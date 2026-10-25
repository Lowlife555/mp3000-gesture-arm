#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cebek C-9895.2 机械臂 · 树莓派控制台
=====================================

这台臂的真身
------------
VID:PID = **1267:0000** 属于 **OWI Inc.**。Cebek C-9895.2 是
**OWI Robotic Arm Edge（型号 OWI-535）**的贴牌版本，两者协议相同：

    3 字节命令，byte0/byte1/byte2，位打包
    byte0 [1:0]=夹爪 [3:2]=腕 [5:4]=肘 [7:6]=肩   每 2 位：00 停 / 01 正 / 10 反
    byte1 [1:0]=底座旋转                          00 停 / 01 顺时针 / 10 逆时针
    byte2 [0]  =爪内照明 LED                      0 关 / 1 开

**关键语义**：发一次命令，机械臂会**一直动到下一次命令**；
`00 00 00` 是通用停止。所以"动 200 毫秒"= 发命令 → 等 200 ms → 发 `00 00 00`。
这正是原厂说明书里 Program 模式的"时间"含义。

传输方式
--------
OWI 的开源实现普遍用 **control transfer**：
    bmRequestType=0x40  bRequest=0x06  wValue=0x0100  wIndex=0  data=3 字节
但原厂 Windows 驱动是 WDK BulkUsb 示例改的，说明设备**同时有 bulk 端点**。
本程序默认先试 control，失败再自动退回 bulk OUT，并记住哪种成功了。

为什么不用 pip
--------------
纯标准库 `ctypes` 直接调系统里的 `libusb-1.0.so.0`。不装 pyusb、
不建 venv、不碰 Debian 13 的 PEP 668。零依赖，双击就能跑。

用法
----
    python3 cebek.py info                    # 枚举设备 + 描述符 + 端点（只读，零风险）
    python3 cebek.py gui                     # 图形界面（在树莓派桌面上双击）
    python3 cebek.py test                    # 安全自检：灯光开/关、夹爪轻动（会动，需 --yes）
    python3 cebek.py move shoulder up 300    # 肩部向上 300 ms（需 --yes）
    python3 cebek.py light on                # 爪内 LED 开
    python3 cebek.py stop                    # 立刻发 00 00 00
    python3 cebek.py raw 000000              # 发原始 3 字节（需 --yes）

安全
----
- 会动 USB 的命令都要 `--yes`。
- 单次动作硬上限 **3000 ms**。
- 任何异常/中断（Ctrl-C、异常、窗口关闭）都会在 finally 里发 `00 00 00`。
- 首次使用先跑 `info`，确认设备在、端点对，再跑 `test`。
"""

import ctypes
import ctypes.util
import os
import sys
import threading
import time

# ──────────────────────────────────────────────────────────────
# 设备与协议常量
# ──────────────────────────────────────────────────────────────

VID = 0x1267
PID = 0x0000

# 备用候选（原厂 INF 里还列了这两个，理论上不该用到）
FALLBACK_IDS = [(0x04F3, 0x0000), (0x1B47, 0x0001)]

MAX_MS = 3000
DEFAULT_TIMEOUT_MS = 3000

# 关节 → byte0 里的位移量 / byte1 的位移量
JOINTS = {
    "gripper":  {"shift": 0, "byte": 0, "cn": "夹爪",    "pos": "夹/松"},
    "wrist":    {"shift": 2, "byte": 0, "cn": "腕部",    "pos": "上/下"},
    "elbow":    {"shift": 4, "byte": 0, "cn": "肘部",    "pos": "上/下"},
    "shoulder": {"shift": 6, "byte": 0, "cn": "肩部",    "pos": "上/下"},
    "base":     {"shift": 0, "byte": 1, "cn": "底座旋转", "pos": "顺/逆"},
}
ALIASES = {
    "1": "shoulder", "2": "elbow", "3": "wrist", "4": "gripper", "5": "base",
    "m1": "shoulder", "m2": "elbow", "m3": "wrist", "m4": "gripper", "m5": "base",
    "夹爪": "gripper", "腕": "wrist", "腕部": "wrist", "肘": "elbow", "肘部": "elbow",
    "肩": "shoulder", "肩部": "shoulder", "底座": "base", "底座旋转": "base",
}
DIRS = {"fwd": 1, "up": 1, "cw": 1, "open": 1, "正": 1, "上": 1, "顺": 1, "松": 1,
        "rev": 2, "down": 2, "ccw": 2, "close": 2, "反": 2, "下": 2, "逆": 2, "夹": 2}

LIBUSB_ERROR_NAMES = {
    -1: "IO", -2: "INVALID_PARAM", -3: "ACCESS（权限不足）", -4: "NO_DEVICE",
    -5: "NOT_FOUND", -6: "BUSY", -7: "TIMEOUT", -9: "PIPE",
    -11: "INTERRUPTED", -12: "NO_MEM", -99: "OTHER",
}

TRANSPORT_CACHE = None   # "control" / "bulk"，第一次成功后记住


def err_name(code):
    return LIBUSB_ERROR_NAMES.get(code, str(code))


class DeviceDescriptor(ctypes.Structure):
    """libusb_device_descriptor，18 字节，字段顺序必须与 libusb.h 一致"""
    _fields_ = [
        ("bLength", ctypes.c_uint8), ("bDescriptorType", ctypes.c_uint8),
        ("bcdUSB", ctypes.c_uint16), ("bDeviceClass", ctypes.c_uint8),
        ("bDeviceSubClass", ctypes.c_uint8), ("bDeviceProtocol", ctypes.c_uint8),
        ("bMaxPacketSize0", ctypes.c_uint8), ("idVendor", ctypes.c_uint16),
        ("idProduct", ctypes.c_uint16), ("bcdDevice", ctypes.c_uint16),
        ("iManufacturer", ctypes.c_uint8), ("iProduct", ctypes.c_uint8),
        ("iSerialNumber", ctypes.c_uint8), ("bNumConfigurations", ctypes.c_uint8),
    ]


# ──────────────────────────────────────────────────────────────
# 协议编码
# ──────────────────────────────────────────────────────────────

def encode(gripper=0, wrist=0, elbow=0, shoulder=0, base=0, light=0):
    """把各关节动作打包成 3 字节。动作值：0=停 1=正 2=反"""
    b0 = ((gripper & 3) | ((wrist & 3) << 2) |
          ((elbow & 3) << 4) | ((shoulder & 3) << 6))
    b1 = base & 3
    b2 = light & 1
    return bytes([b0, b1, b2])


def encode_one(joint, action, light=0):
    joint = ALIASES.get(joint, joint)
    spec = JOINTS[joint]
    kw = {"light": light}
    kw[joint] = action
    return encode(**kw)


STOP = encode()


def describe(cmd):
    """把 3 字节翻译成人话，便于日志核对"""
    b0, b1, b2 = cmd
    parts = []
    for name in ("gripper", "wrist", "elbow", "shoulder"):
        v = (b0 >> JOINTS[name]["shift"]) & 3
        if v:
            parts.append("%s:%s" % (JOINTS[name]["cn"], "正" if v == 1 else "反"))
    v = b1 & 3
    if v:
        parts.append("底座:%s" % ("顺" if v == 1 else "逆"))
    if b2 & 1:
        parts.append("灯:开")
    return " / ".join(parts) if parts else "全部停止"


# ──────────────────────────────────────────────────────────────
# libusb ctypes 绑定
# ──────────────────────────────────────────────────────────────

class LibUSB:
    def __init__(self):
        path = ctypes.util.find_library("usb-1.0") or "libusb-1.0.so.0"
        try:
            self.lib = ctypes.CDLL(path)
        except OSError as e:
            raise SystemExit("找不到 libusb-1.0，请先 sudo apt install libusb-1.0-0\n%s" % e)
        self._declare()
        self.ctx = ctypes.c_void_p()
        rc = self.lib.libusb_init(ctypes.byref(self.ctx))
        if rc != 0:
            raise SystemExit("libusb_init 失败：%s" % err_name(rc))
        self._devlist = None

    def _declare(self):
        L = self.lib
        p = ctypes.c_void_p
        L.libusb_init.argtypes = [ctypes.POINTER(p)]
        L.libusb_init.restype = ctypes.c_int
        L.libusb_exit.argtypes = [p]
        L.libusb_get_device_list.argtypes = [p, ctypes.POINTER(ctypes.POINTER(p))]
        L.libusb_get_device_list.restype = ctypes.c_ssize_t
        L.libusb_free_device_list.argtypes = [ctypes.POINTER(p), ctypes.c_int]
        L.libusb_open.argtypes = [p, ctypes.POINTER(p)]
        L.libusb_open.restype = ctypes.c_int
        L.libusb_close.argtypes = [p]
        L.libusb_claim_interface.argtypes = [p, ctypes.c_int]
        L.libusb_claim_interface.restype = ctypes.c_int
        L.libusb_release_interface.argtypes = [p, ctypes.c_int]
        L.libusb_detach_kernel_driver.argtypes = [p, ctypes.c_int]
        L.libusb_detach_kernel_driver.restype = ctypes.c_int
        L.libusb_control_transfer.argtypes = [
            p, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint16,
            ctypes.c_uint16, ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint16, ctypes.c_uint,
        ]
        L.libusb_control_transfer.restype = ctypes.c_int
        L.libusb_bulk_transfer.argtypes = [
            p, ctypes.c_ubyte, ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
        ]
        L.libusb_bulk_transfer.restype = ctypes.c_int
        L.libusb_get_string_descriptor_ascii.argtypes = [
            p, ctypes.c_uint8, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int,
        ]
        L.libusb_get_string_descriptor_ascii.restype = ctypes.c_int
        L.libusb_get_device_descriptor.argtypes = [p, ctypes.POINTER(DeviceDescriptor)]
        L.libusb_get_device_descriptor.restype = ctypes.c_int
        L.libusb_get_bus_number.argtypes = [p]
        L.libusb_get_bus_number.restype = ctypes.c_uint8
        L.libusb_get_device_address.argtypes = [p]
        L.libusb_get_device_address.restype = ctypes.c_uint8

    def list_devices(self):
        lst = ctypes.POINTER(ctypes.c_void_p)()
        n = self.lib.libusb_get_device_list(self.ctx, ctypes.byref(lst))
        if n < 0:
            raise SystemExit("libusb_get_device_list 失败：%s" % err_name(n))
        out = []
        for i in range(n):
            dev = lst[i]
            dd = DeviceDescriptor()
            if self.lib.libusb_get_device_descriptor(dev, ctypes.byref(dd)) != 0:
                continue
            out.append({
                "dev": dev,
                "vid": dd.idVendor, "pid": dd.idProduct,
                "bus": self.lib.libusb_get_bus_number(dev),
                "addr": self.lib.libusb_get_device_address(dev),
                "class": dd.bDeviceClass, "dd": dd,
            })
        self._devlist = (lst, n)
        return out

    def open(self, dev):
        h = ctypes.c_void_p()
        rc = self.lib.libusb_open(dev, ctypes.byref(h))
        if rc != 0:
            raise PermissionError(rc)
        return h

    def string(self, h, index):
        if not index:
            return ""
        buf = (ctypes.c_ubyte * 255)()
        rc = self.lib.libusb_get_string_descriptor_ascii(h, index, buf, 255)
        return buf[:rc].decode("utf-8", "replace") if rc >= 0 else ""

    def get_descriptor(self, h, dtype, index=0, langid=0, length=255):
        buf = (ctypes.c_ubyte * length)()
        rc = self.lib.libusb_control_transfer(
            h, 0x80, 0x06, (dtype << 8) | index, langid, buf, length, DEFAULT_TIMEOUT_MS)
        return (bytes(buf[:rc]) if rc > 0 else None)

    def claim(self, h, iface=0):
        rc = self.lib.libusb_detach_kernel_driver(h, iface)
        rc2 = self.lib.libusb_claim_interface(h, iface)
        return rc2

    def release(self, h, iface=0):
        return self.lib.libusb_release_interface(h, iface)

    def close(self, h):
        self.lib.libusb_close(h)

    def control_out(self, h, data, request=0x06, value=0x0100, index=0):
        """OWI 文献里的写法：bmRequestType=0x40, bRequest=0x06, wValue=0x0100"""
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        return self.lib.libusb_control_transfer(
            h, 0x40, request, value, index, buf, len(data), DEFAULT_TIMEOUT_MS)

    def bulk_write(self, h, ep, data, timeout=DEFAULT_TIMEOUT_MS):
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        actual = ctypes.c_int(0)
        rc = self.lib.libusb_bulk_transfer(h, ep, buf, len(data), ctypes.byref(actual), timeout)
        return rc, actual.value

    def bulk_read(self, h, ep, length=64, timeout=300):
        buf = (ctypes.c_ubyte * length)()
        actual = ctypes.c_int(0)
        rc = self.lib.libusb_bulk_transfer(h, ep, buf, length, ctypes.byref(actual), timeout)
        return rc, bytes(buf[:actual.value])

    def cleanup(self):
        try:
            if self._devlist:
                self.lib.libusb_free_device_list(self._devlist[0], 1)
        except Exception:
            pass
        try:
            self.lib.libusb_exit(self.ctx)
        except Exception:
            pass


def parse_config(data):
    if not data or len(data) < 9:
        return None
    total = data[2] | (data[3] << 8)
    cfg = {"total": total, "value": data[5], "maxpower_mA": data[8] * 2,
           "interfaces": []}
    i, cur = 0, None
    while i < len(data) and i < total:
        blen = data[i]
        if blen == 0:
            break
        btype = data[i + 1]
        if btype == 0x04 and blen >= 9:
            cur = {"num": data[i + 2], "alt": data[i + 3], "cls": data[i + 5],
                   "endpoints": []}
            cfg["interfaces"].append(cur)
        elif btype == 0x05 and blen >= 7 and cur is not None:
            addr = data[i + 2]
            attr = data[i + 3] & 3
            cur["endpoints"].append({
                "addr": addr, "hex": "0x%02X" % addr,
                "dir": "IN" if addr & 0x80 else "OUT",
                "type": {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}[attr],
                "max_packet": data[i + 4] | (data[i + 5] << 8),
                "interval": data[i + 6],
            })
        i += blen
    return cfg


PERMISSION_HELP = """
打开设备失败：%s

这是 Linux 的权限限制：/dev/bus/usb/* 默认只有 root 能写。
请在树莓派上跑一次下面这条（需要你输入密码），之后永久生效：

    echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1267", ATTR{idProduct}=="0000", MODE="0666"' \\
      | sudo tee /etc/udev/rules.d/99-cebek-arm.rules
    sudo udevadm control --reload-rules && sudo udevadm trigger

然后把机械臂 USB 拔下再插上。

（本程序不处理密码，也不会索取密码。）
"""


# ──────────────────────────────────────────────────────────────
# 机械臂对象
# ──────────────────────────────────────────────────────────────

class Arm:
    def __init__(self, verbose=True):
        self.usb = LibUSB()
        self.h = None
        self.info = None
        self.cfg = None
        self.ep_out = None
        self.ep_in = None
        self.method = None
        self.verbose = verbose
        self._lock = threading.Lock()

    def log(self, msg):
        if self.verbose:
            print(msg)

    def connect(self):
        devs = self.usb.list_devices()
        target = None
        for d in devs:
            if (d["vid"], d["pid"]) == (VID, PID):
                target = d
                break
        if target is None:
            for d in devs:
                if (d["vid"], d["pid"]) in FALLBACK_IDS:
                    target = d
                    break
        if target is None:
            self.log("没找到设备（VID:PID 既不是 %04X:%04X 也不是备用 ID）"
                     % (VID, PID))
            return False
        self.info = target
        try:
            self.h = self.usb.open(target["dev"])
        except PermissionError as e:
            raise SystemExit(PERMISSION_HELP % err_name(e.args[0]))
        data = self.usb.get_descriptor(self.h, 0x02, 0, 0, 512)
        self.cfg = parse_config(data) if data else None
        if self.cfg:
            for itf in self.cfg["interfaces"]:
                for ep in itf["endpoints"]:
                    if ep["type"] in ("bulk", "interrupt"):
                        if ep["dir"] == "OUT" and self.ep_out is None:
                            self.ep_out = ep["addr"]
                        if ep["dir"] == "IN" and self.ep_in is None:
                            self.ep_in = ep["addr"]
        self.usb.claim(self.h, 0)
        return True

    # ── 发送 ────────────────────────────────────────────────
    def send(self, cmd):
        """发 3 字节。先 control，失败自动退 bulk。"""
        global TRANSPORT_CACHE
        if len(cmd) != 3:
            raise ValueError("OWI 协议必须正好 3 字节，收到 %d 字节" % len(cmd))
        with self._lock:
            order = [TRANSPORT_CACHE] if TRANSPORT_CACHE else ["control", "bulk"]
            if TRANSPORT_CACHE is None:
                order = ["control", "bulk"]
            last = None
            for m in order:
                if m == "control":
                    rc = self.usb.control_out(self.h, cmd)
                    if rc >= 0:
                        TRANSPORT_CACHE = "control"
                        return "control", rc
                    last = ("control", rc)
                else:
                    if self.ep_out is None:
                        last = ("bulk", -5)
                        continue
                    rc, n = self.usb.bulk_write(self.h, self.ep_out, cmd)
                    if rc == 0:
                        TRANSPORT_CACHE = "bulk"
                        return "bulk", n
                    last = ("bulk", rc)
            raise RuntimeError("两种传输都失败：%s" % (last,))

    def stop(self):
        try:
            self.send(STOP)
        except Exception:
            pass

    def act(self, joint, action, ms, light=0, keep_light=None):
        """把关节动 ms 毫秒然后停。返回实际用时。"""
        joint = ALIASES.get(joint, joint)
        if joint not in JOINTS:
            raise SystemExit("未知关节：%s（可用：%s）"
                             % (joint, ", ".join(JOINTS)))
        action = DIRS.get(str(action).lower(), action)
        try:
            action = int(action)
        except (TypeError, ValueError):
            raise SystemExit("未知方向：%s（可用：fwd/up/cw/open 或 rev/down/ccw/close）"
                             % action)
        if action not in (1, 2):
            raise SystemExit("动作值只能是 1 或 2")
        ms = max(0, min(int(ms), MAX_MS))
        cmd = encode_one(joint, action, light=light)
        t0 = time.time()
        try:
            self.send(cmd)
            self.log("  → %s  %s  %d ms" % (cmd.hex(" ").upper(), describe(cmd), ms))
            while (time.time() - t0) * 1000.0 < ms:
                time.sleep(min(0.01, max(0.001, ms / 1000.0 / 4)))
        finally:
            self.stop()
        return time.time() - t0

    def light(self, on):
        cmd = encode(light=1 if on else 0)
        self.send(cmd)
        self.log("  → %s  灯%s" % (cmd.hex(" ").upper(), "开" if on else "关"))

    def close(self):
        try:
            self.stop()
        finally:
            try:
                if self.h:
                    self.usb.release(self.h, 0)
                    self.usb.close(self.h)
            finally:
                self.usb.cleanup()


# ──────────────────────────────────────────────────────────────
# 命令行子命令
# ──────────────────────────────────────────────────────────────

def need_yes(what):
    if "--yes" not in sys.argv:
        raise SystemExit(
            "「%s」会向机械臂发送字节，臂会动。\n"
            "确认臂在空旷处、手已离开夹爪后，在命令末尾加 --yes 重跑。" % what)


def cmd_info(_a):
    usb = LibUSB()
    try:
        devs = usb.list_devices()
        print("总线上共 %d 个设备\n" % len(devs))
        target = None
        for d in devs:
            mark = ""
            if (d["vid"], d["pid"]) == (VID, PID):
                mark = "   ← 机械臂 (OWI 0x1267:0x0000)"
                target = d
            elif (d["vid"], d["pid"]) in FALLBACK_IDS:
                mark = "   ← 备用候选 ID"
                target = target or d
            print("  %04X:%04X  总线 %d 地址 %-3d  class=0x%02X%s"
                  % (d["vid"], d["pid"], d["bus"], d["addr"], d["class"], mark))

        if target is None:
            print("\n没有匹配到机械臂。请检查：")
            print("  1. USB 线插在树莓派上（不是插在 Windows 电脑上）")
            print("  2. 接口板的 BKR 6V 电源已接")
            print("  3. 电源开关 J7 SW 拨到 ON")
            print("  4. 换一个 USB 口试试（Pi 4B 有两个 USB3 蓝口和两个 USB2 黑口）")
            return 1

        try:
            h = usb.open(target["dev"])
        except PermissionError as e:
            print(PERMISSION_HELP % err_name(e.args[0]))
            return 2

        dd = target["dd"]
        print("\n===== 设备详情 =====")
        print("  VID:PID        %04X:%04X" % (dd.idVendor, dd.idProduct))
        print("  bcdUSB         %04X" % dd.bcdUSB)
        print("  bcdDevice      %04X" % dd.bcdDevice)
        print("  设备类         0x%02X  sub=0x%02X  proto=0x%02X"
              % (dd.bDeviceClass, dd.bDeviceSubClass, dd.bDeviceProtocol))
        print("  厂商字符串     %r" % usb.string(h, dd.iManufacturer))
        print("  产品字符串     %r" % usb.string(h, dd.iProduct))
        print("  序列号         %r" % usb.string(h, dd.iSerialNumber))
        print("  配置数         %d" % dd.bNumConfigurations)

        data = usb.get_descriptor(h, 0x02, 0, 0, 512)
        if data:
            cfg = parse_config(data)
            print("\n===== 配置 %d  (总线取电上限 %d mA) ====="
                  % (cfg["value"], cfg["maxpower_mA"]))
            for itf in cfg["interfaces"]:
                print("  接口 %d  class=0x%02X  端点 %d 个"
                      % (itf["num"], itf["cls"], len(itf["endpoints"])))
                for ep in itf["endpoints"]:
                    print("      %s  %-9s 最大包 %-4d 间隔 %d"
                          % (ep["hex"], ep["type"], ep["max_packet"], ep["interval"]))
            ins = [ep for itf in cfg["interfaces"] for ep in itf["endpoints"]
                   if ep["dir"] == "IN" and ep["type"] in ("bulk", "interrupt")]
            if ins:
                ep = ins[0]
                rc, payload = usb.bulk_read(h, ep["addr"], ep["max_packet"], 300)
                print("\n  试读 IN 端点 %s：rc=%d 数据=%s"
                      % (ep["hex"], rc, payload.hex(" ").upper() if payload else "(空)"))
            else:
                print("\n  没有 IN 端点 —— 设备只收不回，与原厂 BulkUsb 行为一致。")
        usb.close(h)
        return 0
    finally:
        usb.cleanup()


def cmd_stop(_a):
    arm = Arm()
    try:
        if not arm.connect():
            return 1
        arm.stop()
        print("已发停止帧 00 00 00")
        return 0
    finally:
        arm.close()


def cmd_light(args):
    on = (args[0].lower() in ("on", "1", "开")) if args else True
    arm = Arm()
    try:
        if not arm.connect():
            return 1
        arm.light(on)
        return 0
    finally:
        arm.close()


def cmd_move(args):
    if len(args) < 3:
        raise SystemExit("用法：move <关节> <方向> <毫秒>\n"
                         "关节：shoulder / elbow / wrist / gripper / base\n"
                         "方向：up|down / fwd|rev / open|close / cw|ccw")
    need_yes("move")
    joint, d, ms = args[0], args[1], int(args[2])
    arm = Arm()
    try:
        if not arm.connect():
            return 1
        print("传输方式：%s" % (TRANSPORT_CACHE or "自动探测"))
        arm.act(joint, d, ms)
        print("完成，已停。")
        return 0
    finally:
        arm.close()


def cmd_raw(args):
    if not args:
        raise SystemExit("用法：raw 550500   （3 字节十六进制）")
    need_yes("raw")
    cmd = bytes.fromhex(args[0].replace(" ", ""))
    if len(cmd) != 3:
        raise SystemExit("OWI 协议必须正好 3 字节，你给了 %d 字节" % len(cmd))
    arm = Arm()
    try:
        if not arm.connect():
            return 1
        m, rc = arm.send(cmd)
        print("已发 %s  via %s  rc=%s  （%s）"
              % (cmd.hex(" ").upper(), m, rc, describe(cmd)))
        return 0
    finally:
        arm.close()


def cmd_test(_a):
    """安全自检：只动夹爪和灯。"""
    need_yes("test")
    arm = Arm()
    try:
        if not arm.connect():
            return 1
        print("传输方式自动探测中…")
        arm.light(True)
        print("✓ 灯开了吗？（爪子里那颗）")
        time.sleep(1.0)
        arm.light(False)
        time.sleep(0.5)
        print("→ 夹爪夹一下 300 ms")
        arm.act("gripper", 2, 300)
        time.sleep(0.5)
        print("→ 夹爪松一下 300 ms")
        arm.act("gripper", 1, 300)
        print("✓ 如果灯亮了、夹爪动了，说明协议对了。传输方式：%s" % TRANSPORT_CACHE)
        return 0
    finally:
        arm.close()


# ──────────────────────────────────────────────────────────────
# 图形界面
# ──────────────────────────────────────────────────────────────

def cmd_gui(_a):
    import tkinter as tk
    from tkinter import ttk, scrolledtext

    BG, FG, ACC = "#0f1317", "#d6dee6", "#4fa3d1"
    root = tk.Tk()
    root.title("Cebek C-9895.2 / OWI-535 机械臂控制台")
    root.geometry("820x620")
    root.configure(bg=BG)

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    for name, kw in (("TFrame", {"background": BG}),
                     ("TLabel", {"background": BG, "foreground": FG}),
                     ("TLabelframe", {"background": BG, "foreground": ACC}),
                     ("TLabelframe.Label", {"background": BG, "foreground": ACC}),
                     ("TCheckbutton", {"background": BG, "foreground": FG})):
        style.configure(name, **kw)

    arm = Arm(verbose=False)
    connected = {"ok": False}
    counters = {j: 0 for j in JOINTS}

    top = ttk.Frame(root)
    top.pack(fill="x", padx=12, pady=(10, 4))
    status = ttk.Label(top, text="设备：未连接", font=("DejaVu Sans", 11, "bold"))
    status.pack(side="left")
    meth = ttk.Label(top, text="", foreground="#e0a040")
    meth.pack(side="right")

    log = scrolledtext.ScrolledText(root, height=9, bg="#080b0e", fg="#9fc4dc",
                                    insertbackground=FG, font=("DejaVu Sans Mono", 9))
    log.pack(side="bottom", fill="both", expand=False, padx=12, pady=(4, 10))

    def say(m):
        log.insert("end", time.strftime("[%H:%M:%S] ") + str(m) + "\n")
        log.see("end")

    # 时长
    tf = ttk.LabelFrame(root, text="点按动作的时长（按住按钮则不受此限）")
    tf.pack(fill="x", padx=12, pady=4)
    ms = tk.IntVar(value=250)
    lbl = ttk.Label(tf, text="250 ms", width=9)
    ttk.Scale(tf, from_=20, to=MAX_MS, orient="horizontal", variable=ms,
              command=lambda _=None: lbl.config(text="%d ms" % ms.get())
              ).pack(side="left", fill="x", expand=True, padx=8, pady=6)
    lbl.pack(side="right", padx=8)

    # 关节行
    jf = ttk.LabelFrame(root, text="关节（按住 = 一直动，松开 = 立刻停）")
    jf.pack(fill="x", padx=12, pady=4)

    light_var = tk.BooleanVar(value=False)

    def send_cmd(cmd):
        if not connected["ok"]:
            say("✗ 未连接，先点「连接」")
            return False
        try:
            m, _rc = arm.send(cmd)
            meth.config(text="传输：%s" % m)
            return True
        except Exception as e:
            say("✗ 发送失败：%r" % e)
            return False

    def begin(joint, action):
        cmd = encode_one(joint, action, light=1 if light_var.get() else 0)
        if send_cmd(cmd):
            say("%s  %s" % (cmd.hex(" ").upper(), describe(cmd)))

    def end(_e=None):
        send_cmd(STOP)

    rows = {}
    for j, spec in JOINTS.items():
        r = ttk.Frame(jf)
        r.pack(fill="x", padx=6, pady=2)
        ttk.Label(r, text=spec["cn"], width=9).pack(side="left")
        for label, act in ((spec["pos"].split("/")[0], 1), (spec["pos"].split("/")[1], 2)):
            b = ttk.Button(r, text=label, width=7)
            b.pack(side="left", padx=2)
            b.bind("<ButtonPress-1>", lambda e, jj=j, aa=act: begin(jj, aa))
            b.bind("<ButtonRelease-1>", end)
        b = ttk.Button(r, text="点头按 %dms" % 250, width=14,
                       command=lambda jj=j: step(jj))
        b.pack(side="left", padx=6)
        cnt = ttk.Label(r, text="累计 0.0 s（估算）", width=22, foreground="#c89040")
        cnt.pack(side="left", padx=8)
        rows[j] = cnt

    def step(joint):
        if not connected["ok"]:
            say("✗ 未连接")
            return
        d = 1
        t0 = time.time()
        begin(joint, d)
        root.after(int(ms.get()), lambda: (end(), finish(joint, t0)))

    def finish(joint, t0):
        elapsed = (time.time() - t0) * 1000.0
        counters[joint] += elapsed
        rows[joint].config(text="累计 %.1f s（估算）" % (counters[joint] / 1000.0))

    # 灯 + 底部
    bot = ttk.Frame(root)
    bot.pack(fill="x", padx=12, pady=6)

    def toggle_light():
        if not connected["ok"]:
            say("✗ 未连接")
            return
        cmd = encode(light=1 if light_var.get() else 0)
        if send_cmd(cmd):
            say("灯 %s" % ("开" if light_var.get() else "关"))

    ttk.Checkbutton(bot, text="爪内 LED（Search Light）",
                    variable=light_var, command=toggle_light).pack(side="left")

    def do_connect():
        try:
            ok = arm.connect()
            if ok:
                dd = arm.info["dd"]
                status.config(text="设备：%04X:%04X 已连接" % (dd.idVendor, dd.idProduct),
                              foreground="#5fd08a")
                connected["ok"] = True
                say("✓ 已连接 %04X:%04X  OUT=%s IN=%s"
                    % (dd.idVendor, dd.idProduct,
                       "0x%02X" % arm.ep_out if arm.ep_out else "无",
                       "0x%02X" % arm.ep_in if arm.ep_in else "无"))
            else:
                status.config(text="设备：未找到", foreground="#e05555")
                say("✗ 没找到 —— USB 插了吗？BKR 6V 接了吗？J7 SW 到 ON 了吗？")
        except SystemExit as e:
            status.config(text="设备：权限不足", foreground="#e05555")
            say(str(e))
        except Exception as e:
            say("✗ %r" % e)

    ttk.Button(bot, text="连接 / 重新枚举", command=do_connect).pack(side="left", padx=6)
    ttk.Button(bot, text="清空日志",
               command=lambda: log.delete("1.0", "end")).pack(side="left", padx=6)

    bigstop = tk.Button(bot, text="■ 全部停止", bg="#a02020", fg="white",
                        activebackground="#d03030", font=("DejaVu Sans", 12, "bold"),
                        command=lambda: (send_cmd(STOP), say("已发停止帧")))
    bigstop.pack(side="right", padx=6)

    def on_close():
        try:
            arm.close()
        finally:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    say("就绪。协议：OWI-535 三字节位打包。")
    say("⚠ 这台臂没有任何位置反馈 —— 「累计秒数」是命令累加，不是实测位置。")
    say("⚠ 断电或程序崩掉时臂会保持最后一条命令；本程序在关闭窗口时会发停止帧。")
    do_connect()
    root.mainloop()
    return 0


# ──────────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────────

COMMANDS = {
    "info": cmd_info,
    "gui": cmd_gui,
    "test": cmd_test,
    "move": cmd_move,
    "light": cmd_light,
    "stop": cmd_stop,
    "raw": cmd_raw,
}


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    name = argv[1]
    if name not in COMMANDS:
        print("未知命令：%s\n可用：%s" % (name, ", ".join(COMMANDS)))
        return 1
    return COMMANDS[name](argv[2:]) or 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv) or 0)
    except KeyboardInterrupt:
        print("\n已中止。若臂还在动，跑一次：python3 cebek.py stop")
        sys.exit(130)
