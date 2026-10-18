# -*- coding: utf-8 -*-
"""
MP3000 / YZ3 试跑 · 流水线自检（用合成数据验证代码能跑通）
=========================================================
作用：**在没有摄像头、没有真实数据的情况下**，验证 02_train.py / 04_quantize.py
      这两步的代码逻辑与依赖安装是否正常。

它会在 data/<类别>/ 下生成一批**合成图片**（文件名以 fake_ 开头）：
    fist     → 中间一个实心圆（模拟握拳的一团）
    palm     → 若干竖直条（模拟张开的手指）
    scissors → 两条斜条组成 V 形（模拟剪刀手）

安全性设计（防止污染真实数据）：
  - 如果 data/ 里已经存在**非 fake_** 的图片，脚本直接拒绝运行；
  - 用 --clean 可以一键删掉所有 fake_*.jpg。

⚠️ 合成数据训出来的模型**不能拿去演示**，它只证明"代码能跑"。

用法：
    python 00_selftest.py            # 生成合成数据
    python 02_train.py               # 验证训练
    python 04_quantize.py            # 验证量化
    python 00_selftest.py --clean    # 删掉合成数据
"""

import os
import glob
import argparse

import numpy as np
import cv2

CLASSES = ["fist", "palm", "scissors"]
IMG_SIZE = 64
PER_CLASS = 150

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")


def draw_fist(rng):
    img = np.full((IMG_SIZE, IMG_SIZE), 200, np.uint8)
    cx = 32 + int(rng.integers(-4, 5))
    cy = 34 + int(rng.integers(-4, 5))
    r = 16 + int(rng.integers(-3, 4))
    cv2.circle(img, (cx, cy), r, 40, -1)
    return img


def draw_palm(rng):
    img = np.full((IMG_SIZE, IMG_SIZE), 200, np.uint8)
    n = 4 + int(rng.integers(0, 2))
    for i in range(n):
        x = 14 + i * 9 + int(rng.integers(-2, 3))
        y0 = 12 + int(rng.integers(-3, 4))
        y1 = 52 + int(rng.integers(-4, 3))
        cv2.line(img, (x, y0), (x + int(rng.integers(-2, 3)), y1), 40, 4)
    return img


def draw_scissors(rng):
    img = np.full((IMG_SIZE, IMG_SIZE), 200, np.uint8)
    base = (32 + int(rng.integers(-3, 4)), 54)
    for dx in (-12, 12):
        tip = (32 + dx + int(rng.integers(-3, 4)), 10 + int(rng.integers(-4, 5)))
        cv2.line(img, base, tip, 40, 5)
    return img


DRAWERS = {"fist": draw_fist, "palm": draw_palm, "scissors": draw_scissors}


def add_noise(img, rng):
    noise = rng.normal(0, 10, img.shape)
    img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    # 随机亮度扰动
    img = np.clip(img.astype(np.float32) * float(rng.uniform(0.8, 1.2)), 0, 255).astype(np.uint8)
    # 随机小位移，逼模型学形状而不是位置
    dx, dy = int(rng.integers(-3, 4)), int(rng.integers(-3, 4))
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, M, (IMG_SIZE, IMG_SIZE), borderValue=200)


def real_images_exist():
    for c in CLASSES:
        d = os.path.join(DATA_DIR, c)
        if not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, "*.jpg")):
            if not os.path.basename(f).startswith("fake_"):
                return f
    return None


def clean():
    n = 0
    for c in CLASSES:
        for f in glob.glob(os.path.join(DATA_DIR, c, "fake_*.jpg")):
            os.remove(f)
            n += 1
    print("已删除 %d 张合成图片。" % n)
    for c in CLASSES:
        d = os.path.join(DATA_DIR, c)
        left = len(glob.glob(os.path.join(d, "*.jpg"))) if os.path.isdir(d) else 0
        print("  %-9s 剩余 %d 张" % (c, left))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="删除所有 fake_*.jpg")
    ap.add_argument("--per-class", type=int, default=PER_CLASS)
    args = ap.parse_args()

    if args.clean:
        clean()
        return 0

    bad = real_images_exist()
    if bad:
        print("[拒绝运行] data/ 里已经有真实采集的图片：%s" % bad)
        print("           合成数据会和真实数据混在一起，必须先清空或改用别的目录。")
        print("           如果你确认要清掉合成数据，运行：python 00_selftest.py --clean")
        return 1

    rng = np.random.default_rng(7)
    print("生成合成数据（仅供代码自检，不可用于演示）...")
    for c in CLASSES:
        d = os.path.join(DATA_DIR, c)
        os.makedirs(d, exist_ok=True)
        for f in glob.glob(os.path.join(d, "fake_*.jpg")):
            os.remove(f)
        for i in range(args.per_class):
            img = DRAWERS[c](rng)
            img = add_noise(img, rng)
            cv2.imwrite(os.path.join(d, "fake_%03d.jpg" % i), img)
        print("  %-9s 生成 %d 张" % (c, args.per_class))

    print("\n合成数据就绪。现在跑：")
    print("  python 02_train.py")
    print("  python 04_quantize.py")
    print("验证完记得清理：python 00_selftest.py --clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
