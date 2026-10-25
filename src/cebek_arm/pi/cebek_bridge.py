#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cebek_bridge.py · STM32 ↔ 树莓派 ↔ OWI-535 机械臂 的 USB 桥
============================================================

职责只有一件事：**把 STM32 从串口发来的 3 字节，原样写到机械臂的 USB。**
所有"聪明"的东西（菜单、状态机、安全计时）都在 STM32 上；这里只做搬运，
外加一个**看门狗**——因为这台臂"发了命令就一直动"，所以通信一断必须有人
替它踩刹车。

为什么看门狗放在树莓派
----------------------
STM32 掉电、UART 线松了、程序死循环 —— 这些情况下 STM32 自己发不出停止帧。
而树莓派在这里是唯一还能动作的一方。它一旦发现"1500 ms 没收到新命令"，
就自动发 `00 00 00`。这是最后一道保险。

串口线序协议（ASCII 文本，一行一条，回车换行结尾）
--------------------------------------------------
    STM32 → 树莓派
        ARM <b0> <b1> <b2>     三个十六进制字节，例如  ARM 41 00 00
        PING                   心跳
        NOP                    空操作（仅刷新看门狗）

    树莓派 → STM32
        OK                     命令已执行
        PONG                   心跳回应
        ERR <原因>
        TMO                    看门狗触发，已发停止帧

用法
----
    python3 cebek_bridge.py --port /dev/ttyACM0          # 连 STM32 的虚拟串口
    python3 cebek_bridge.py --port /dev/serial0 --baud 115200
    python3 cebek_bridge.py --stdio                      # 从标准输入读命令（测试用）
    python3 cebek_bridge.py --stdio --no-usb             # 只测协议解析，不碰硬件

    --watchdog-ms 1500   多久没命令就自动停
    --no-usb             不打开 USB（干跑）
    --verbose            打印每一帧
"""

import argparse
import os
import select
import sys
import termios
import threading
import time
import tty

import cebek   # 同目录下的协议与 libusb 封装


# ──────────────────────────────────────────────────────────────
# 串口（不依赖 pyserial，纯 termios）
# ──────────────────────────────────────────────────────────────

def open_serial(path, baud=115200):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    # 原始模式：不要回显、不要行缓冲、不要软流控
    attrs[0] = 0                                                   # iflag
    attrs[1] = 0                                                   # oflag
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL        # cflag
    attrs[3] = 0                                                   # lflag
    attrs[4] = attrs[5] = BAUD_TABLE[baud]
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


BAUD_TABLE = {
    9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
    57600: termios.B57600, 115200: termios.B115200,
    230400: termios.B230400,
}


def list_serial_candidates():
    out = []
    for pat in ("/dev/ttyACM", "/dev/ttyUSB"):
        d = os.path.dirname(pat)
        base = os.path.basename(pat)
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if name.startswith(base):
                    out.append(os.path.join(d, name))
    if os.path.exists("/dev/serial0"):
        out.append("/dev/serial0")
    return out


# ──────────────────────────────────────────────────────────────
# 桥本体
# ──────────────────────────────────────────────────────────────

class Bridge:
    def __init__(self, arm, write, watchdog_ms=1500, verbose=False):
        self.arm = arm
        self.write = write                 # 回话给 STM32 的函数
        self.watchdog_s = watchdog_ms / 1000.0
        self.verbose = verbose
        self.last_cmd_time = time.time()
        self.last_state = cebek.STOP
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.stats = {"arm": 0, "ping": 0, "nop": 0, "bad": 0, "tmo": 0}

    def log(self, m):
        if self.verbose:
            print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)

    # ── 看门狗 ─────────────────────────────────────────────
    def watchdog_loop(self):
        while not self._stop.wait(0.1):
            with self._lock:
                idle = time.time() - self.last_cmd_time
                moving = (self.last_state != cebek.STOP)
            if moving and idle > self.watchdog_s:
                self.send_stop("看门狗：%.1f s 没收到新命令" % idle)
                self.stats["tmo"] += 1
                self.write("TMO\n")

    def send_stop(self, why=""):
        try:
            if self.arm is not None:
                self.arm.send(cebek.STOP)
        except Exception as e:
            print("!! 发停止帧失败：%r" % e, file=sys.stderr, flush=True)
        with self._lock:
            self.last_state = cebek.STOP
            self.last_cmd_time = time.time()
        self.log("STOP %s" % why)

    # ── 命令处理 ────────────────────────────────────────────
    def handle(self, line):
        line = line.strip()
        if not line:
            return
        parts = line.split()
        cmd = parts[0].upper()

        if cmd in ("ARM", "A"):
            if len(parts) != 4:
                self.stats["bad"] += 1
                self.write("ERR need 3 bytes\n")
                return
            try:
                data = bytes(int(p, 16) for p in parts[1:4])
            except ValueError:
                self.stats["bad"] += 1
                self.write("ERR bad hex\n")
                return
            if self.arm is not None:
                try:
                    method, rc = self.arm.send(data)
                except Exception as e:
                    self.write("ERR usb %s\n" % type(e).__name__)
                    self.log("USB 发送失败 %r" % e)
                    return
                with self._lock:
                    self.last_state = data
                    self.last_cmd_time = time.time()
                self.stats["arm"] += 1
                self.log("ARM %s  via %s  （%s）"
                         % (data.hex(" ").upper(), method, cebek.describe(data)))
            else:
                with self._lock:
                    self.last_state = data
                    self.last_cmd_time = time.time()
                self.stats["arm"] += 1
                self.log("ARM %s  （--no-usb，未发出）（%s）"
                         % (data.hex(" ").upper(), cebek.describe(data)))
            self.write("OK\n")
            return

        if cmd in ("PING", "P"):
            self.stats["ping"] += 1
            with self._lock:
                self.last_cmd_time = time.time()
            self.write("PONG\n")
            return

        if cmd in ("NOP", "N", "STOP"):
            # NOP 只刷看门狗；STOP 真的踩刹车
            if cmd == "STOP":
                self.send_stop("收到 STOP 命令")
            else:
                with self._lock:
                    self.last_cmd_time = time.time()
            self.stats["nop"] += 1
            self.write("OK\n")
            return

        self.stats["bad"] += 1
        self.write("ERR unknown %s\n" % cmd)

    # ── 主循环（从 fd 读字节流）──────────────────────────────
    def run_stream(self, fd):
        buf = b""
        self.log("桥已启动，看门狗 %.0f ms" % (self.watchdog_s * 1000))
        while not self._stop.is_set():
            try:
                r, _, _ = select.select([fd], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                chunk = os.read(fd, 256)
            except BlockingIOError:
                continue
            except OSError:
                break
            if not chunk:
                # select 说可读、read 却返回空 = EOF / 挂断（管道读完、USB 串口被拔）
                self.log("输入流结束（EOF/挂断）")
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.handle(line.decode("utf-8", "replace"))
        self.shutdown()

    # ── 收尾 ────────────────────────────────────────────────
    def shutdown(self):
        self._stop.set()
        self.send_stop("程序退出")
        print("统计：%s" % self.stats, flush=True)


def main(argv):
    ap = argparse.ArgumentParser(description="STM32 ↔ 树莓派 ↔ OWI-535 USB 桥")
    ap.add_argument("--port", default=None, help="串口设备，如 /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200, choices=sorted(BAUD_TABLE))
    ap.add_argument("--stdio", action="store_true", help="从标准输入读命令（测试用）")
    ap.add_argument("--no-usb", action="store_true", help="不打开机械臂 USB")
    ap.add_argument("--watchdog-ms", type=int, default=1500)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    # ── 打开机械臂 ──
    arm = None
    if not args.no_usb:
        arm = cebek.Arm(verbose=False)
        if not arm.connect():
            print("!! 没找到机械臂。可以加 --no-usb 干跑。", file=sys.stderr)
            return 2
        print("机械臂已连接 %04X:%04X" % (arm.info["dd"].idVendor,
                                          arm.info["dd"].idProduct), flush=True)

    # ── 输出通道 ──
    if args.stdio:
        def write(s):
            sys.stdout.write("<< " + s)
            sys.stdout.flush()
        fd = sys.stdin.fileno()
    else:
        port = args.port
        if port is None:
            cands = list_serial_candidates()
            if not cands:
                print("!! 没找到串口，可选：%s" % (cands or "无"), file=sys.stderr)
                print("   插上 Nucleo 后应该是 /dev/ttyACM0", file=sys.stderr)
                return 2
            port = cands[0]
            print("自动选择串口：%s" % port, flush=True)
        try:
            fd = open_serial(port, args.baud)
        except (OSError, termios.error) as e:
            print("!! 打开串口 %s 失败：%s" % (port, e), file=sys.stderr)
            return 2
        print("串口已打开 %s @ %d" % (port, args.baud), flush=True)

        def write(s):
            try:
                os.write(fd, s.encode())
            except OSError:
                pass

    bridge = Bridge(arm, write, args.watchdog_ms, args.verbose)
    wd = threading.Thread(target=bridge.watchdog_loop, daemon=True)
    wd.start()
    try:
        bridge.run_stream(fd)
    except KeyboardInterrupt:
        bridge.shutdown()
    finally:
        if arm is not None:
            arm.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
