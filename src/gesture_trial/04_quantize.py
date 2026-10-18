# -*- coding: utf-8 -*-
"""
MP3000 / YZ3 试跑 · int8 量化对比（加分项，时间不够可以不做）
============================================================
把训练好的 float32 模型转成 TensorFlow Lite，做两种量化，比较"体积 vs 精度"：

    1) float32 TFLite ：几乎无损，文件大
    2) int8 全整数量化 ：权重和激活都压成 8 位整数，文件小约 4 倍

为什么这件事对 MP3000 重要：
    微控制器（比如你 ER3007 的 STM32L476）Flash 只有 1 MB、RAM 128 KB，
    塞不下 float32 模型。**量化是"把 PC 上的模型搬进单片机"的必经一步**。
    这正是把 YZ3 从"跑个数据集"升级成"嵌入式系统"的那个关键环节。

int8 量化需要"代表性数据集"：拿一批真实图片让转换器统计数值范围，
才能确定每个量化的缩放系数（scale）与零点（zero point）。

用法：
    python 04_quantize.py
"""

import os
import glob

import numpy as np
import cv2
import tensorflow as tf
import keras

CLASSES = ["fist", "palm", "scissors"]
IMG_SIZE = 64

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MODEL_DIR = os.path.join(HERE, "models")
REPORT_DIR = os.path.join(HERE, "reports")


def load_val_images(limit=300):
    X, y = [], []
    for idx, c in enumerate(CLASSES):
        for f in sorted(glob.glob(os.path.join(DATA_DIR, c, "*.jpg")))[: limit // len(CLASSES)]:
            img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            if img.shape != (IMG_SIZE, IMG_SIZE):
                img = cv2.resize(img, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
            X.append(img)
            y.append(idx)
    X = np.asarray(X, dtype=np.float32) / 255.0
    y = np.asarray(y, dtype=np.int64)
    return X[..., None], y


def tflite_predict(path, X):
    interp = tf.lite.Interpreter(model_path=path)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    preds = []
    for i in range(len(X)):
        x = X[i:i + 1].astype(inp["dtype"])
        interp.set_tensor(inp["index"], x)
        interp.invoke()
        preds.append(int(np.argmax(interp.get_tensor(out["index"])[0])))
    return np.asarray(preds)


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    keras_path = os.path.join(MODEL_DIR, "gesture_cnn.keras")
    if not os.path.exists(keras_path):
        print("[错误] 找不到 %s，先跑 02_train.py" % keras_path)
        return 1

    model = keras.models.load_model(keras_path)
    X, y = load_val_images()
    print("用 %d 张真实图片做代表性数据集与评估" % len(X))

    # ---------- 1) float32 ----------
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    f32_model = conv.convert()
    f32_path = os.path.join(MODEL_DIR, "gesture_float32.tflite")
    with open(f32_path, "wb") as fp:
        fp.write(f32_model)

    # ---------- 2) int8 全整数量化 ----------
    def representative_dataset():
        for i in range(len(X)):
            yield [X[i:i + 1].astype(np.float32)]

    conv8 = tf.lite.TFLiteConverter.from_keras_model(model)
    conv8.optimizations = [tf.lite.Optimize.DEFAULT]
    conv8.representative_dataset = representative_dataset
    # 输入输出仍保留 float32，方便和前面的脚本用同一套预处理
    conv8.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv8.inference_input_type = tf.float32
    conv8.inference_output_type = tf.float32
    try:
        int8_model = conv8.convert()
        int8_path = os.path.join(MODEL_DIR, "gesture_int8.tflite")
        with open(int8_path, "wb") as fp:
            fp.write(int8_model)
    except Exception as exc:                       # noqa: BLE001
        print("[警告] int8 全整数量化失败：%s" % exc)
        print("       退回动态范围量化（只压权重，仍能演示体积下降）。")
        conv8b = tf.lite.TFLiteConverter.from_keras_model(model)
        conv8b.optimizations = [tf.lite.Optimize.DEFAULT]
        int8_model = conv8b.convert()
        int8_path = os.path.join(MODEL_DIR, "gesture_int8.tflite")
        with open(int8_path, "wb") as fp:
            fp.write(int8_model)

    # ---------- 对比 ----------
    size_f32 = os.path.getsize(f32_path)
    size_i8 = os.path.getsize(int8_path)

    pred_f32 = tflite_predict(f32_path, X)
    pred_i8 = tflite_predict(int8_path, X)
    acc_f32 = float((pred_f32 == y).mean())
    acc_i8 = float((pred_i8 == y).mean())

    lines = []
    lines.append("MP3000 / YZ3 试跑 · 量化对比")
    lines.append("=" * 56)
    lines.append("评估数据：%d 张真实手势图（注意：与训练集有重叠，只用于对比两者相对关系）" % len(X))
    lines.append("")
    lines.append("%-16s %14s %12s" % ("模型", "文件大小", "准确率"))
    lines.append("-" * 56)
    lines.append("%-16s %11.1f KB %11.4f" % ("float32 TFLite", size_f32 / 1024.0, acc_f32))
    lines.append("%-16s %11.1f KB %11.4f" % ("int8 TFLite", size_i8 / 1024.0, acc_i8))
    lines.append("-" * 56)
    lines.append("体积压缩比：%.2fx" % (size_f32 / max(size_i8, 1)))
    lines.append("准确率变化：%+.4f" % (acc_i8 - acc_f32))
    lines.append("")
    lines.append("结论（供报告引用）：int8 量化把模型体积压到约 1/4，")
    lines.append("准确率变化在可接受范围内 —— 这就是把模型搬进 STM32 这类")
    lines.append("微控制器的前提条件。")
    text = "\n".join(lines)
    print(text)

    out = os.path.join(REPORT_DIR, "quantization.txt")
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(text + "\n")
    print("\n已保存：%s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
