# -*- coding: utf-8 -*-
"""
MP3000 / YZ3 试跑 · 实时手势识别（这就是明天要给 Yu Zhou 看的东西）
==================================================================
打开摄像头 → 取中间方框 → 缩成 64x64 灰度 → 送进训练好的 CNN → 实时显示三个类别的概率。

和训练时保持完全一致的三件事（不一致就会识别不准）：
  1. 同样水平镜像；
  2. 同样只取中间方形方框（ROI）；
  3. 同样缩成 64x64 灰度、除以 255。

一个工程上的小技巧（值得讲）：
  单帧预测会抖动，所以这里对最近 N 帧的概率做滑动平均（"投票"）。
  这叫**时序平滑** —— 实时系统里常用的手段，代价是响应慢一点点。

操作：
  q   退出
  s   把当前画面存成截图（放到 reports/ 下，可以贴进报告）
  空格 重置平滑窗口
"""

import os
import time
import argparse
from collections import deque

import numpy as np
import cv2
import keras

CLASSES = ["fist", "palm", "scissors"]
CLASS_HINT = {"fist": "握拳", "palm": "手掌", "scissors": "剪刀手"}
IMG_SIZE = 64
WORK_WIDTH = 960       # 与 01_capture.py 必须一致，否则训练/推理输入分布不同
ROI_FRAC = 0.55        # 与 01_capture.py 必须一致
SMOOTH_N = 10          # 滑动平均窗口长度（帧）

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "models", "gesture_cnn.keras")
SHOT_DIR = os.path.join(HERE, "reports")


def draw_bar(img, x, y, w, h, frac, color, label, prob):
    cv2.rectangle(img, (x, y), (x + w, y + h), (90, 90, 90), 1)
    cv2.rectangle(img, (x, y), (x + int(w * max(0.0, min(1.0, frac))), y + h), color, -1)
    cv2.putText(img, "%-9s %5.1f%%" % (label, prob * 100), (x - 118, y + h - 3),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    os.makedirs(SHOT_DIR, exist_ok=True)

    if not os.path.exists(MODEL_PATH):
        print("[错误] 找不到模型：%s" % MODEL_PATH)
        print("       先跑 python 02_train.py 训练出模型。")
        return 1

    print("加载模型 %s ..." % MODEL_PATH)
    model = keras.models.load_model(MODEL_PATH)
    print("模型加载完成。参数量 = %d" % model.count_params())

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print("[错误] 打不开摄像头 (index=%d)。检查是不是被 Zoom/Teams/浏览器 占用了。" % args.camera)
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    win = "MP3000 / YZ3 - live gesture recognition"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)

    history = deque(maxlen=SMOOTH_N)
    last_time = time.time()
    fps = 0.0
    ms_per_infer = 0.0

    print("按 q 退出；按 s 存截图。")
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame = cv2.flip(frame, 1)

        # 与 01_capture.py 完全相同的处理链，一步都不能差
        h, w = frame.shape[:2]
        if w > WORK_WIDTH:
            frame = cv2.resize(frame, (WORK_WIDTH, int(round(h * WORK_WIDTH / w))),
                               interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]

        roi_size = int(min(h, w) * ROI_FRAC)
        x0 = (w - roi_size) // 2
        y0 = (h - roi_size) // 2
        x1, y1 = x0 + roi_size, y0 + roi_size

        roi = frame[y0:y1, x0:x1]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)

        # 推理（记录耗时 —— 这个数字报告里要用）
        t0 = time.perf_counter()
        inp = (small.astype(np.float32) / 255.0)[None, :, :, None]
        probs = model.predict(inp, verbose=0)[0]
        ms_per_infer = (time.perf_counter() - t0) * 1000.0

        history.append(probs)
        smooth = np.mean(np.stack(history, axis=0), axis=0)
        top = int(np.argmax(smooth))

        now = time.time()
        dt = now - last_time
        last_time = now
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1.0 / dt)

        # ---------------- 叠加界面 ----------------
        box_color = (0, 220, 0)
        cv2.rectangle(frame, (x0, y0), (x1, y1), box_color, 2)

        cv2.putText(frame, "PREDICTION: %s (%s)" % (CLASSES[top], CLASS_HINT[CLASSES[top]]),
                    (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, box_color, 2)

        bar_x, bar_y, bar_w, bar_h = 138, 58, 300, 20
        colors = [(60, 60, 240), (60, 200, 60), (240, 160, 60)]
        for i, c in enumerate(CLASSES):
            draw_bar(frame, bar_x, bar_y + i * 30, bar_w, bar_h,
                     smooth[i], colors[i % 3], c, smooth[i])

        cv2.putText(frame, "inference %.1f ms   camera %.0f fps   smoothing %d frames"
                    % (ms_per_infer, fps, len(history)),
                    (12, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (210, 210, 210), 1)

        preview = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
        preview = cv2.resize(preview, (96, 96), interpolation=cv2.INTER_NEAREST)
        frame[h - 106:h - 10, w - 106:w - 10] = preview

        cv2.imshow(win, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("s"):
            shot = os.path.join(SHOT_DIR, "live_%d.png" % int(time.time()))
            cv2.imwrite(shot, frame)
            print("截图已保存：%s" % shot)
        elif key == ord(" "):
            history.clear()
            print("平滑窗口已重置")

    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
