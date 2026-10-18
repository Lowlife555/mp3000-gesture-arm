# -*- coding: utf-8 -*-
"""
MP3000 / YZ3 试跑 · 手势数据采集
=================================
用笔记本自带摄像头采集三类手势图片，作为神经网络的训练数据。

为什么自己采数据（而不是下载 MNIST 之类）：
  1. 数据是自己造的 —— 这是"动手能力"最硬的证据，别人没法复制；
  2. 采集过程会自然产生光照 / 距离 / 角度的变化，逼着模型学"形状"而不是"死记像素"；
  3. 图片留在磁盘上，随时能复现、能重训。

操作说明：
  1 / 2 / 3   切换当前要采集的类别（fist=握拳 / palm=手掌 / scissors=剪刀手）
  空格        开始 / 停止 连续采集
  q           退出

三个设计要点（它们直接决定最后能不能实时识别准）：
  - 画面水平镜像：像照镜子，抬手方向和直觉一致，演示时不会左右颠倒；
  - 只保存中间方框（ROI）里的内容：把背景变化挡在门外，模型只看手；
  - 统一存成 64x64 灰度图：数据量小，纯 CPU 也训得动。

采集时请刻意做这些变化（很重要，不然明天现场容易翻车）：
  - 手离摄像头 30cm / 50cm / 80cm 各采一些；
  - 手在框内偏左 / 居中 / 偏右 各采一些；
  - 开灯 / 关灯、手心朝镜头 / 稍微侧一点 各采一些；
  - 每类至少 200 张，500 张更好。
"""

import os
import time
import argparse

import cv2

# ---------------------------------------------------------------- 配置
CLASSES = ["fist", "palm", "scissors"]
CLASS_HINT = {"fist": "握拳", "palm": "手掌", "scissors": "剪刀手"}
IMG_SIZE = 64          # 存盘尺寸（和训练脚本保持一致）
WORK_WIDTH = 960       # 画面先缩到这个宽度再处理（1080p 原图处理太慢）
ROI_FRAC = 0.55        # 采集方框边长 = 画面高度 × 这个比例
SAVE_INTERVAL = 0.08   # 连续采集时每 80ms 存一帧（约 12 张/秒）
MAX_PER_CLASS = 800    # 单类上限，防止手一直按着存爆

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")


def ensure_dirs():
    for c in CLASSES:
        os.makedirs(os.path.join(OUT_DIR, c), exist_ok=True)


def count_saved():
    """数一数每类已经存了多少张。"""
    counts = {}
    for c in CLASSES:
        d = os.path.join(OUT_DIR, c)
        counts[c] = len([f for f in os.listdir(d) if f.lower().endswith(".jpg")])
    return counts


def class_stats(class_name):
    """统计某一类已存图片的平均亮度和对比度。

    为什么要盯这两个数：如果某一类的框里其实是纯背景（白墙、桌面），
    它的平均亮度会明显偏离其他类、对比度会特别低。
    这种情况下网络会走"捷径"—— 不看手的形状，只看框里有多亮，
    在验证集上照样能拿高分，一到现场就废。
    """
    d = os.path.join(OUT_DIR, class_name)
    files = [f for f in os.listdir(d) if f.lower().endswith(".jpg")]
    means, stds = [], []
    for f in files:
        img = cv2.imread(os.path.join(d, f), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        means.append(float(img.mean()))
        stds.append(float(img.std()))
    if not means:
        return None
    return {"n": len(means), "mean": sum(means) / len(means), "std": sum(stds) / len(stds)}


def sanity_report():
    """采集结束后做一次"数据健康检查"，专门抓捷径学习。"""
    print("=" * 60)
    print("数据健康检查（别跳过，这一步能省掉一整轮返工）")
    print("-" * 60)
    stats = {}
    for c in CLASSES:
        s = class_stats(c)
        stats[c] = s
        if s is None:
            print("  %-9s 没有图片" % c)
        else:
            print("  %-9s n=%-4d 框内平均亮度=%6.1f  对比度(std)=%5.1f"
                  % (c, s["n"], s["mean"], s["std"]))

    present = [c for c in CLASSES if stats[c]]
    problems = []

    # 检查 1：某一类几乎全是纯色背景 → 那类根本没采到手
    for c in present:
        if stats[c]["std"] < 20:
            problems.append("%s 的框内对比度只有 %.1f（<20）—— 几乎是一张纯色背景，"
                            "手很可能在框外。" % (c, stats[c]["std"]))

    # 检查 2：各类亮度差别太大 → 网络可以只看亮度就分类，不必看手的形状
    if len(present) >= 2:
        means = [stats[c]["mean"] for c in present]
        spread = max(means) - min(means)
        if spread > 25:
            order = sorted(present, key=lambda c: stats[c]["mean"])
            problems.append(
                "各类亮度差 %.1f（>25）：%s。类别和背景明暗绑在一起，"
                "网络大概率会走捷径（只看亮度、不看手的形状）——"
                "验证集会很漂亮，现场会翻车。"
                % (spread, " < ".join("%s(%.0f)" % (c, stats[c]["mean"]) for c in order)))

    if problems:
        print("-" * 60)
        print("[警告] 发现 %d 个问题：" % len(problems))
        for i, p in enumerate(problems, 1):
            print("  %d) %s" % (i, p))
        print()
        print("怎么修：重新采集。三个要点：")
        print("  1) 每一类都在【同样的机位和光照】下采；")
        print("  2) 看右下角小图，确认【手确实占满框】（std 低于 20 会弹橙色警告）；")
        print("  3) 三类【交错】着采（每类 60 张一轮，轮 3~4 轮），")
        print("     别把一整类连续采完 —— 那样机位/光照漂移会直接变成类别特征。")
        print("[建议] 出现上面任何一条，先别往下训练。")
    else:
        print("-" * 60)
        print("[OK] 没发现明显的捷径学习隐患（各类亮度接近、框内都有内容）。")
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0, help="摄像头编号，一般 0 就是自带摄像头")
    args = ap.parse_args()

    ensure_dirs()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print("[错误] 打不开摄像头 (index=%d)。" % args.camera)
        print("       常见原因：Zoom / Teams / 浏览器正在占用摄像头，或 Windows 隐私设置里禁用了相机。")
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    current = CLASSES[0]
    recording = False
    last_save = 0.0
    counts = count_saved()

    print(__doc__)
    print("=" * 60)
    print("!! 采集前必做：关掉 Windows 工作室效果（Studio Effects）")
    print("   它的【自动取景】会跟着你的脸自动变焦，把脸一直放在画面中心 ——")
    print("   于是中间的 ROI 框里装的永远是脸，手举在哪儿都进不去。")
    print("   2026-10-07 的第一次采集就是这样被毁掉的（证据图 _badrun_证据_数据长什么样.png）。")
    print("   关闭：任务栏右下角点 网络/音量/电池 图标 -> Studio Effects 磁贴 -> 关")
    print("         或 设置 > 蓝牙和其他设备 > 摄像头 > 选前置摄像头 -> 关闭 Studio Effects")
    print("   验证：头左右移动，画面【不应该】跟着变焦。")
    print("=" * 60)
    print("当前类别：%s（%s）" % (current, CLASS_HINT[current]))
    print("=" * 60)

    win = "MP3000 / YZ3 - gesture capture"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)

    while True:
        ok, frame = cap.read()
        if not ok:
            print("[错误] 读不到画面，摄像头可能被拔掉或被占用了。")
            break

        # 水平镜像，像照镜子
        frame = cv2.flip(frame, 1)

        # 1080p 原图处理太慢，先缩到 WORK_WIDTH 宽（采集与实时识别必须同一套处理）
        h, w = frame.shape[:2]
        if w > WORK_WIDTH:
            frame = cv2.resize(frame, (WORK_WIDTH, int(round(h * WORK_WIDTH / w))),
                               interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]

        # 画面中央的采集方框（边长按比例算，换分辨率也不会跑偏）
        roi_size = int(min(h, w) * ROI_FRAC)
        x0 = (w - roi_size) // 2
        y0 = (h - roi_size) // 2
        x1, y1 = x0 + roi_size, y0 + roi_size

        roi = frame[y0:y1, x0:x1]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)

        # 框内内容的"健康度"：平均亮度 + 对比度。
        # 对比度很低 = 框里几乎是纯色背景 = 手不在框里。
        # 这个提示是当场就该看见的，不要等训练完才发现。
        roi_mean = float(small.mean())
        roi_std = float(small.std())
        roi_empty = roi_std < 20.0

        # 连续采集：每隔 SAVE_INTERVAL 存一帧
        now = time.time()
        if recording and (now - last_save) >= SAVE_INTERVAL:
            if counts[current] < MAX_PER_CLASS:
                fname = "%s_%d_%03d.jpg" % (current, int(now * 1000), counts[current])
                cv2.imwrite(os.path.join(OUT_DIR, current, fname), small)
                counts[current] += 1
                last_save = now
            else:
                recording = False
                print("[提示] %s 已达上限 %d 张，自动停止采集。" % (current, MAX_PER_CLASS))

        # ---------------- 画面叠加信息 ----------------
        color = (0, 0, 255) if recording else (0, 255, 0)
        box_color = (0, 165, 255) if roi_empty else color   # 橙色 = 框里没东西
        cv2.rectangle(frame, (x0, y0), (x1, y1), box_color, 3 if roi_empty else 2)

        cv2.putText(frame, "CLASS: %s (%s)" % (current, CLASS_HINT[current]),
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        cv2.putText(frame, "RECORDING" if recording else "paused  (press SPACE)",
                    (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        y = 90
        for c in CLASSES:
            mark = ">>" if c == current else "  "
            cv2.putText(frame, "%s %-9s %4d" % (mark, c, counts[c]),
                        (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
            y += 24

        cv2.putText(frame, "1/2/3 switch   SPACE record   q quit",
                    (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # 框内健康度实时读数（右上角）
        cv2.putText(frame, "box mean=%.0f std=%.0f" % (roi_mean, roi_std),
                    (w - 230, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        if roi_empty:
            cv2.putText(frame, "! BOX LOOKS EMPTY - put your hand inside the box",
                        (10, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

        # 常驻提醒：自动取景是上一次采集失败的真凶
        cv2.putText(frame, "Studio Effects must be OFF (auto-framing follows your face)",
                    (10, h - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)

        # 右下角放一个"模型实际看到的样子"的小图，方便你确认手在框里
        preview = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
        preview = cv2.resize(preview, (96, 96), interpolation=cv2.INTER_NEAREST)
        frame[h - 106:h - 10, w - 106:w - 10] = preview

        cv2.imshow(win, frame)

        # ---------------- 键盘 ----------------
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key in (ord("1"), ord("2"), ord("3")):
            current = CLASSES[key - ord("1")]
            recording = False
            print("当前类别 -> %s（%s），已录 %d 张" % (current, CLASS_HINT[current], counts[current]))
        elif key == ord(" "):
            recording = not recording
            print("采集 %s：%s" % (current, "开始" if recording else "停止"))

    cap.release()
    cv2.destroyAllWindows()

    print("=" * 60)
    print("采集结束，最终数量：")
    total = 0
    for c in CLASSES:
        print("  %-9s %4d 张" % (c, counts[c]))
        total += counts[c]
    print("  合计      %4d 张" % total)
    sanity_report()
    print("下一步：python 02_train.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
