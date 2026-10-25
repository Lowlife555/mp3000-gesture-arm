#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cebek_oneclick.py — Cebek C-9895.2 / OWI-535 机械臂 · 点开即用控制台
=====================================================================

上一版要先在终端里敲命令、还要单独确认和机械臂"配对"过才能动。
这一版把那些步骤全部收进程序里：

  · 启动即自动搜索机械臂，找到就连上，不用任何命令行参数
  · 拔掉再插上会自动重连（不用重启程序）
  · USB 权限不足时，屏幕上直接给出那一行需要执行的确切命令
  · 关窗口时自动发 00 00 00，臂不会带着最后一条命令跑掉

三种操作方式
------------
1. **按住即动**：把某个关节的「正转 / 反转」按钮按住，松开立刻停。
   这是最符合直觉的用法，也是原厂的程序模式在做的事。
2. **定时点动**：填一个毫秒数，选关节和方向，点「点动」——
   动那么久就停。适合做重复实验。
3. **全部停止**：屏幕下方那一大条，任何情况下按下去都立刻发 00 00 00。

安全说明（很重要）
------------------
这台臂**没有任何位置反馈**，也没有限位开关。它"发一条命令就一直转"，
靠齿轮箱打滑来限制行程。所以：

  · 单次动作硬上限 3000 ms，到点程序自己发停止帧（按住模式同样受限）
  · 程序退出 / 关窗口 / 拔 USB 前都会发 00 00 00
  · **但如果你直接断电或者 SSH 断掉，臂会保持最后的动作** —— 因为
    命令是锁存在接口板上的。所以离开时请先按「全部停止」。
  · ⚠️ 屏幕上所有时间都是"命令累计"，不是角度。没有反馈信号，
    就不可能知道它现在指着哪。

用法
----
    python3 cebek_oneclick.py            # 图形界面（桌面双击用这个）
    python3 cebek_oneclick.py --selftest # 不开窗口，自检 USB 与协议
"""

import os
import sys
import time

# ── 协议常量（已在本机实测确认）──────────────────────────────
VID = 0x1267
PID = 0x0000

# 关节名 → (落在第几个字节, 左移几位)
JOINT_DEF = {
    "gripper":  (0, 0),
    "wrist":    (0, 2),
    "elbow":    (0, 4),
    "shoulder": (0, 6),
    "base":     (1, 0),
}

JOINT_CN = {
    "gripper":  "夹爪",
    "wrist":    "腕部",
    "elbow":    "肘部",
    "shoulder": "肩部",
    "base":     "底座",
}

DIR_POS = 1     # 正转（对夹爪是"张开"）
DIR_NEG = 2     # 反转（对夹爪是"闭合"）
STOP = b"\x00\x00\x00"

MAX_MS = 3000           # 单次动作硬上限
RECONNECT_POLL_MS = 800


def make_cmd(joint, direction, light=0):
    """把 (关节, 方向) 编成机械臂能吃的 3 个字节。

    byte0 [1:0]=夹爪 [3:2]=腕 [5:4]=肘 [7:6]=肩   每段 00停/01正/10反
    byte1 [1:0]=底座
    byte2 bit0 = 爪内灯
    """
    b = [0, 0, 0]
    if joint in JOINT_DEF:
        byte, shift = JOINT_DEF[joint]
        b[byte] |= (direction & 0x03) << shift
    b[2] = 1 if light else 0
    return bytes(b)


def describe(cmd):
    names = []
    for j, (byte, shift) in JOINT_DEF.items():
        v = (cmd[byte] >> shift) & 0x03
        if v:
            names.append("%s%s" % (JOINT_CN[j], "+" if v == DIR_POS else "-"))
    if cmd[2] & 1:
        names.append("灯开")
    return "、".join(names) if names else "全部停止"


def import_driver():
    """导入同目录下的 cebek（libusb 封装）。找不到就给出清楚的原因。"""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import cebek
    return cebek


# ──────────────────────────────────────────────────────────────
# 自检模式（不需要图形界面，SSH 里就能跑）
# ──────────────────────────────────────────────────────────────

def selftest():
    print("=" * 60)
    print("Cebek 机械臂 · 自检")
    print("=" * 60)
    try:
        cebek = import_driver()
    except Exception as e:
        print("✗ 导入 cebek 失败：%r" % e)
        print("  确认 cebek.py 和本文件在同一个目录里。")
        return 2

    print("· 驱动模块：%s" % cebek.__file__)

    arm = cebek.Arm(verbose=False)
    print("· 搜索 USB 设备 %04X:%04X ..." % (VID, PID))
    if not arm.connect():
        print("✗ 没找到机械臂。检查：")
        print("  1) USB 线是否插在树莓派上")
        print("  2) lsusb | grep 1267 有没有输出")
        print("  3) 权限：sudo 需要密码时先跑一次 授权USB访问.sh")
        return 3

    info = arm.info or {}
    dd = info.get("dd")
    print("✓ 已连接 %04X:%04X  总线 %s 地址 %s"
          % (dd.idVendor, dd.idProduct,
             info.get("bus", "?"), info.get("addr", "?")))
    print("· 端点：OUT=%s  IN=%s"
          % (("0x%02X" % arm.ep_out) if arm.ep_out else "无",
             ("0x%02X" % arm.ep_in) if arm.ep_in else "无"))
    if arm.ep_out is None:
        print("  （没有 OUT 端点，只能走控制传输 —— 这是预期结果）")

    def send(label, cmd):
        try:
            method, rc = arm.send(cmd)
        except Exception as e:
            print("✗ %s 失败：%r" % (label, e))
            return False
        print("  %-6s → %s   %-14s [%s rc=%d]"
              % (label, cmd.hex(" ").upper(), describe(cmd), method, rc))
        return True

    try:
        print("")
        print("· 1/5  停止帧（上电先确保臂是停着的）")
        if not send("STOP", STOP):
            return 4

        print("· 2/5  爪内灯：亮 0.8 秒，然后关")
        if not send("灯开", b"\x00\x00\x01") or not send("灯关", b"\x00\x00\x00"):
            return 4
        time.sleep(0.3)

        print("· 3/5  夹爪：合 400 ms")
        arm.act("gripper", 2, 400)
        time.sleep(0.4)

        print("· 4/5  夹爪：松 400 ms")
        arm.act("gripper", 1, 400)
        time.sleep(0.3)

        print("· 5/5  收尾停止帧")
        if not send("STOP", STOP):
            return 4
    except Exception as e:
        print("✗ 自检过程中出错：%r" % e)
        return 5
    finally:
        try:
            arm.close()
        except Exception:
            pass

    print("=" * 60)
    print("✓ 自检通过。")
    print("  应该看到：灯亮过又灭，夹爪两个方向各动一次。")
    print("  看到了 = 协议正确，可以进下一步。")
    print("  没看到动作 = 机械臂没通电（6 V 必须接 BKR），或协议不对。")
    print("")
    print("  图形界面（要在 Pi 自己的桌面上跑，SSH 里没有屏幕）：")
    print("    python3 cebek_oneclick.py")
    print("=" * 60)
    return 0


# ──────────────────────────────────────────────────────────────
# 图形界面
# ──────────────────────────────────────────────────────────────

def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except Exception as e:
        print("✗ 这个 Python 没有 tkinter：%r" % e)
        print("  Debian 上装：sudo apt install python3-tk")
        return 2

    if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
        print("✗ 当前没有图形显示（DISPLAY 为空）。")
        print("  这通常是因为你用 SSH 连过来 —— 图形界面要在树莓派的")
        print("  桌面上双击图标运行，或者用 VNC / 接显示器。")
        print("  只想验证硬件是否正常，可以跑：python3 cebek_oneclick.py --selftest")
        return 3

    try:
        cebek = import_driver()
    except Exception as e:
        print("✗ 导入 cebek 失败：%r" % e)
        return 2

    # ── 主窗口 ──
    root = tk.Tk()
    root.title("Cebek 机械臂控制台  ·  C-9895.2 / OWI-535")
    root.configure(bg="#f4f4f6")
    root.minsize(560, 700)

    BG, CARD, INK, DIM = "#f4f4f6", "#ffffff", "#1c1c22", "#6b6b78"
    ACC, ACC2, WARN = "#0a6cff", "#00a06a", "#d92b2b"

    def card(parent, pad=10):
        f = tk.Frame(parent, bg=CARD, highlightthickness=1,
                     highlightbackground="#dcdce4")
        f.pack(fill="x", padx=12, pady=(0, pad))
        return f

    # ── 标题 ──
    head = tk.Frame(root, bg=CARD, highlightthickness=1, highlightbackground="#dcdce4")
    head.pack(fill="x", padx=12, pady=(12, 10))
    tk.Label(head, text="CEBEK 机械臂控制台", font=("DejaVu Sans", 15, "bold"),
             bg=CARD, fg=INK).pack(anchor="w", padx=12, pady=(10, 0))
    link_lbl = tk.Label(head, text="● 正在搜索机械臂…", font=("DejaVu Sans", 11),
                        bg=CARD, fg=WARN, anchor="w")
    link_lbl.pack(anchor="w", padx=12, pady=(2, 2))
    detail_lbl = tk.Label(head, text="插上 USB 后会自动连上，不用重启程序",
                          font=("DejaVu Sans", 9), bg=CARD, fg=DIM, anchor="w",
                          justify="left", wraplength=500)
    detail_lbl.pack(anchor="w", padx=12, pady=(0, 10))

    # ── 按住即动 ──
    c1 = card(root)
    tk.Label(c1, text="按住即动（松手立刻停）", font=("DejaVu Sans", 11, "bold"),
             bg=CARD, fg=INK).pack(anchor="w", padx=12, pady=(10, 6))

    grid = tk.Frame(c1, bg=CARD)
    grid.pack(fill="x", padx=12, pady=(0, 12))
    for col, txt in enumerate(("关节", "反转（←）", "正转（→）")):
        tk.Label(grid, text=txt, font=("DejaVu Sans", 9, "bold"), bg=CARD,
                 fg=DIM).grid(row=0, column=col, sticky="w",
                              padx=(0, 10), pady=(0, 4))

    hold_btns = []
    state = {
        "arm": None,
        "state": "searching",   # searching / ok / noperm / error
        "msg": "",
        "last_cmd": STOP,
        "hold_job": None,       # 按住超时的 after id
        "jog_job": None,        # 定时点动的 after id
        "est": {k: 0.0 for k in JOINT_DEF},
        "move_start": None,
    }

    def now_ms():
        return int(time.time() * 1000)

    # ── 发送（唯一出口，所有按钮都走这里）──
    def send(cmd, why=""):
        arm = state["arm"]
        if arm is None:
            set_state("error", "当前没有连接，指令没有发出")
            return False
        try:
            arm.send(cmd)
        except Exception as e:
            # USB 掉了：丢连接，交给轮询去重连
            drop_connection("USB 发送失败：%r" % e)
            return False
        state["last_cmd"] = cmd
        cmd_lbl.config(text="最近指令：%s   %s" % (cmd.hex(" ").upper(), describe(cmd)))
        if why:
            status_lbl.config(text=why)
        return True

    def stop_all(why="已全部停止"):
        for k in ("hold_job", "jog_job"):
            if state[k]:
                try:
                    root.after_cancel(state[k])
                except Exception:
                    pass
                state[k] = None
        close_move()
        send(STOP, why)

    def close_move():
        """结束一次计时动作，把时长记进累计。"""
        if state["move_start"] is not None:
            j = state.get("move_joint")
            if j in state["est"]:
                state["est"][j] += (now_ms() - state["move_start"]) / 1000.0
            state["move_start"] = None
            state["move_joint"] = None
            refresh_est()

    def refresh_est():
        parts = []
        for j in ("shoulder", "elbow", "wrist", "gripper", "base"):
            v = state["est"][j]
            if v > 0.05:
                parts.append("%s %.1fs" % (JOINT_CN[j], v))
        est_lbl.config(text=("EST 累计（不是角度）：" + ("  ".join(parts) if parts else "—")))

    def begin_hold(joint, direction):
        if state["state"] != "ok":
            return
        close_move()
        send(make_cmd(joint, direction), "动作中：%s" % JOINT_CN[joint])
        state["move_start"] = now_ms()
        state["move_joint"] = joint
        # 硬上限：到 MAX_MS 自动停，必须松手才能再来
        state["hold_job"] = root.after(MAX_MS, lambda: (
            stop_all("已到 3 秒硬上限，强制停止（请松手）")))

    def end_hold():
        if state["hold_job"]:
            try:
                root.after_cancel(state["hold_job"])
            except Exception:
                pass
            state["hold_job"] = None
        if state["move_start"] is not None:
            stop_all("已停止")

    row = 1
    for joint in ("gripper", "wrist", "elbow", "shoulder", "base"):
        tk.Label(grid, text=JOINT_CN[joint], font=("DejaVu Sans", 11), bg=CARD,
                 fg=INK).grid(row=row, column=0, sticky="w", pady=3)
        for col, d in ((1, DIR_NEG), (2, DIR_POS)):
            b = tk.Button(grid, text=("反转" if d == DIR_NEG else "正转"),
                          font=("DejaVu Sans", 11), width=9, height=1,
                          bg="#eef3ff", fg=INK, activebackground=ACC,
                          relief="raised", bd=1)
            b.grid(row=row, column=col, sticky="we", padx=3, pady=3)
            b.bind("<ButtonPress-1>", lambda e, j=joint, dd=d: begin_hold(j, dd))
            b.bind("<ButtonRelease-1>", lambda e: end_hold())
            hold_btns.append(b)
        row += 1

    # ── 定时点动 ──
    c2 = card(root)
    tk.Label(c2, text="定时点动（动这么久就停）", font=("DejaVu Sans", 11, "bold"),
             bg=CARD, fg=INK).pack(anchor="w", padx=12, pady=(10, 6))
    jr = tk.Frame(c2, bg=CARD)
    jr.pack(fill="x", padx=12, pady=(0, 12))

    jvar = tk.StringVar(value="shoulder")
    dvar = tk.StringVar(value="正转")
    mvar = tk.IntVar(value=300)

    tk.Label(jr, text="关节", font=("DejaVu Sans", 9), bg=CARD, fg=DIM).grid(row=0, column=0)
    cb = ttk.Combobox(jr, textvariable=jvar, width=8, state="readonly",
                      values=list(JOINT_DEF.keys()))
    cb.grid(row=1, column=0, padx=(0, 8))

    tk.Label(jr, text="方向", font=("DejaVu Sans", 9), bg=CARD, fg=DIM).grid(row=0, column=1)
    cb2 = ttk.Combobox(jr, textvariable=dvar, width=6, state="readonly",
                       values=["正转", "反转"])
    cb2.grid(row=1, column=1, padx=(0, 8))

    tk.Label(jr, text="毫秒", font=("DejaVu Sans", 9), bg=CARD, fg=DIM).grid(row=0, column=2)
    sp = tk.Spinbox(jr, from_=50, to=MAX_MS, increment=50, textvariable=mvar,
                    width=7)
    sp.grid(row=1, column=2, padx=(0, 8))

    def do_jog():
        if state["state"] != "ok":
            set_state("error", "当前没有连接，指令没有发出")
            return
        joint = jvar.get()
        direction = DIR_POS if dvar.get() == "正转" else DIR_NEG
        try:
            ms = int(mvar.get())
        except Exception:
            ms = 300
        ms = max(50, min(MAX_MS, ms))
        mvar.set(ms)

        close_move()
        if state["jog_job"]:
            root.after_cancel(state["jog_job"])
        send(make_cmd(joint, direction), "点动 %s %d ms" % (JOINT_CN[joint], ms))
        state["move_start"] = now_ms()
        state["move_joint"] = joint
        state["jog_job"] = root.after(ms, lambda: (
            stop_all("点动结束（%d ms）" % ms)))

    tk.Button(jr, text="点 动", font=("DejaVu Sans", 11, "bold"), width=8,
              bg=ACC, fg="white", activebackground="#0854c8",
              relief="flat", command=do_jog).grid(row=1, column=3, padx=(4, 0))

    # ── 灯 + 全部停止 ──
    c3 = card(root)
    lr = tk.Frame(c3, bg=CARD)
    lr.pack(fill="x", padx=12, pady=(10, 10))
    light_on = {"v": False}

    def toggle_light():
        light_on["v"] = not light_on["v"]
        send(make_cmd(None, 0, light=1 if light_on["v"] else 0),
             "爪内灯：" + ("开" if light_on["v"] else "关"))
        light_btn.config(text=("爪内灯：开" if light_on["v"] else "爪内灯：关"),
                         bg=("#fff3cd" if light_on["v"] else "#eeeeee"))

    light_btn = tk.Button(lr, text="爪内灯：关", font=("DejaVu Sans", 11), width=14,
                          bg="#eeeeee", fg=INK, relief="flat", command=toggle_light)
    light_btn.pack(side="left")

    stop_btn = tk.Button(c3, text="■   全 部 停 止", font=("DejaVu Sans", 17, "bold"),
                         bg=WARN, fg="white", activebackground="#a81f1f",
                         relief="flat", height=2,
                         command=lambda: stop_all("已全部停止"))
    stop_btn.pack(fill="x", padx=12, pady=(0, 12))

    # ── 状态条 ──
    c4 = card(root, pad=0)
    status_lbl = tk.Label(c4, text="就绪", font=("DejaVu Sans", 10), bg=CARD,
                          fg=INK, anchor="w")
    status_lbl.pack(fill="x", padx=12, pady=(10, 2))
    cmd_lbl = tk.Label(c4, text="最近指令：00 00 00   全部停止",
                       font=("DejaVu Sans Mono", 9), bg=CARD, fg=DIM, anchor="w")
    cmd_lbl.pack(fill="x", padx=12, pady=(0, 2))
    est_lbl = tk.Label(c4, text="EST 累计（不是角度）：—", font=("DejaVu Sans", 9),
                       bg=CARD, fg=DIM, anchor="w")
    est_lbl.pack(fill="x", padx=12, pady=(0, 10))
    tk.Label(root, text="提示：这台臂没有位置反馈，屏幕上只有“命令累计”，没有“角度”。\n"
                        "离开前请先按“全部停止”——它是锁存命令，断电前不会自己停。",
             font=("DejaVu Sans", 8), bg=BG, fg=DIM, justify="left"
             ).pack(fill="x", padx=14, pady=(2, 10))

    # ── 连接管理 ──
    def set_state(st, msg):
        state["state"] = st
        state["msg"] = msg
        if st == "ok":
            link_lbl.config(text="● 已连接  %04X:%04X" % (VID, PID), fg=ACC2)
        elif st == "searching":
            link_lbl.config(text="● 正在搜索机械臂…", fg=WARN)
        elif st == "noperm":
            link_lbl.config(text="● 找到设备但没权限", fg=WARN)
        else:
            link_lbl.config(text="● 未连接", fg=WARN)
        if msg:
            detail_lbl.config(text=msg)
        on = (st == "ok")
        for b in hold_btns:
            b.config(state=("normal" if on else "disabled"))

    def drop_connection(reason):
        arm = state["arm"]
        state["arm"] = None
        if arm is not None:
            try:
                arm.close()
            except Exception:
                pass
        close_move()
        set_state("searching", "%s\n正在自动重连…" % reason)

    def try_connect():
        if state["arm"] is not None:
            # 还连着的，做一次轻量探活
            return
        arm = cebek.Arm(verbose=False)
        if arm.connect():
            state["arm"] = arm
            dd = arm.info["dd"]
            set_state("ok", "设备 %04X:%04X   总线 %s 地址 %s\n"
                            "这条命令是锁存的：发一条就一直动，直到下一条。"
                            % (dd.idVendor, dd.idProduct,
                               arm.info.get("bus", "?"), arm.info.get("addr", "?")))
            # 连上第一件事：确保臂是停着的
            try:
                arm.send(STOP)
            except Exception as e:
                drop_connection("连上但发送失败：%r" % e)
                return
            return
        # 连不上：区分"找不到"和"没权限"
        msg = getattr(arm, "last_error", "") or ""
        try:
            devs = cebek.LibUSB().list_devices() if hasattr(cebek, "LibUSB") else []
        except Exception:
            devs = []
        found = any(d.get("vid") == VID and d.get("pid") == PID for d in devs)
        if found:
            set_state("noperm",
                      "系统认到了这块设备，但当前用户没有读写权限。\n"
                      "在树莓派上执行一次下面这行，然后拔插一次 USB：\n\n"
                      "    sudo cp ~/Desktop/CebekArm/99-cebek-arm.rules "
                      "/etc/udev/rules.d/\n"
                      "    sudo udevadm control --reload && sudo udevadm trigger\n\n"
                      "（也就是桌面上那个「授权USB访问.sh」）")
        else:
            set_state("searching", "没找到机械臂。检查 USB 线是否插在树莓派上。\n"
                                   "会自动重试，插上就会连上，不用重启程序。")

    def poll():
        try_connect()
        root.after(RECONNECT_POLL_MS, poll)

    def on_close():
        try:
            stop_all("程序退出")
        finally:
            if state["arm"] is not None:
                try:
                    state["arm"].close()
                except Exception:
                    pass
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # 允许用方向键/Esc 干点有用的事
    root.bind("<Escape>", lambda e: stop_all("已全部停止（Esc）"))

    refresh_est()
    try_connect()
    root.after(RECONNECT_POLL_MS, poll)
    root.mainloop()
    return 0


def main(argv):
    if "--selftest" in argv or "-t" in argv:
        return selftest()
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    return run_gui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
