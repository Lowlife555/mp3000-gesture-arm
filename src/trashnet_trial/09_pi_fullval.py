#!/usr/bin/env python3
"""09_pi_fullval.py —— 在树莓派上跑完整验证集（379 张），出真实准确率。

用途：演示页上的累计百分比是「36 张固定样本循环」的数字，不是模型准确率。
本脚本跑完整 379 张验证集，给出可对外引用、可与训练日志对照的数字。

Preprocessing is copied verbatim from 08_pi_demo.py::Predictor so the numbers
are directly comparable with what the demo page shows.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "trashnet_mobilenetv2_int8.tflite"
META = ROOT / "meta.json"
VAL = ROOT / "val"


class Predictor:
    """Same preprocessing as 08_pi_demo.py — do not diverge."""

    def __init__(self, model_path: Path, meta_path: Path | None):
        from ai_edge_litert.interpreter import Interpreter

        self.interp = Interpreter(model_path=str(model_path), num_threads=2)
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.out = self.interp.get_output_details()[0]

        meta = {}
        if meta_path and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.class_names = meta.get("class_names") or [
            "cardboard", "glass", "metal", "paper", "plastic", "trash",
        ]
        self.img_size = int(meta.get("img_size", 224))
        self.in_dtype = self.inp["dtype"]
        self.in_quant = self.inp.get("quantization", (0.0, 0))
        self.out_quant = self.out.get("quantization", (0.0, 0))

    def predict_rgb(self, rgb: Image.Image) -> dict:
        t0 = time.perf_counter()
        im = rgb.convert("RGB").resize(
            (self.img_size, self.img_size), Image.Resampling.BILINEAR
        )
        arr = np.asarray(im, dtype=np.uint8)[None, ...]
        if self.in_dtype == np.int8:
            scale, zero = self.in_quant
            arr = (arr.astype(np.int16) + int(zero)).clip(-128, 127).astype(np.int8)
        elif self.in_dtype == np.float32:
            arr = arr.astype(np.float32) / 255.0

        self.interp.set_tensor(self.inp["index"], arr)
        self.interp.invoke()
        logits = self.interp.get_tensor(self.out["index"])[0]

        scale, zero = self.out_quant
        probs = logits.astype(np.float32)
        if scale:
            probs = (probs.astype(np.int32) - int(zero)).astype(np.float32) * scale
        if not np.all((probs >= 0) & (probs <= 1.0001)):
            e = np.exp(probs - probs.max())
            probs = e / e.sum()

        ms = (time.perf_counter() - t0) * 1000.0
        order = np.argsort(probs)[::-1]
        return {
            "top": self.class_names[int(order[0])],
            "conf": float(probs[order[0]]),
            "ms": ms,
            "top3": [
                (self.class_names[int(i)], float(probs[i])) for i in order[:3]
            ],
        }


def main() -> int:
    if not MODEL.exists():
        print(f"ERROR: model not found: {MODEL}", file=sys.stderr)
        return 1
    if not VAL.exists():
        print(f"ERROR: val folder not found: {VAL}", file=sys.stderr)
        return 1

    classes = sorted(d.name for d in VAL.iterdir() if d.is_dir())
    files = sorted(
        p for c in classes for p in (VAL / c).glob("*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    print(f"model : {MODEL.name} ({MODEL.stat().st_size:,} bytes)")
    print(f"val   : {len(files)} images in {len(classes)} classes {classes}")
    print()

    pred = Predictor(MODEL, META)

    per_class_total: Counter = Counter()
    per_class_correct: Counter = Counter()
    confusion: dict[str, Counter] = defaultdict(Counter)
    times: list[float] = []
    wrong: list[dict] = []

    t_start = time.perf_counter()
    for i, p in enumerate(files, 1):
        truth = p.parent.name
        im = Image.open(p)
        im.load()
        r = pred.predict_rgb(im)
        times.append(r["ms"])
        per_class_total[truth] += 1
        confusion[truth][r["top"]] += 1
        if r["top"] == truth:
            per_class_correct[truth] += 1
        else:
            wrong.append(
                {"file": f"{truth}/{p.name}", "truth": truth,
                 "pred": r["top"], "conf": round(r["conf"], 4)}
            )
        if i % 50 == 0 or i == len(files):
            acc = sum(per_class_correct.values()) / i
            print(f"  {i:4d}/{len(files)}  running acc = {acc:.4f}")
    wall = time.perf_counter() - t_start

    total = len(files)
    correct = sum(per_class_correct.values())
    overall = correct / total
    tms = np.asarray(times, dtype=np.float64)

    print()
    print("=" * 58)
    print(f"OVERALL  {correct}/{total} = {overall:.4f}  ({overall*100:.2f}%)")
    print(f"latency  mean {tms.mean():.1f} ms   median {np.median(tms):.1f} ms"
          f"   p95 {np.percentile(tms, 95):.1f} ms   min {tms.min():.1f}"
          f"   max {tms.max():.1f}")
    print(f"wall     {wall:.1f} s for {total} images ({wall/total*1000:.1f} ms/img)")
    print()
    print("per-class accuracy")
    for c in classes:
        n, k = per_class_total[c], per_class_correct[c]
        print(f"  {c:<10} {k:3d}/{n:3d} = {k/n:6.2%}" if n else f"  {c:<10} n/a")
    print()
    print("confusion (rows = truth, cols = predicted)")
    short = {c: c[:4] for c in classes}
    print("            " + " ".join(f"{short[c]:>5}" for c in classes))
    for t in classes:
        row = " ".join(f"{confusion[t].get(c, 0):>5d}" for c in classes)
        print(f"  {t:<10} {row}")
    print()
    print(f"wrong: {len(wrong)} of {total}")
    for w in wrong[:20]:
        print(f"  {w['file']:<34} truth={w['truth']:<10} pred={w['pred']:<10} {w['conf']:.2f}")
    if len(wrong) > 20:
        print(f"  ... and {len(wrong)-20} more")

    out = {
        "model": MODEL.name,
        "model_bytes": MODEL.stat().st_size,
        "n": total,
        "correct": correct,
        "accuracy": round(overall, 6),
        "latency_ms": {
            "mean": round(float(tms.mean()), 2),
            "median": round(float(np.median(tms)), 2),
            "p95": round(float(np.percentile(tms, 95)), 2),
            "min": round(float(tms.min()), 2),
            "max": round(float(tms.max()), 2),
        },
        "per_class": {
            c: {"n": per_class_total[c], "correct": per_class_correct[c],
                "accuracy": round(per_class_correct[c] / per_class_total[c], 6)
                if per_class_total[c] else None}
            for c in classes
        },
        "confusion": {t: dict(confusion[t]) for t in classes},
        "wrong": wrong,
        "measured_on": "Raspberry Pi 4 Model B 8GB, ai-edge-litert, num_threads=2",
    }
    (ROOT / "fullval.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print()
    print(f"wrote {ROOT / 'fullval.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
