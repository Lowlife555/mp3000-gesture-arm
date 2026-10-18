"""
03 量化：float32 keras → int8 tflite

体积大约降到 1/4，精度掉多少要自己测，别信口说。

⚠️ 设计要点：
  1) 模型图里不该有 Random* 增强层（02_train.py 已把增强移到 dataset 管道）。
     这里再查一次，出现就报错退出 —— 否则 Pi 上每张图推理前都会被随机翻转。
  2) 输入固定 uint8（Pi 直接喂原始像素），输出保持 float32
     （softmax 概率只占 8 bit 会丢精度，没必要）。
  3) 导出前后各评一次验证集：量化前后准确率都要报出来。
"""
import json
import pathlib
import time

import tensorflow as tf

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS = ROOT / "src" / "trashnet_trial" / "models"
VAL = ROOT / "data" / "trashnet_split" / "val"

meta = json.loads((MODELS / "meta.json").read_text(encoding="utf-8"))
CLASSES = meta["class_names"]
IMG = meta["img_size"]
TRAIN_ACC = meta["val_accuracy"]

print(f"加载: {MODELS / 'trashnet_mobilenetv2.keras'}")
model = tf.keras.models.load_model(MODELS / "trashnet_mobilenetv2.keras")
print("层清单:", [(l.name, type(l).__name__) for l in model.layers])

# ── 1. 安全断言：模型里不能有随机增强层 ───────────────────────────────
bad = [f"{l.name}({type(l).__name__})" for l in model.layers
       if "random" in type(l).__name__.lower() or "augment" in l.name.lower()]
if bad:
    raise SystemExit(f"❌ 模型图里含随机层 {bad} —— 导出后 Pi 上结果不可重复，先改 02_train.py")
print("✅ 模型图无随机增强层")

val_ds = tf.keras.utils.image_dataset_from_directory(
    VAL, image_size=(IMG, IMG), batch_size=32, shuffle=False)
print("验证类别:", val_ds.class_names, "| 批数:", len(val_ds))
assert val_ds.class_names == CLASSES, "验证集类别顺序与训练不一致"

# ── 2. 量化前的基准 ───────────────────────────────────────────────────
model.compile(optimizer="adam", loss="sparse_categorical_crossentropy",
              metrics=["accuracy"])
_, acc_f32 = model.evaluate(val_ds, verbose=0)
print(f"\n量化前（float32 keras）val_acc = {acc_f32:.4f}  (训练记录 {TRAIN_ACC:.4f})")

# ── 3. 代表性数据集（必须真实图片）────────────────────────────────────
rep_ds = tf.keras.utils.image_dataset_from_directory(
    VAL, image_size=(IMG, IMG), batch_size=1, shuffle=True, seed=0)


def representative():
    n = 0
    for images, _ in rep_ds:
        if n >= 100:
            break
        yield [tf.cast(images, tf.float32)]
        n += 1
    print(f"  代表性样本数: {n}")


# ── 4. 转 int8 ────────────────────────────────────────────────────────
converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.uint8

print("\n转换中（1-3 分钟）...")
t0 = time.time()
tflite = converter.convert()
print(f"转换完成，用时 {time.time() - t0:.0f} s")

out = MODELS / "trashnet_mobilenetv2_int8.tflite"
out.write_bytes(tflite)

keras_bytes = (MODELS / "trashnet_mobilenetv2.keras").stat().st_size
print(f"\nkeras 文件  : {keras_bytes / 1024 / 1024:8.2f} MB")
print(f"tflite int8 : {len(tflite) / 1024 / 1024:8.2f} MB")
print(f"压缩比      : {keras_bytes / len(tflite):8.2f}×")
print(f"已保存      : {out}")

# ── 5. 用 tflite 自己再评一次（真实精度，不是 keras 的）───────────────
interp = tf.lite.Interpreter(model_path=str(out))
interp.allocate_tensors()
inp = interp.get_input_details()[0]
oup = interp.get_output_details()[0]
print(f"\n输入: {inp['shape']} {inp['dtype'].__name__}  quant={inp['quantization']}")
print(f"输出: {oup['shape']} {oup['dtype'].__name__}  quant={oup['quantization']}")

import numpy as np  # noqa: E402

correct = total = 0
for images, labels in val_ds:
    for k in range(images.shape[0]):
        arr = tf.cast(images[k], tf.uint8).numpy()
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        interp.set_tensor(inp["index"], arr[None, ...])
        interp.invoke()
        probs = interp.get_tensor(oup["index"])[0].astype(np.float32)
        scale, zero = oup["quantization"]
        if scale:
            probs = (probs - zero) * scale
        correct += int(int(np.argmax(probs)) == int(labels[k]))
        total += 1
acc_int8 = correct / total if total else float("nan")
print(f"\n量化后（int8 tflite）val_acc = {acc_int8:.4f}  (n={total})")
print(f"精度变化: {acc_f32:.4f} → {acc_int8:.4f}  (Δ {acc_int8 - acc_f32:+.4f})")

meta.update({
    "tflite_int8_bytes": len(tflite),
    "keras_bytes": int(keras_bytes),
    "compression_ratio": round(keras_bytes / len(tflite), 2),
    "val_accuracy_float32": float(acc_f32),
    "val_accuracy_int8": float(acc_int8),
    "tflite_input": {"shape": [int(v) for v in inp["shape"]],
                     "dtype": inp["dtype"].__name__},
    "tflite_output": {"shape": [int(v) for v in oup["shape"]],
                      "dtype": oup["dtype"].__name__},
})
(MODELS / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
print(f"已更新: {MODELS / 'meta.json'}")
