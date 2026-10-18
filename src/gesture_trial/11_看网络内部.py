# -*- coding: utf-8 -*-
"""
打开黑箱：看训练出来的网络内部到底长什么样
====================================================================
你在屏幕上看到的只有"输入图片 → 三个概率"。中间那 215,539 个数字到底变成了什么？
这个脚本把三样东西画出来：

  ① 第 1 层卷积的 16 个卷积核（每个只有 3x3）
     —— 训练完之后，它们会变成什么图案？这是"网络到底在看什么"最直接的答案。
  ② 特征图：同一张图喂进去，每一层各"看到"什么
     —— 你会看到浅层是边缘、深层是更整体的形状。
  ③ 【探针测试】给网络喂一些"它从没见过的东西"：
     纯黑、纯白、纯灰、随机噪声
     —— 如果它对纯黑图很自信地说"拳头"，说明它学的是亮度不是形状（捷径学习的铁证）。

用法：
    python 11_看网络内部.py
    python 11_看网络内部.py --model <别的模型路径>

产物：reports/看网络内部.png（三行图）、控制台文字摘要
"""

import os
import sys
import glob
import argparse

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np
import cv2
import tensorflow as tf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 图里要写中文，必须指定一个支持中文的字体，否则会显示成一串方框（tofu）。
# Microsoft YaHei / SimHei 是 Windows 自带的中文字体。
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
CLASSES = ["fist", "palm", "scissors"]
CLASS_CN = {"fist": "握拳", "palm": "手掌", "scissors": "剪刀手"}
IMG_SIZE = 64
DATA_DIR = os.path.join(HERE, "data")
REPORT_DIR = os.path.join(HERE, "reports")


# ---------------------------------------------------------------- 工具
def imread_gray(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    img = cv2.resize(img, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    return img.astype("float32") / 255.0


def to_input(batch):
    """(N,64,64) -> (N,64,64,1)，和训练时喂进去的形状完全一致。"""
    return batch.reshape((-1, IMG_SIZE, IMG_SIZE, 1))


def find_conv_layers(model):
    """把模型里所有 Conv2D 层挑出来（按顺序）。"""
    out = []
    for layer in model.layers:
        if layer.__class__.__name__ == "Conv2D":
            out.append(layer)
    return out


def build_probe_images():
    """探针：网络从没见过的输入。用来测它是不是在走捷径。"""
    h = w = IMG_SIZE
    rng = np.random.default_rng(0)
    return [
        ("纯黑（全 0）", np.zeros((h, w), dtype="float32")),
        ("纯白（全 1）", np.ones((h, w), dtype="float32")),
        ("中性灰（0.5）", np.full((h, w), 0.5, dtype="float32")),
        ("随机噪声", rng.random((h, w)).astype("float32")),
        ("左亮右暗渐变", np.tile(np.linspace(1, 0, w, dtype="float32"), (h, 1))),
    ]


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.join(HERE, "models", "gesture_cnn.keras"),
                    help="模型路径，默认 models/gesture_cnn.keras")
    args = ap.parse_args()

    if not os.path.isfile(args.model):
        print("[错误] 找不到模型：%s" % args.model)
        print("       先双击 重来_存档并采集.cmd 采数据，再双击 训练.cmd 训练出模型。")
        return 1

    os.makedirs(REPORT_DIR, exist_ok=True)
    model = tf.keras.models.load_model(args.model)
    convs = find_conv_layers(model)

    print("=" * 64)
    print("打开黑箱：%s" % os.path.basename(args.model))
    print("=" * 64)
    n_params = int(model.count_params())
    print("总参数量：%d" % n_params)
    print("卷积层：%s" % ", ".join("%s(%s)" % (l.name, l.output.shape[-1]) for l in convs))
    print()

    # ---------- 准备样本图（有真数据就用真数据，没有就用探针图） ----------
    samples, sample_names = [], []
    for c in CLASSES:
        fs = sorted(glob.glob(os.path.join(DATA_DIR, c, "*.jpg")))
        if fs:
            img = imread_gray(fs[0])
            if img is not None:
                samples.append(img)
                sample_names.append("%s (%s)" % (c, CLASS_CN[c]))
    using_real_data = len(samples) > 0
    if not using_real_data:
        print("[提示] data/ 里没有图片，第 1、2 行改用探针图展示网络内部结构。")
        samples = [p[1] for p in build_probe_images()[:3]]
        sample_names = [p[0] for p in build_probe_images()[:3]]

    probes = build_probe_images()
    probe_batch = to_input(np.stack([p[1] for p in probes]))
    probe_probs = model.predict(probe_batch, verbose=0)

    print("-" * 64)
    print("【探针测试】给网络喂它从没见过的东西，看它怎么说")
    print("  一个健康模型的期望：对这些无意义输入【不要】自信地押某一个类")
    print("-" * 64)
    print("  %-16s %s" % ("输入", "  ".join("%-10s" % c for c in CLASSES)))
    for (name, _), probs in zip(probes, probe_probs):
        row = "  ".join("%-10s" % ("%.3f" % p) for p in probs)
        top = CLASSES[int(np.argmax(probs))]
        mark = "  <-- 很自信地押了 %s" % top if float(np.max(probs)) > 0.8 else ""
        print("  %-16s %s%s" % (name, row, mark))
    print()
    spread = float(np.mean(np.max(probe_probs, axis=1)))
    if spread > 0.8:
        print("  [警告] 探针平均最高置信度 %.3f > 0.8：" % spread)
        print("         网络对'纯色/噪声'这类无意义输入仍然很自信 ——")
        print("         这是捷径学习的典型症状：它可能在看亮度，而不是看手的形状。")
    else:
        print("  [OK] 探针平均最高置信度 %.3f，没有对无意义输入盲目自信。" % spread)
    print()

    # ---------- 画图 ----------
    fig = plt.figure(figsize=(14, 11))

    # 第 1 行：conv1 的卷积核
    ax = fig.add_subplot(3, 1, 1)
    ax.set_title("(1) 第 1 层卷积的卷积核：训练之后，每个 3x3 的小窗变成了什么图案？", fontsize=11)
    if convs:
        w = convs[0].get_weights()[0]          # (3,3,in_ch,out_ch)
        n_show = min(w.shape[-1], 16)
        grid = np.zeros((2 * 4, 2 * 4), dtype="float32")
        for i in range(n_show):
            k = w[:, :, 0, i]
            k = (k - k.min()) / (k.max() - k.min() + 1e-8)
            r, c = divmod(i, 4)
            grid[r * 2:r * 2 + 2, c * 2:c * 2 + 2] = cv2.resize(k, (2, 2), interpolation=cv2.INTER_NEAREST)
        ax.imshow(grid, cmap="gray", interpolation="nearest")
        ax.text(1.02, 0.5, "每个 2x2 格子 = 一个 3x3 卷积核\n（放大显示）", transform=ax.transAxes,
                fontsize=9, va="center")
    else:
        ax.text(0.5, 0.5, "没找到卷积层", ha="center")
    ax.set_xticks([]); ax.set_yticks([])

    # 第 2 行：特征图（逐层）
    ax = fig.add_subplot(3, 1, 2)
    ax.set_title("(2) 特征图：同一张图喂进去，每一层各'看到'什么（每层取前 8 个通道）", fontsize=11)
    row = None
    if convs and samples:
        # 注意：Keras 3 里 load 回来的模型 model.input 可能不可用
        # （报 "The layer ... has never been called"），
        # 所以这里不走子模型，而是手动按顺序逐层调用，顺手把卷积输出截下来。
        x = tf.constant(to_input(np.stack([samples[0]])), dtype="float32")
        strips = []
        try:
            for layer in model.layers:
                x = layer(x, training=False)
                if layer.__class__.__name__ == "Conv2D":
                    fmap = np.asarray(x)[0]                     # (H,W,C)
                    n = min(fmap.shape[-1], 8)
                    strips.append(np.hstack([
                        cv2.resize(fmap[:, :, i], (IMG_SIZE, IMG_SIZE),
                                   interpolation=cv2.INTER_NEAREST)
                        for i in range(n)
                    ]))
        except Exception as exc:                                # noqa: BLE001
            print("[警告] 逐层前向失败，跳过第 2 行：%s" % exc)
        if strips:
            row = np.vstack(strips)
    if row is not None:
        row = (row - row.min()) / (row.max() - row.min() + 1e-8)
        ax.imshow(row, cmap="viridis", aspect="auto", interpolation="nearest")
        for i, l in enumerate(convs):
            ax.text(-1, (i + 0.5) * IMG_SIZE, l.name, fontsize=9, ha="right", va="center")
        ax.text(0.0, 1.02, "输入样例：%s" % sample_names[0], transform=ax.transAxes, fontsize=9)
    else:
        ax.text(0.5, 0.5, "没有可用的样例图", ha="center")
    ax.set_xticks([]); ax.set_yticks([])

    # 第 3 行：探针测试的柱状图
    ax = fig.add_subplot(3, 1, 3)
    ax.set_title("(3) 探针测试：喂无意义输入时，三个类别的概率各是多少？", fontsize=11)
    xs = np.arange(len(probes))
    width = 0.25
    for j, c in enumerate(CLASSES):
        vals = [float(probe_probs[i][j]) for i in range(len(probes))]
        ax.bar(xs + (j - 1) * width, vals, width, label=c)
    ax.axhline(0.8, color="red", linestyle="--", linewidth=1)
    ax.text(len(probes) - 0.5, 0.82, "0.8 = 危险线", color="red", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels([p[0] for p in probes], fontsize=9)
    ax.set_ylabel("softmax 概率")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=9)

    fig.tight_layout()
    out_png = os.path.join(REPORT_DIR, "看网络内部.png")
    fig.savefig(out_png, dpi=110)
    plt.close(fig)

    print("=" * 64)
    print("图已保存：%s" % out_png)
    print("  第 1 行 = 卷积核（它学会了找什么图案）")
    print("  第 2 行 = 特征图（每层各看到什么）")
    print("  第 3 行 = 探针测试（它有没有在走捷径）")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
