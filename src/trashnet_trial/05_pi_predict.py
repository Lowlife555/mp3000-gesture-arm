#!/usr/bin/env python3
"""
05 树莓派单张图片推理

⚠️ 树莓派上【不装 TensorFlow】，只用 ai-edge-litert（就是 tflite-runtime 的改名版）。
   正确的 import 是：from ai_edge_litert.interpreter import Interpreter
   （`from ai_edge_litert import Interpreter` 会 ImportError，实测过）

用法：
    python 05_pi_predict.py 图片.jpg
    python 05_pi_predict.py --dir 某个文件夹
    python 05_pi_predict.py --spec           # 只看模型规格
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np
from PIL import Image

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError as e:
    sys.exit(f"❌ 导入失败: {e}\n"
             "   正确写法是 from ai_edge_litert.interpreter import Interpreter\n"
             "   检查: python -c \"from ai_edge_litert.interpreter import Interpreter\"")

HERE = pathlib.Path(__file__).resolve().parent
MODEL = HERE / "trashnet_mobilenetv2_int8.tflite"
META = HERE / "meta.json"

if not MODEL.exists():
    sys.exit(f"❌ 找不到模型: {MODEL}\n   先从电脑 scp 过来")
if not META.exists():
    sys.exit(f"❌ 找不到 meta.json: {META}\n   类别名在里面，必须一起 scp")


def load():
    interp = Interpreter(model_path=str(MODEL))
    interp.allocate_tensors()
    meta = json.loads(META.read_text(encoding="utf-8"))
    return (interp, interp.get_input_details()[0], interp.get_output_details()[0],
            meta["class_names"], meta["img_size"])


def predict(interp, inp, oup, classes, size, path):
    """返回 [(类别, 概率), ...] 按概率降序，以及本次推理毫秒数"""
    img = Image.open(path).convert("RGB")
    # ⚠️ 必须用 BILINEAR：训练时 tf.image.resize 的默认插值就是 bilinear。
    #    PIL 的默认是 BICUBIC，不显式指定会让像素分布和训练时不一致。
    img = img.resize((size, size), Image.Resampling.BILINEAR)
    arr = np.asarray(img, dtype=np.uint8)[None, ...]

    interp.set_tensor(inp["index"], arr)
    t0 = time.perf_counter()
    interp.invoke()
    ms = (time.perf_counter() - t0) * 1000.0

    probs = interp.get_tensor(oup["index"])[0].astype(np.float32)
    scale, zero = oup["quantization"]
    if scale:
        probs = (probs - zero) * scale
    if probs.sum() > 0:
        probs = probs / probs.sum()
    order = np.argsort(probs)[::-1]
    return [(classes[i], float(probs[i])) for i in order], ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="图片路径")
    ap.add_argument("--dir", help="对整个文件夹里的图片逐张推理")
    ap.add_argument("--spec", action="store_true", help="只打印模型规格")
    ap.add_argument("--top", type=int, default=3, help="显示前几名（默认 3）")
    args = ap.parse_args()

    interp, inp, oup, classes, size = load()

    print(f"模型: {MODEL.name}  ({MODEL.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"输入: {inp['shape']} {inp['dtype'].__name__}  quant={inp['quantization']}")
    print(f"输出: {oup['shape']} {oup['dtype'].__name__}  quant={oup['quantization']}")
    print(f"类别({len(classes)}): {classes}")
    print(f"输入尺寸: {size}x{size}")
    if args.spec:
        return

    if args.dir:
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        files = sorted(p for p in pathlib.Path(args.dir).iterdir()
                       if p.suffix.lower() in exts)
        if not files:
            sys.exit(f"❌ {args.dir} 里没有图片")
        print(f"\n共 {len(files)} 张\n")
        hit = scored = 0
        for f in files:
            res, ms = predict(interp, inp, oup, classes, size, f)
            label, conf = res[0]
            # 只有当文件夹名本身就是类别名时才计对错；否则（比如 test_images）不做判定
            graded = f.parent.name in classes
            good = f.parent.name == label
            if graded:
                scored += 1
                hit += int(good)
            mark = ("✅" if good else "❌") if graded else "·"
            print(f"{mark} {f.name:<24} → {label:<10} "
                  f"{conf:6.2%}  {ms:6.1f} ms")
        if scored:
            print(f"\n目录名与预测一致: {hit}/{scored}")
        else:
            print(f"\n（文件夹名不是类别名，未计对错；只看“→”后面的预测）")
    elif args.path:
        res, ms = predict(interp, inp, oup, classes, size, args.path)
        print(f"\n图片: {args.path}")
        for i, (label, conf) in enumerate(res[:args.top], 1):
            bar = "█" * int(conf * 40)
            print(f"  {i}. {label:<11} {conf:7.2%}  {bar}")
        print(f"\n推理耗时: {ms:.1f} ms")
    else:
        ap.error("要给一张图片路径，或用 --dir 指定文件夹，或 --spec 看规格")


if __name__ == "__main__":
    main()
