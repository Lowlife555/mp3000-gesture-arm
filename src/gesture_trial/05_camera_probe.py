# -*- coding: utf-8 -*-
"""
MP3000 / YZ3 试跑 · 摄像头探测
==============================
OpenCV 5 是新的大版本，不同 Windows 后端（DSHOW / MSMF）对摄像头的兼容性不一样。
这个脚本把几个组合都试一遍，告诉你**哪一个能出画面**。

用法：
    python 05_camera_probe.py

如果全是 False，按顺序检查：
  1. Zoom / Teams / 浏览器 是否正占着摄像头（关掉再试）；
  2. Windows 设置 → 隐私和安全性 → 相机 → 允许桌面应用访问相机；
  3. 笔记本键盘上可能有摄像头物理遮挡/快捷键（F8 之类的相机键）。
"""

import cv2

BACKENDS = [
    ("CAP_ANY", getattr(cv2, "CAP_ANY", 0)),
    ("CAP_DSHOW", getattr(cv2, "CAP_DSHOW", 700)),
    ("CAP_MSMF", getattr(cv2, "CAP_MSMF", 1400)),
]

for idx in (0, 1):
    for name, be in BACKENDS:
        cap = cv2.VideoCapture(idx, be)
        opened = cap.isOpened()
        ok, frame = (False, None)
        if opened:
            ok, frame = cap.read()
            if frame is not None:
                # 顺便试试设置分辨率
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                ok2, f2 = cap.read()
                if f2 is not None:
                    frame = f2
        shape = None if frame is None else frame.shape
        print("camera=%d backend=%-9s opened=%-5s read=%-5s shape=%s"
              % (idx, name, opened, ok, shape))
        cap.release()

print("\n挑一个 opened=True 且 read=True 的组合。")
print("默认脚本用的是 camera=0 + OpenCV 的默认后端（CAP_ANY）。")
print("如果只有 CAP_DSHOW 能出画面，就改用：")
print('    python 03_live_demo.py --camera 0     # 先把脚本里的后端改成 CAP_DSHOW')
