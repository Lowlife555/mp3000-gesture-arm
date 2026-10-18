#!/usr/bin/env python3
"""
06 树莓派摄像头实时识别（picamera2）

用法：
    python 06_pi_live.py                  # 一直跑，Ctrl+C 停
    python 06_pi_live.py --save            # 同时把每帧存成 jpg（演示留证据）
    python 06_pi_live.py --log demo.csv    # 把每次预测写进 CSV
    python 06_pi_live.py --interval 0.3    # 每 0.3 秒一帧（默认 0.2）

⚠️ 无显示器（纯 SSH）也能跑：capture_array 不需要预览窗口。
⚠️ 光照：没有漫射的裸 LED 会在物体上打出高光，塑料/玻璃会误判。见文档「光照」一节。
"""
import argparse
import csv
import pathlib
import sys
import time

import numpy as np
from PIL import Image

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError as e:
    sys.exit(f"❌ {e}\n   应为 from ai_edge_litert.interpreter import Interpreter")
try:
    from picamera2 import Picamera2
except ImportError as e:
    sys.exit(f"❌ picamera2 导入失败: {e}\n"
             "   必须在 --system-site-packages 的 venv 里跑（见文档阶段 2）")

HERE = pathlib.Path(__file__).resolve().parent
MODEL = HERE / "trashnet_mobilenetv2_int8.tflite"
META = HERE / "meta.json"
for p in (MODEL, META):
    if not p.exists():
        sys.exit(f"❌ 缺少 {p.name}，先从电脑 scp 过来")

import json  # noqa: E402

meta = json.loads(META.read_text(encoding="utf-8"))
CLASSES = meta["class_names"]
IMG = meta["img_size"]

interp = Interpreter(model_path=str(MODEL))
interp.allocate_tensors()
inp_d = interp.get_input_details()[0]
oup_d = interp.get_output_details()[0]


def infer(rgb_frame):
    img = Image.fromarray(rgb_frame).resize((IMG, IMG), Image.Resampling.BILINEAR)
    arr = np.asarray(img, dtype=np.uint8)[None, ...]
    interp.set_tensor(inp_d["index"], arr)
    t0 = time.perf_counter()
    interp.invoke()
    ms = (time.perf_counter() - t0) * 1000.0
    probs = interp.get_tensor(oup_d["index"])[0].astype(np.float32)
    s, z = oup_d["quantization"]
    if s:
        probs = (probs - z) * s
    if probs.sum() > 0:
        probs = probs / probs.sum()
    return probs, ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=0.2, help="采样间隔秒（默认 0.2）")
    ap.add_argument("--save", action="store_true", help="保存每帧 jpg")
    ap.add_argument("--save-dir", default="demo_frames", help="存图目录")
    ap.add_argument("--log", help="预测结果写进这个 CSV")
    ap.add_argument("--warmup", type=int, default=10, help="丢弃前几帧（自动曝光稳定）")
    args = ap.parse_args()

    save_dir = pathlib.Path(args.save_dir)
    if args.save:
        save_dir.mkdir(parents=True, exist_ok=True)

    logf = logw = None
    if args.log:
        logf = open(args.log, "a", newline="", encoding="utf-8")
        logw = csv.writer(logf)
        if logf.tell() == 0:
            logw.writerow(["iso_time", "top1", "conf", "top2", "conf2", "infer_ms"])

    picam2 = Picamera2()
    cfg = picam2.create_preview_configuration(
        main={"size": (640, 480), "format": "RGB888"})
    picam2.configure(cfg)
    picam2.start()
    print(f"摄像头已启动 640x480 RGB888 | 模型 {IMG}x{IMG} | {len(CLASSES)} 类")
    print("第 1-2 秒先让它自动曝光稳定…")
    time.sleep(2)

    for _ in range(args.warmup):
        infer(picam2.capture_array())
    print("就绪。Ctrl+C 停止。\n")

    n = 0
    t_start = time.time()
    try:
        while True:
            frame = picam2.capture_array()
            if frame.ndim == 3 and frame.shape[2] == 4:
                frame = frame[:, :, :3]
            probs, ms = infer(frame)
            order = np.argsort(probs)[::-1]
            top1, conf1 = CLASSES[order[0]], float(probs[order[0]])
            top2, conf2 = CLASSES[order[1]], float(probs[order[1]])
            n += 1
            fps = n / (time.time() - t_start)
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] {top1:<11} {conf1:6.2%}   "
                  f"(次: {top2} {conf2:5.1%})   {ms:5.1f} ms   {fps:4.1f} fps")

            if args.save:
                Image.fromarray(frame).save(
                    save_dir / f"{time.strftime('%H%M%S')}_{top1}_{conf1:.2f}.jpg",
                    quality=85)
            if logw:
                logw.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), top1,
                               f"{conf1:.4f}", top2, f"{conf2:.4f}", f"{ms:.1f}"])
                logf.flush()

            time.sleep(max(0.0, args.interval - ms / 1000.0))
    except KeyboardInterrupt:
        print(f"\n停止。共 {n} 帧，平均 {n / (time.time() - t_start):.1f} fps")
    finally:
        picam2.stop()
        if logf:
            logf.close()
            print(f"日志已写: {args.log}")


if __name__ == "__main__":
    main()
