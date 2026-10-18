"""
02 训练：MobileNetV2 迁移学习（两阶段）+ 存 keras 模型

⚠️ 两处关键设计（都是踩过坑之后改的）：
  1) 训练/验证来自 00_split.py 生成的 trashnet_split/{train,val}
     —— 不用 image_dataset_from_directory 的 validation_split，那个不分层。
  2) 数据增强放在【dataset 管道】里，不放进模型图。
     —— 放模型里的话，导出 TFLite 时 RandomFlip/Rotation/Zoom 会被编进去，
        Pi 上每张图推理前都被随机翻转缩放，结果不可重复。

环境变量：
  TRASHNET_EPOCHS  每阶段轮数（默认 8；想快速验证管道就设 2）
"""
import json
import os
import pathlib
import time

import tensorflow as tf

ROOT = pathlib.Path(__file__).resolve().parents[2]
TRAIN = ROOT / "data" / "trashnet_split" / "train"
VAL = ROOT / "data" / "trashnet_split" / "val"
OUT = ROOT / "src" / "trashnet_trial" / "models"
OUT.mkdir(parents=True, exist_ok=True)

IMG = 224
BATCH = 32
SEED = 1337
EPOCHS = int(os.environ.get("TRASHNET_EPOCHS", "8"))

print(f"训练集: {TRAIN}")
print(f"验证集: {VAL}")
print(f"每阶段轮数: {EPOCHS} | TF: {tf.__version__}")
if not TRAIN.is_dir():
    raise SystemExit("找不到训练集，先跑 00_split.py")

# ── 1. 数据 ───────────────────────────────────────────────────────────
train_raw = tf.keras.utils.image_dataset_from_directory(
    TRAIN, image_size=(IMG, IMG), batch_size=BATCH, seed=SEED, shuffle=True)
val_raw = tf.keras.utils.image_dataset_from_directory(
    VAL, image_size=(IMG, IMG), batch_size=BATCH, shuffle=False)
CLASS_NAMES = train_raw.class_names
print("类别:", CLASS_NAMES)
print(f"训练批数: {len(train_raw)} | 验证批数: {len(val_raw)}")

val_names = sorted(p.name for p in VAL.iterdir() if p.is_dir())
if val_names != CLASS_NAMES:
    raise SystemExit(f"训练/验证类别不一致: {CLASS_NAMES} vs {val_names}")
print("✅ 训练集与验证集类别一致，验证集含全部类别")

# 增强器：独立层，只用在训练管道上，不进模型图
augmenter = tf.keras.Sequential([
    tf.keras.layers.RandomFlip("horizontal"),
    tf.keras.layers.RandomRotation(0.08),
    tf.keras.layers.RandomZoom(0.10),
], name="augmenter")

AUTOTUNE = tf.data.AUTOTUNE
train_ds = (train_raw
            .map(lambda x, y: (augmenter(x, training=True), y),
                 num_parallel_calls=AUTOTUNE)
            .cache().prefetch(AUTOTUNE))
val_ds = val_raw.cache().prefetch(AUTOTUNE)

# ── 2. 模型（⚠️ 里面没有任何 Random 层）────────────────────────────────
print("加载 MobileNetV2 ImageNet 权重...")
base = tf.keras.applications.MobileNetV2(
    input_shape=(IMG, IMG, 3), include_top=False, weights="imagenet")
base.trainable = False
print("权重就绪")

inputs = tf.keras.Input(shape=(IMG, IMG, 3), name="image")
x = tf.keras.layers.Rescaling(1.0 / 127.5, offset=-1.0, name="rescale")(inputs)
x = base(x, training=False)
x = tf.keras.layers.GlobalAveragePooling2D(name="gap")(x)
x = tf.keras.layers.Dropout(0.2)(x)
outputs = tf.keras.layers.Dense(len(CLASS_NAMES), activation="softmax", name="pred")(x)
model = tf.keras.Model(inputs, outputs, name="trashnet_mobilenetv2")

bad = [l.name for l in model.layers if "random" in type(l).__name__.lower()]
if bad:
    raise SystemExit(f"模型里混进了随机层，导出会坏: {bad}")
print("✅ 模型图里没有随机增强层")
model.summary()

CKPT = OUT / "best.keras"


class TimeIt(tf.keras.callbacks.Callback):
    def on_epoch_begin(self, epoch, logs=None):
        self.t0 = time.time()

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}
        print(f"  ⏱️  第 {epoch + 1} 轮 {time.time() - self.t0:.1f} s  "
              f"acc={logs.get('accuracy', float('nan')):.4f} "
              f"val_acc={logs.get('val_accuracy', float('nan')):.4f}")


callbacks = [
    tf.keras.callbacks.ModelCheckpoint(CKPT, monitor="val_accuracy",
                                       save_best_only=True, verbose=1),
    tf.keras.callbacks.EarlyStopping(monitor="val_accuracy", patience=6,
                                     restore_best_weights=True),
    tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                         patience=2, verbose=1),
    TimeIt(),
]

# ── 3. 阶段 A：冻结骨干 ───────────────────────────────────────────────
print("\n=== 阶段 A：冻结骨干 ===")
tA = time.time()
model.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
              loss="sparse_categorical_crossentropy", metrics=["accuracy"])
model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS, callbacks=callbacks)
print(f"阶段 A 总用时 {time.time() - tA:.0f} s")

# ── 4. 阶段 B：微调最后 30 层 ─────────────────────────────────────────
print("\n=== 阶段 B：微调最后 30 层 ===")
tB = time.time()
base.trainable = True
for layer in base.layers[:-30]:
    layer.trainable = False
model.compile(optimizer=tf.keras.optimizers.Adam(1e-5),
              loss="sparse_categorical_crossentropy", metrics=["accuracy"])
model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS, callbacks=callbacks)
print(f"阶段 B 总用时 {time.time() - tB:.0f} s")

# ── 5. 存盘 + meta ────────────────────────────────────────────────────
best = tf.keras.models.load_model(CKPT)
loss, acc = best.evaluate(val_ds, verbose=0)
best.save(OUT / "trashnet_mobilenetv2.keras")
print(f"\n最佳模型验证集: loss={loss:.4f}  acc={acc:.4f}")
print(f"已保存: {OUT / 'trashnet_mobilenetv2.keras'}")

n_train = sum(len(list(d.iterdir())) for d in TRAIN.iterdir() if d.is_dir())
n_val = sum(len(list(d.iterdir())) for d in VAL.iterdir() if d.is_dir())
meta = {
    "class_names": CLASS_NAMES, "img_size": IMG,
    "val_accuracy": float(acc), "val_loss": float(loss),
    "split": "stratified 00_split.py (per-class 15%)",
    "n_train": n_train, "n_val": n_val,
    "source": "garythung/trashnet (MIT)",
    "backbone": "MobileNetV2",
    "epochs_per_stage": EPOCHS, "seed": SEED,
    "tf_version": tf.__version__,
    "augment_location": "dataset pipeline (not in model graph)",
}
(OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                              encoding="utf-8")
print(f"已保存: {OUT / 'meta.json'}")
print(f"训练 {n_train} 张 / 验证 {n_val} 张（分层）")
