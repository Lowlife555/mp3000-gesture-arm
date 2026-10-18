#!/usr/bin/env python3
"""
07 Pi 网页看摄像头 + 识别结果（纯标准库，不依赖 Flask）

页面：   http://<pi>:8080
    /         HTML 页面（左边视频流，右边识别结果，每秒刷新）
    /stream   MJPEG 视频流
    /api      JSON 当前预测
    /health   健康检查

用法：
    python 07_pi_webcam.py                 # 正常跑（需要 CSI 或 USB 摄像头）
    python 07_pi_webcam.py --port 8080
    python 07_pi_webcam.py --test-pattern  # 没有摄像头时用合成图验证整条链路
    python 07_pi_webcam.py --interval 0.2  # 每 0.2 秒一帧

⚠️ 必须用装了 ai-edge-litert + picamera2 的那个 venv 跑：
    source ~/trashnet-env/bin/activate && python 07_pi_webcam.py
"""
import argparse
import io
import json
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent if "__file__" in globals() else pathlib.Path(".")
MODEL_CANDIDATES = [
    HERE / "trashnet_mobilenetv2_int8.tflite",
    HERE / "models" / "trashnet_mobilenetv2_int8.tflite",
    pathlib.Path.home() / "trashnet_demo" / "trashnet_mobilenetv2_int8.tflite",
]
META_CANDIDATES = [
    HERE / "meta.json",
    HERE / "models" / "meta.json",
    pathlib.Path.home() / "trashnet_demo" / "meta.json",
]

MODEL = next((p for p in MODEL_CANDIDATES if p.exists()), None)
META = next((p for p in META_CANDIDATES if p.exists()), None)
if MODEL is None or META is None:
    sys.exit("❌ 找不到 trashnet_mobilenetv2_int8.tflite / meta.json（应在 ~/trashnet_demo/）")

from ai_edge_litert.interpreter import Interpreter  # noqa: E402

meta = json.loads(META.read_text(encoding="utf-8"))
CLASSES = meta["class_names"]
IMG = meta["img_size"]

interp = Interpreter(model_path=str(MODEL))
interp.allocate_tensors()
IN = interp.get_input_details()[0]
OUT = interp.get_output_details()[0]

STATE = {
    "jpeg": None, "top": [], "ms": 0.0, "err": None,
    "frames": 0, "fps": 0.0, "ts": 0.0, "src": "-",
}
LOCK = threading.Lock()


def infer(rgb):
    """rgb: HxWx3 uint8 → (top3 [(cls, prob)], ms)"""
    img = Image.fromarray(rgb).resize((IMG, IMG), Image.Resampling.BILINEAR)
    arr = np.asarray(img, dtype=np.uint8)[None, ...]
    interp.set_tensor(IN["index"], arr)
    t0 = time.perf_counter()
    interp.invoke()
    ms = (time.perf_counter() - t0) * 1000.0
    p = interp.get_tensor(OUT["index"])[0].astype(np.float32)
    s, z = OUT["quantization"]
    if s:
        p = (p - z) * s
    if p.sum() > 0:
        p = p / p.sum()
    order = np.argsort(p)[::-1][:3]
    return [(CLASSES[i], float(p[i])) for i in order], ms


def encode_jpeg(rgb, label=None, conf=None, ms=None):
    im = Image.fromarray(rgb)
    if label is not None:
        d = ImageDraw.Draw(im)
        txt = f"{label} {conf:.1%}  {ms:.0f}ms"
        d.rectangle([0, 0, im.width, 22], fill=(0, 0, 0))
        d.text((6, 5), txt, fill=(0, 255, 128))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def make_placeholder(text):
    im = Image.new("RGB", (640, 480), (18, 18, 22))
    d = ImageDraw.Draw(im)
    d.text((20, 220), text, fill=(255, 120, 120))
    d.text((20, 250), "plug in the CSI camera, then restart this service", fill=(160, 160, 160))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def test_pattern(t):
    """合成一张彩条图，用来在没有摄像头时验证整条链路"""
    arr = np.zeros((480, 640, 3), dtype=np.uint8)
    cols = [(200, 60, 60), (60, 200, 60), (60, 60, 200),
            (200, 200, 60), (200, 60, 200), (60, 200, 200)]
    w = 640 // len(cols)
    for i, c in enumerate(cols):
        arr[:, i * w:(i + 1) * w] = c
    # 中间放一个会呼吸的方块，肉眼能看出流是活的
    k = int(60 + 40 * abs(np.sin(t)))
    arr[240 - k // 2:240 + k // 2, 320 - k // 2:320 + k // 2] = (255, 255, 255)
    return arr


def worker(args):
    cam = None
    if args.test_pattern:
        with LOCK:
            STATE["src"] = "test-pattern"
        print("模式：合成测试图（不需要摄像头）")
    else:
        try:
            from picamera2 import Picamera2
            cam = Picamera2()
            cfg = cam.create_preview_configuration(
                main={"size": (640, 480), "format": "RGB888"})
            cam.configure(cfg)
            cam.start()
            time.sleep(2)
            for _ in range(5):
                cam.capture_array()
            with LOCK:
                STATE["src"] = "CSI/USB camera 640x480"
            print("摄像头已启动 640x480 RGB888")
        except Exception as e:
            msg = f"没有可用摄像头: {type(e).__name__}: {e}"
            print("⚠️", msg)
            with LOCK:
                STATE["err"] = msg
                STATE["src"] = "none"
                STATE["jpeg"] = make_placeholder("NO CAMERA")
            cam = None

    t_loop = 0.0
    n0, t0 = 0, time.time()
    while True:
        t_loop += args.interval
        try:
            if args.test_pattern:
                rgb = test_pattern(t_loop)
            elif cam is not None:
                rgb = cam.capture_array()
                if rgb.ndim == 3 and rgb.shape[2] == 4:
                    rgb = rgb[:, :, :3]
            else:
                time.sleep(1.0)
                continue

            top, ms = infer(rgb)
            jpg = encode_jpeg(rgb, top[0][0], top[0][1], ms)
            n0 += 1
            fps = n0 / max(1e-6, time.time() - t0)
            with LOCK:
                STATE.update(jpeg=jpg, top=top, ms=ms, err=None,
                             frames=n0, fps=fps, ts=time.time())
        except Exception as e:
            with LOCK:
                STATE["err"] = f"{type(e).__name__}: {e}"
            time.sleep(1.0)
        time.sleep(max(0.0, args.interval - 0.02))


HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>MP3000 · 垃圾分类实时识别</title>
<style>
 body{margin:0;background:#111;color:#eee;font-family:system-ui,"Segoe UI",sans-serif}
 .wrap{display:flex;gap:16px;padding:16px;align-items:flex-start;flex-wrap:wrap}
 img{width:640px;max-width:100%;border-radius:8px;background:#000}
 .card{background:#1b1b20;border-radius:8px;padding:16px;min-width:300px}
 h1{font-size:18px;margin:0 0 12px;color:#8fd}
 .big{font-size:40px;font-weight:700;color:#0f8;margin:8px 0}
 .row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #2a2a33}
 .muted{color:#888;font-size:13px}
 .bar{height:8px;background:#2a2a33;border-radius:4px;overflow:hidden;margin-top:4px}
 .fill{height:100%;background:#0f8}
 .err{color:#f77}
</style></head><body>
<div class="wrap">
  <div>
    <img src="/stream" alt="stream">
    <div class="muted" id="meta" style="margin-top:8px">—</div>
  </div>
  <div class="card">
    <h1>识别结果</h1>
    <div class="big" id="top">—</div>
    <div id="probs"></div>
    <div class="muted" style="margin-top:12px" id="stat">—</div>
    <div class="err" id="err"></div>
  </div>
</div>
<script>
async function tick(){
  try{
    const r = await fetch('/api',{cache:'no-store'});
    const j = await r.json();
    document.getElementById('top').textContent =
      j.top && j.top.length ? j.top[0][0] : '—';
    document.getElementById('probs').innerHTML = (j.top||[]).map(([c,p])=>
      `<div class="row"><span>${c}</span><span>${(p*100).toFixed(1)}%</span></div>
       <div class="bar"><div class="fill" style="width:${(p*100).toFixed(1)}%"></div></div>`
    ).join('');
    document.getElementById('stat').textContent =
      `推理 ${j.ms.toFixed(1)} ms · ${j.fps.toFixed(1)} fps · 共 ${j.frames} 帧 · 源: ${j.src}`;
    document.getElementById('err').textContent = j.err ? ('⚠️ '+j.err) : '';
    document.getElementById('meta').textContent =
      j.err ? '等待摄像头…' : '实时画面（Pi 本地推理）';
  }catch(e){}
}
setInterval(tick, 1000); tick();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    with LOCK:
                        jpg = STATE["jpeg"]
                    if jpg is None:
                        jpg = make_placeholder("STARTING...")
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpg)}\r\n\r\n".encode())
                    self.wfile.write(jpg + b"\r\n")
                    self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError):
                return
        elif self.path.startswith("/api"):
            with LOCK:
                body = json.dumps({
                    "top": STATE["top"], "ms": STATE["ms"], "err": STATE["err"],
                    "frames": STATE["frames"], "fps": STATE["fps"],
                    "src": STATE["src"], "ts": STATE["ts"],
                }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/health"):
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--interval", type=float, default=0.2)
    ap.add_argument("--test-pattern", action="store_true")
    args = ap.parse_args()

    print(f"模型: {MODEL}  ({MODEL.stat().st_size/1024/1024:.2f} MB)")
    print(f"类别: {CLASSES}")
    threading.Thread(target=worker, args=(args,), daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"网页: http://<pi-ip>:{args.port}/   （Ctrl+C 停止）")
    srv.serve_forever()


if __name__ == "__main__":
    main()
