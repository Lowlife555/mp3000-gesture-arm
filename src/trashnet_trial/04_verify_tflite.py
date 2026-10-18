"""
04 验证：用 tflite 解释器在【验证集】上逐类抽检 + 测单帧延迟

⚠️ 抽样必须来自 trashnet_split/val（训练从未见过）。
   从 dataset-resized 抽会抽到训练图，看着漂亮但什么也没证明。

⚠️ 这里的延迟是【PC 的】，不是树莓派的 —— Pi 上会慢一个量级，到阶段 3 再实测。
"""
import json
import pathlib
import statistics
import time

import numpy as np
import tensorflow as tf

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS = ROOT / "src" / "trashnet_trial" / "models"
VAL = ROOT / "data" / "trashnet_split" / "val"

meta = json.loads((MODELS / "meta.json").read_text(encoding="utf-8"))
CLASSES = meta["class_names"]
IMG = meta["img_size"]

TFLITE = MODELS / "trashnet_mobilenetv2_int8.tflite"
interp = tf.lite.Interpreter(model_path=str(TFLITE))
interp.allocate_tensors()
inp = interp.get_input_details()[0]
oup = interp.get_output_details()[0]
print("模型:", TFLITE.name)
print("输入:", inp["shape"], inp["dtype"].__name__, "| 输出:", oup["shape"], oup["dtype"].__name__)
print("类别:", CLASSES)
print("抽样来源（训练未见过的验证集）:", VAL)
print()


def predict(path):
    raw = tf.io.read_file(str(path))
    img = tf.io.decode_image(raw, channels=3, expand_animations=False)
    img = tf.image.resize(img, (IMG, IMG), method="bilinear")
    arr = tf.cast(img, tf.uint8).numpy()[None, ...]

    interp.set_tensor(inp["index"], arr)
    t0 = time.perf_counter()
    interp.invoke()
    ms = (time.perf_counter() - t0) * 1000

    probs = interp.get_tensor(oup["index"])[0].astype(np.float32)
    scale, zero = oup["quantization"]
    if scale:
        probs = (probs - zero) * scale
    if probs.sum() > 0:
        probs = probs / probs.sum()
    top = int(np.argmax(probs))
    return CLASSES[top], float(probs[top]), ms


ok = total = 0
lat = []
per_class = {}
for cls_dir in sorted(p for p in VAL.iterdir() if p.is_dir()):
    pics = sorted(cls_dir.glob("*.jpg"))[:3] or sorted(cls_dir.glob("*.png"))[:3]
    if not pics:
        continue
    c_ok = 0
    for pic in pics:
        label, conf, ms = predict(pic)
        good = label == cls_dir.name
        c_ok += int(good)
        ok += int(good)
        total += 1
        lat.append(ms)
        print(f"{'✅' if good else '❌'} 真值={cls_dir.name:<10} 预测={label:<10} "
              f"置信度={conf:6.2%}  {ms:7.2f} ms")
    per_class[cls_dir.name] = (c_ok, len(pics))

print(f"\n抽检命中: {ok}/{total} = {ok / total:.1%}")
for c, (a, n) in per_class.items():
    print(f"  {c:<11} {a}/{n}")

# 单帧延迟：拿第一张图跑 20 次取中位
first = next(iter(sorted(VAL.glob("*/*.jpg"))))
raw = tf.io.read_file(str(first))
img = tf.cast(tf.image.resize(tf.io.decode_image(raw, channels=3, expand_animations=False),
                              (IMG, IMG), method="bilinear"), tf.uint8).numpy()[None, ...]
runs = []
for _ in range(20):
    interp.set_tensor(inp["index"], img)
    t0 = time.perf_counter()
    interp.invoke()
    runs.append((time.perf_counter() - t0) * 1000)
print(f"\n单帧延迟（PC，20 次）: 中位 {statistics.median(runs):.2f} ms | "
      f"最小 {min(runs):.2f} | 最大 {max(runs):.2f}")
print("\n⚠️ 这是 PC 的数字。树莓派上会慢一个量级 —— 到阶段 3 在 Pi 上实测。")
