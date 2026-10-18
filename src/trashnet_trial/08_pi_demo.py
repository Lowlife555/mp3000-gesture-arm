#!/usr/bin/env python3
"""
08_pi_demo.py — 树莓派垃圾分类演示页面

两种演示模式：
  images  : 循环播放 demo_images/ 里的真实垃圾照片，逐张推理（默认）
  camera  : 有 CSI 摄像头时实时识别（摄像头没到就报错，不会崩）
  pause   : 冻结在当前画面，方便讲解某一张

访问：http://<树莓派IP>:8090/
接口：
  /            演示页面
  /stream      MJPEG 流（图片模式和摄像头模式都走这里，前端无差别）
  /api         JSON：当前结果 + 累计准确率
  /api/mode?m=images|camera|pause
  /api/next    手动下一张
  /health      健康检查

只用标准库 + PIL + numpy + ai_edge_litert，不依赖 Flask。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent

CLASS_ZH = {
    "cardboard": "纸板",
    "glass": "玻璃",
    "metal": "金属",
    "paper": "纸",
    "plastic": "塑料",
    "trash": "其他垃圾",
}

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# 画布尺寸（投影/截图都够看）
CANVAS_W = 900
BAND_H = 120
MAX_IMG_H = 600


# --------------------------------------------------------------------------
# 模型
# --------------------------------------------------------------------------
def find_file(names, extra_dirs=()):
    dirs = [HERE, HERE / "models", Path.home() / "trashnet_demo"]
    dirs.extend(Path(d) for d in extra_dirs)
    for name in names:
        for d in dirs:
            p = Path(d) / name
            if p.exists():
                return p
    return None


class Predictor:
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
        im = rgb.convert("RGB").resize((self.img_size, self.img_size), Image.Resampling.BILINEAR)
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
            "top": self.class_names[int(np.argmax(probs))],
            "conf": float(probs[int(np.argmax(probs))]),
            "top3": [
                [self.class_names[int(i)], float(probs[int(i)])] for i in order[:3]
            ],
            "ms": round(ms, 2),
        }


# --------------------------------------------------------------------------
# 全量验证集参考结果
# --------------------------------------------------------------------------
def load_fullval() -> dict:
    """读取 09_pi_fullval.py 产出的全量验证集结果（379 张）。

    演示页上的「本次运行」是 36 张固定样本循环出来的数字，**不是模型准确率**；
    这个才是可以对外引用的那个数。两者必须并列显示，否则容易被误读。
    """
    p = Path(__file__).resolve().parent / "fullval.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {
            "n": d["n"],
            "correct": d["correct"],
            "accuracy": d["accuracy"],
            "median_ms": d.get("latency_ms", {}).get("median"),
            "model": d.get("model", ""),
            "measured_on": d.get("measured_on", ""),
            "per_class": d.get("per_class", {}),
        }
    except Exception as e:  # 文件缺失/损坏都不该让演示挂掉
        print(f"WARN: fullval.json 不可用（{e}）；页面将不显示全量数字", flush=True)
        return {}


# 全局状态
# --------------------------------------------------------------------------
class State:
    def __init__(self, image_files: list[dict], interval: float):
        self.lock = threading.Lock()
        self.image_files = image_files
        self.interval = interval
        self.mode = "images"          # images | camera | pause
        self.index = 0
        self.current = None            # 当前结果 dict
        self.stats = {"n": 0, "correct": 0}
        self.fullval = load_fullval()  # 379 张全量的固定结果（≠ 本次运行）
        self.frame = b""
        self.frame_seq = 0
        # 帧历史：seq -> {"jpeg": bytes, "meta": dict}
        # 目的：前端按 seq 精确取回"它正在显示的那一帧"的图片和判定，
        # 保证侧栏数字与画面永远同一帧（否则 /api 轮询会领先画面一帧）
        self.history = {}
        self.history_order = []
        self.history_max = 12
        self.camera_ok = False
        self.camera_err = "尚未检测"
        self.started = time.time()
        self.last_change = time.time()

    def push_frame_locked(self, seq: int, jpeg: bytes, meta: dict):
        """调用方必须已持有 self.lock。存下这一帧的图片与判定，供 /frame?seq= 精确取回。"""
        m = dict(meta)
        m["frame_seq"] = seq
        self.history[seq] = {"jpeg": jpeg, "meta": m}
        self.history_order.append(seq)
        while len(self.history_order) > self.history_max:
            self.history.pop(self.history_order.pop(0), None)

    def get_frame(self, seq):
        """取指定 seq 的 JPEG；seq 为 None 或已淘汰时退回当前帧。"""
        with self.lock:
            h = self.history.get(seq) if seq is not None else None
            if h is not None:
                return h["jpeg"], h["meta"]
            return self.frame, None

    def snapshot(self, seq: int | None = None) -> dict:
        with self.lock:
            h = self.history.get(seq) if seq is not None else None
            if h is not None:
                # 回放指定帧：所有数字与那一帧严格对应
                d = dict(h["meta"])
                d["camera_ok"] = self.camera_ok
                d["camera_err"] = self.camera_err
                d["interval"] = self.interval
                d["uptime_s"] = round(time.time() - self.started, 1)
                d["live_seq"] = self.frame_seq
                d["fullval"] = self.fullval
                return d
            d = {
                "mode": self.mode,
                "index": self.index,
                "total": len(self.image_files),
                "stats": dict(self.stats),
                "frame_seq": self.frame_seq,
                "camera_ok": self.camera_ok,
                "camera_err": self.camera_err,
                "interval": self.interval,
                "uptime_s": round(time.time() - self.started, 1),
                "live_seq": self.frame_seq,
                "fullval": self.fullval,
            }
            if self.current:
                d.update(self.current)
            return d

    def set_mode(self, mode: str) -> bool:
        if mode not in ("images", "camera", "pause"):
            return False
        with self.lock:
            if mode == "camera" and not self.camera_ok:
                return False
            self.mode = mode
            self.last_change = time.time()
        return True

    def next_image(self):
        with self.lock:
            self.index = (self.index + 1) % max(1, len(self.image_files))
            self.last_change = time.time()


STATE: State | None = None
PRED: Predictor | None = None


# --------------------------------------------------------------------------
# 画面合成
# --------------------------------------------------------------------------
_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, size)
                _FONT_CACHE[size] = f
                return f
            except Exception:
                pass
    f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def compose(img: Image.Image, res: dict | None, truth: str | None, label: str) -> bytes:
    """把图片 + 结果画成一张给观众看的画面。"""
    img = img.convert("RGB")

    # 等比缩放到画布宽度
    scale = CANVAS_W / img.width
    if img.height * scale > MAX_IMG_H:
        scale = MAX_IMG_H / img.height
    w, h = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    thumb = img.resize((w, h), Image.Resampling.BILINEAR)

    canvas = Image.new("RGB", (CANVAS_W, h + BAND_H), (16, 17, 20))
    canvas.paste(thumb, ((CANVAS_W - w) // 2, 0))
    d = ImageDraw.Draw(canvas)

    y0 = h
    if res is None:
        d.rectangle([0, y0, CANVAS_W, y0 + BAND_H], fill=(35, 20, 20))
        d.text((18, y0 + 40), f"NO RESULT  ({label})", font=font(30), fill=(240, 120, 120))
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=80)
        return buf.getvalue()

    ok = truth is None or truth == res["top"]
    band_color = (20, 38, 24) if ok else (44, 20, 20)
    d.rectangle([0, y0, CANVAS_W, y0 + BAND_H], fill=band_color)

    pred = res["top"]
    conf = res["conf"]
    d.text(
        (18, y0 + 12),
        f"PREDICT: {pred.upper()}  {conf:.1%}",
        font=font(34),
        fill=(120, 230, 150) if ok else (255, 130, 130),
    )
    line2 = f"truth: {truth or '?'}   |   {res['ms']:.1f} ms on Raspberry Pi 4B"
    d.text((18, y0 + 60), line2, font=font(21), fill=(200, 205, 215))

    # 右上角：本次运行累计 —— 注意这是 36 张固定样本循环出来的，不是模型准确率。
    # ⚠️ 烙印一律用 ASCII：PIL 加载的字体没有中文字形，中文会渲染成方块。
    if STATE:
        s = STATE.stats
        acc = (s["correct"] / s["n"]) if s["n"] else 0.0
        fv = STATE.fullval.get("accuracy") if STATE.fullval else None
        d.text(
            (CANVAS_W - 250, y0 + 12),
            f"{s['correct']}/{s['n']}  {acc:.1%}",
            font=font(22),
            fill=(190, 190, 200),
        )
        d.text(
            (CANVAS_W - 250, y0 + 40),
            f"all379 {fv:.1%}" if fv is not None else "all379 n/a",
            font=font(18),
            fill=(150, 155, 165),
        )
    # 右下角：序号
    if STATE and STATE.image_files:
        d.text(
            (CANVAS_W - 250, y0 + 62),
            f"#{STATE.index + 1}/{len(STATE.image_files)}   [{label}]",
            font=font(19),
            fill=(150, 155, 165),
        )

    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=80)
    return buf.getvalue()


# --------------------------------------------------------------------------
# 工作线程
# --------------------------------------------------------------------------
def camera_open():
    """尝试打开 CSI 摄像头，返回 (picamera2 对象 or None, 错误信息)"""
    try:
        from picamera2 import Picamera2

        cam = Picamera2()
        cfg = cam.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        cam.configure(cfg)
        cam.start()
        time.sleep(0.6)
        return cam, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def worker():
    assert STATE and PRED
    cam, cam_err = camera_open()
    with STATE.lock:
        STATE.camera_ok = cam is not None
        STATE.camera_err = cam_err or "OK"

    last_key = None
    while True:
        mode = STATE.mode

        if mode == "camera" and not STATE.camera_ok:
            # 摄像头不可用 → 退回图片模式，不崩
            STATE.set_mode("images")
            time.sleep(0.5)
            continue

        if mode == "camera" and cam is not None:
            try:
                arr = cam.capture_array()
                rgb = Image.fromarray(arr[:, :, :3], "RGB")
                res = PRED.predict_rgb(rgb)
                with STATE.lock:
                    STATE.current = {
                        "file": "(live camera)",
                        "truth": None,
                        "top": res["top"],
                        "conf": res["conf"],
                        "top3": res["top3"],
                        "ms": res["ms"],
                    }
                    STATE.stats["n"] += 1
                    STATE.frame = compose(rgb, res, None, "CAMERA")
                    STATE.frame_seq += 1
                    STATE.push_frame_locked(STATE.frame_seq, STATE.frame, {
                        "mode": "camera",
                        "index": STATE.index,
                        "total": len(STATE.image_files),
                        "stats": dict(STATE.stats),
                        "file": "(live camera)",
                        "truth": None,
                        "top": res["top"],
                        "conf": res["conf"],
                        "top3": res["top3"],
                        "ms": res["ms"],
                    })
            except Exception as exc:  # noqa: BLE001
                with STATE.lock:
                    STATE.camera_err = f"抓帧失败: {exc}"
                    STATE.camera_ok = False
                STATE.set_mode("images")
            time.sleep(max(0.0, STATE.interval))
            continue

        # ---- 图片模式 ----
        if not STATE.image_files:
            time.sleep(0.5)
            continue

        with STATE.lock:
            idx = STATE.index % len(STATE.image_files)
        item = STATE.image_files[idx]

        if mode == "pause" and last_key == item["path"]:
            time.sleep(0.25)
            continue

        label = item["true"]
        try:
            img = Image.open(item["path"])
            img.load()
            res = PRED.predict_rgb(img)
            with STATE.lock:
                STATE.current = {
                    "file": item["rel"],
                    "truth": label,
                    "top": res["top"],
                    "conf": res["conf"],
                    "top3": res["top3"],
                    "ms": res["ms"],
                }
                STATE.stats["n"] += 1
                if res["top"] == label:
                    STATE.stats["correct"] += 1
                STATE.frame = compose(img, res, label, "IMAGES")
                STATE.frame_seq += 1
                STATE.push_frame_locked(STATE.frame_seq, STATE.frame, {
                    "mode": "images",
                    "index": STATE.index,
                    "total": len(STATE.image_files),
                    "stats": dict(STATE.stats),
                    "file": item["rel"],
                    "truth": label,
                    "top": res["top"],
                    "conf": res["conf"],
                    "top3": res["top3"],
                    "ms": res["ms"],
                })
            last_key = item["path"]
        except Exception as exc:  # noqa: BLE001
            with STATE.lock:
                STATE.frame = compose(
                    Image.new("RGB", (480, 320), (30, 20, 20)),
                    None,
                    None,
                    f"读取失败 {item['rel']}: {exc}",
                )
                STATE.frame_seq += 1
                STATE.push_frame_locked(STATE.frame_seq, STATE.frame, {
                    "mode": "images",
                    "index": STATE.index,
                    "total": len(STATE.image_files),
                    "stats": dict(STATE.stats),
                    "file": item["rel"],
                    "truth": item["true"],
                    "top": None,
                    "conf": None,
                    "top3": [],
                    "ms": None,
                })

        if mode == "images":
            time.sleep(max(0.0, STATE.interval))
            with STATE.lock:
                if STATE.mode == "images":
                    STATE.index = (STATE.index + 1) % len(STATE.image_files)
        else:
            time.sleep(0.25)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>MP3000 · 垃圾分类演示</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body { margin:0; background:#0e0f12; color:#e8eaf0;
         font-family: "Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
         display:flex; flex-direction:column;
         height:100vh; height:100dvh;   /* 跟随视口高度，窗口缩放实时生效 */
         overflow:hidden; }              /* 页面本身不滚，滚动交给右侧栏 */
  header { flex:0 0 auto; padding:8px 16px; background:#16181d;
           border-bottom:1px solid #262a33;
           display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  h1 { font-size:clamp(14px,1.35vw,19px); margin:0; font-weight:600; letter-spacing:.3px; }
  .badge { font-size:11px; padding:2px 8px; border-radius:99px; background:#2a3a2e; color:#8fe0a8; }
  /* 摄像头状态可能是一长串报错，截断显示，别把页头挤乱 */
  #camNote { max-width:42ch; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  /* 主区：左图右栏，各自占满剩余高度；minmax(0,1fr) 防止图片把栏撑宽 */
  main { flex:1 1 auto; min-height:0;
         display:grid; grid-template-columns:minmax(0,1fr) clamp(230px,23vw,340px);
         gap:14px; padding:12px 16px; overflow:hidden; }
  .view { min-width:0; min-height:0; display:flex; }
  /* 关键：图片盒占满整个格子，用 object-fit 保持比例，
     既会比原图放大（大屏不留空白）也会缩小（小窗口不溢出），永不裁切 */
  .view img { width:100%; height:100%; object-fit:contain; object-position:center;
              border-radius:10px; display:block; background:transparent; }
  aside { min-width:0; min-height:0; overflow-y:auto; overscroll-behavior:contain;
          padding-right:2px; }
  .card { background:#16181d; border:1px solid #262a33; border-radius:10px;
          padding:clamp(8px,0.9vw,14px) clamp(10px,1vw,16px);
          margin-bottom:clamp(8px,0.9vw,14px); }
  .card h2 { font-size:11px; margin:0 0 8px; color:#98a0b0; font-weight:600;
             text-transform:uppercase; letter-spacing:1px; }
  .big { font-size:clamp(19px,2.1vw,30px); font-weight:700; line-height:1.2; }
  .muted { color:#8b93a3; font-size:clamp(11px,0.95vw,13px); }
  .bar { height:8px; background:#23262e; border-radius:99px; overflow:hidden; margin:5px 0 9px; }
  .bar > i { display:block; height:100%; background:linear-gradient(90deg,#4b8cf7,#7ee0a8); }
  .row { display:flex; justify-content:space-between; gap:8px;
         font-size:clamp(11px,0.95vw,13px); margin-bottom:2px; }
  button { background:#232733; color:#dfe3ec; border:1px solid #333a49; border-radius:8px;
           padding:7px 12px; font-size:clamp(12px,1vw,14px); cursor:pointer; margin:0 6px 6px 0; }
  button:hover { background:#2d3341; }
  button.on { background:#2f6f4f; border-color:#3f8f67; color:#d8ffe6; }
  .k { color:#98a0b0; }
  .v { font-variant-numeric: tabular-nums; }

  /* 窄窗口（<820px）：改为上下堆叠，允许页面滚动，图片限高 */
  @media (max-width: 820px) {
    body { height:auto; min-height:100vh; min-height:100dvh; overflow:auto; }
    main { grid-template-columns:1fr; overflow:visible; }
    .view img { max-height:58vh; max-height:58dvh; }
    aside { overflow:visible; }
  }
  /* 矮屏（<620px 高）：进一步压缩页头和间距，把高度让给画面 */
  @media (max-height: 620px) {
    header { padding:4px 12px; gap:8px; }
    h1 { font-size:13px; }
    main { padding:8px 12px; gap:10px; }
    .card { padding:7px 10px; margin-bottom:7px; }
    .card h2 { margin-bottom:5px; }
    .big { font-size:19px; }
  }
  /* 极宽矮（演示常用：1920x1080 全屏）：右侧栏压窄，画面尽量大 */
  @media (min-width: 1400px) {
    main { grid-template-columns:minmax(0,1fr) 300px; }
  }
</style>
</head>
<body>
<header>
  <h1>MP3000 · 树莓派垃圾分类演示</h1>
  <span class="badge" id="modeBadge">图片循环</span>
  <span class="muted" id="camNote">摄像头：检测中…</span>
</header>
<main>
  <div class="view">
    <img id="stream" src="/stream" alt="stream">
  </div>
  <aside>
    <div class="card">
      <h2>当前判定</h2>
      <div class="big" id="pred">—</div>
      <div class="muted" id="conf">—</div>
      <div class="muted" style="margin-top:6px">真实类别：<b id="truth">—</b></div>
    </div>
    <div class="card">
      <h2>Top-3 概率</h2>
      <div id="bars"></div>
    </div>
    <div class="card">
      <h2>本次运行（36 张循环）</h2>
      <div class="row"><span class="k">已识别</span><span class="v" id="n">0</span></div>
      <div class="row"><span class="k">判对</span><span class="v" id="correct">0</span></div>
      <div class="row"><span class="k">准确率</span><span class="v" id="acc">—</span></div>
      <div class="row"><span class="k">单张耗时</span><span class="v" id="ms">—</span></div>
      <div class="row"><span class="k">进度</span><span class="v" id="prog">—</span></div>
      <div style="font-size:12px;color:#8a8f9a;margin-top:8px;line-height:1.45">
        这 36 张是验证集的固定子集，循环播放。
        <b>此处百分比不是模型准确率</b>。</div>
    </div>
    <div class="card">
      <h2>模型真实准确率（379 张全量）</h2>
      <div class="row"><span class="k">判对</span><span class="v" id="fv-correct">—</span></div>
      <div class="row"><span class="k">准确率</span><span class="v" id="fv-acc">—</span></div>
      <div class="row"><span class="k">延迟中位数</span><span class="v" id="fv-ms">—</span></div>
      <div style="font-size:12px;color:#8a8f9a;margin-top:8px;line-height:1.45"
           id="fv-note">来自 09_pi_fullval.py 在树莓派上的实测。</div>
    </div>
    <div class="card">
      <h2>操作</h2>
      <button id="bImages" onclick="setMode('images')">图片循环</button>
      <button id="bPause" onclick="setMode('pause')">暂停</button>
      <button id="bCamera" onclick="setMode('camera')">摄像头</button>
      <button onclick="nextImg()">下一张 →</button>
    </div>
  </aside>
</main>
<script>
const ZH = {cardboard:"纸板", glass:"玻璃", metal:"金属", paper:"纸",
            plastic:"塑料", trash:"其他垃圾"};
const MODE_ZH = {images:"图片循环", pause:"已暂停", camera:"摄像头实时"};

// 帧同步：图片和侧栏数字必须来自同一帧。
// 图片模式走 /frame?seq=N 单帧 JPEG，只有 img.onload 之后才把侧栏切到第 N 帧，
// 这样"图上写什么、侧栏就是什么"，不会出现侧栏领先画面一帧。
// 摄像头模式仍走 /stream 连续 MJPEG，此时侧栏跟随实时数据（画面上也一直在动，看不出延迟）。
let renderedSeq = -1;   // 侧栏当前对应哪一帧
let wantSeq = -1;       // 已经请求显示哪一帧
let metaBySeq = {};     // seq -> /api 快照
let curSrc = '';        // 'frame' | 'stream'

function setMode(m){ fetch('/api/mode?m='+m).then(r=>r.json()).then(refresh); }
function nextImg(){ fetch('/api/next').then(r=>r.json()).then(refresh); }

// 与"某一帧"绑定的数字
function renderFrame(d){
  document.getElementById('pred').textContent = d.top ? (ZH[d.top] || d.top) : '—';
  document.getElementById('conf').textContent =
    d.conf != null ? ('置信度 ' + (d.conf*100).toFixed(1) + '%') : '—';
  document.getElementById('truth').textContent =
    d.truth ? (ZH[d.truth] || d.truth) : (d.mode === 'camera' ? '（实时画面）' : '—');

  const bars = document.getElementById('bars');
  bars.innerHTML = '';
  (d.top3 || []).forEach(([cls, p]) => {
    const pct = (p*100).toFixed(1);
    bars.insertAdjacentHTML('beforeend',
      '<div class="row"><span class="k">'+ (ZH[cls]||cls) +'</span>' +
      '<span class="v">'+ pct +'%</span></div>' +
      '<div class="bar"><i style="width:'+ pct +'%"></i></div>');
  });

  const st = d.stats || {};
  document.getElementById('n').textContent = st.n ?? 0;
  document.getElementById('correct').textContent = st.correct ?? 0;
  document.getElementById('acc').textContent =
    st.n ? ((st.correct/st.n*100).toFixed(1) + '%') : '—';
  document.getElementById('ms').textContent = d.ms != null ? d.ms + ' ms' : '—';
  document.getElementById('prog').textContent = (d.index+1) + ' / ' + d.total;

  // 全量验证集（379 张）—— 固定参考值，与上面的"本次运行"严格区分
  const fv = d.fullval || {};
  if (fv.n) {
    document.getElementById('fv-correct').textContent = fv.correct + ' / ' + fv.n;
    document.getElementById('fv-acc').textContent = (fv.accuracy*100).toFixed(2) + '%';
    document.getElementById('fv-ms').textContent =
      fv.median_ms != null ? fv.median_ms + ' ms' : '—';
  }
}

// 与帧无关的实时状态
function renderStatus(d){
  document.getElementById('modeBadge').textContent = MODE_ZH[d.mode] || d.mode;
  const note = document.getElementById('camNote');
  note.textContent = d.camera_ok ? '摄像头：已就绪'
                                 : '摄像头：' + (d.camera_err || '未连接');
  note.title = d.camera_err || '';
  for (const [id, on] of [['bImages', d.mode==='images'],
                          ['bPause', d.mode==='pause'],
                          ['bCamera', d.mode==='camera']]) {
    document.getElementById(id).classList.toggle('on', on);
  }
}

function showFrame(seq, d){
  const img = document.getElementById('stream');
  let done = false;
  const apply = () => {
    if (done) return;
    done = true;
    if (renderedSeq === seq) return;
    renderedSeq = seq;
    renderFrame(metaBySeq[seq] || d);
    Object.keys(metaBySeq).forEach(k => { if (+k < seq - 8) delete metaBySeq[k]; });
  };
  img.onload = apply;    // 图片解码完成 = 这一帧真的上屏了，此刻才切数字
  img.onerror = apply;   // 出错也切，避免永久卡在旧帧
  img.src = '/frame?seq=' + seq;
}

function refresh(){
  fetch('/api').then(r=>r.json()).then(d=>{
    renderStatus(d);
    const img = document.getElementById('stream');

    if (d.mode === 'camera') {
      if (curSrc !== 'stream') {
        curSrc = 'stream'; renderedSeq = -1; wantSeq = -1;
        img.onload = null; img.onerror = null;
        img.src = '/stream?t=' + Date.now();
      }
      renderFrame(d);
      return;
    }

    metaBySeq[d.frame_seq] = d;
    if (curSrc !== 'frame') { curSrc = 'frame'; renderedSeq = -1; wantSeq = -1; }
    if (d.frame_seq !== wantSeq) { wantSeq = d.frame_seq; showFrame(d.frame_seq, d); }
  }).catch(()=>{});
}
setInterval(refresh, 1200);   // 内容每 2 秒才换，500ms 轮询只是白烧 CPU
refresh();
</script>
</body>
</html>
"""


def _qint(query: str, key: str):
    """从 query string 里取一个整数参数；取不到或不是整数时返回 None。"""
    for part in query.split("&"):
        if part.startswith(key + "="):
            try:
                return int(part[len(key) + 1:])
            except ValueError:
                return None
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # keep-alive 空闲超时（秒）。浏览器会做预连接：把 TCP 握上手却不发请求，
    # 默认没有超时的话，那条线程会永久卡在 readline() 里，越攒越多。
    timeout = 20

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path

        if path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/health":
            self._send(200, json.dumps({"ok": True}).encode())
            return

        if path == "/api":
            seq = _qint(urlparse(self.path).query, "seq")
            self._send(200, json.dumps(STATE.snapshot(seq), ensure_ascii=False).encode())
            return

        if path == "/frame":
            # 单帧 JPEG：前端按 seq 取"它要显示的那一帧"，形成 img.onload 的确定性时序
            seq = _qint(urlparse(self.path).query, "seq")
            data, _meta = STATE.get_frame(seq)
            if not data:
                self._send(404, b"no frame yet", "text/plain; charset=utf-8")
                return
            self._send(200, data, "image/jpeg")
            return

        if path == "/api/mode":
            q = urlparse(self.path).query
            m = ""
            for part in q.split("&"):
                if part.startswith("m="):
                    m = unquote(part[2:])
            ok = STATE.set_mode(m)
            self._send(
                200,
                json.dumps({"ok": ok, "mode": STATE.mode,
                            "camera_ok": STATE.camera_ok,
                            "camera_err": STATE.camera_err}).encode(),
            )
            return

        if path == "/api/next":
            STATE.next_image()
            self._send(200, json.dumps({"ok": True, "index": STATE.index}).encode())
            return

        if path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while True:
                    with STATE.lock:
                        seq, data = STATE.frame_seq, STATE.frame
                    if data and seq != last:
                        last = seq
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode())
                        self.wfile.write(data)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        self._send(404, json.dumps({"error": "not found"}).encode())


def collect_images(root: Path) -> list[dict]:
    items = []
    if root.exists():
        for cls_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for f in sorted(cls_dir.iterdir()):
                if f.suffix.lower() in IMG_EXTS:
                    items.append({"path": f, "rel": f"{cls_dir.name}/{f.name}",
                                  "true": cls_dir.name})
    return items


MAX_CONN = 24


class DemoServer(ThreadingHTTPServer):
    """带并发上限的 HTTP 服务器。

    stdlib 的 ThreadingHTTPServer 有两个隐患，在树莓派上会被放大：
      * `request_queue_size` 默认只有 5，突发请求会溢出 accept 队列，
        内核会打印 "Possible SYN flooding on port ..."，之后新连接要等重传
      * 每个连接开一个线程且没有上限，keep-alive 连接会把线程一直占着

    这里把 accept 队列放宽到 64，并用信号量把并发线程钉死在 MAX_CONN；
    超过上限的连接直接关掉（浏览器会自动重试），绝不让它堆在队列里。
    """

    request_queue_size = 64
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, max_conn=MAX_CONN):
        super().__init__(address, handler)
        self._slots = threading.BoundedSemaphore(max_conn)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.close()
            except OSError:
                pass
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def main():
    global STATE, PRED

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="图片模式每张停留秒数（默认 2.0）")
    ap.add_argument("--images", default=str(HERE / "demo_images"))
    ap.add_argument("--model", default=str(HERE / "trashnet_mobilenetv2_int8.tflite"))
    ap.add_argument("--meta", default=str(HERE / "meta.json"))
    args = ap.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        alt = find_file(["trashnet_mobilenetv2_int8.tflite"])
        if alt is None:
            print("[FATAL] 找不到模型文件", file=sys.stderr)
            return 1
        model_path = alt

    meta_path = Path(args.meta) if Path(args.meta).exists() else find_file(["meta.json"])

    print(f"[info] 模型: {model_path}")
    print(f"[info] 元数据: {meta_path}")
    PRED = Predictor(model_path, meta_path)
    print(f"[info] 类别: {PRED.class_names}")

    root = Path(args.images)
    items = collect_images(root)
    print(f"[info] 演示图库: {root}  → {len(items)} 张")
    if not items:
        print(f"[warn] {root} 里没有图片", file=sys.stderr)

    STATE = State(items, args.interval)

    # 先出一帧占位，避免页面空白
    with STATE.lock:
        STATE.frame = compose(
            Image.new("RGB", (640, 360), (16, 17, 20)), None, None, "启动中…"
        )
        STATE.frame_seq = 1
        STATE.push_frame_locked(STATE.frame_seq, STATE.frame, {
            "mode": "images",
            "index": 0,
            "total": len(items),
            "stats": {"n": 0, "correct": 0},
            "file": None,
            "truth": None,
            "top": None,
            "conf": None,
            "top3": [],
            "ms": None,
        })

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    srv = DemoServer((args.host, args.port), Handler)
    print(f"[ready] http://{args.host}:{args.port}/   图片模式，每张 {args.interval}s")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[bye]")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
