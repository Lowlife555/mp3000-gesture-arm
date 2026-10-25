# Raspberry Pi Host Software

Three programs that drive the arm from a Raspberry Pi. Python standard library only — no `pyusb`,
no `pyserial`, no virtualenv.

| Program | What it is |
|---|---|
| `cebek.py` | the libusb layer (via `ctypes`) plus a command-line interface |
| `cebek_bridge.py` | serial ↔ USB bridge, for running the arm from the STM32 console |
| `cebek_oneclick.py` | a GUI built on `cebek.py`: double-click, it connects itself |

## Install

Copy this directory to the Pi, for example `~/Desktop/CebekArm/`, then:

```
sudo ./授权USB访问.sh          # one udev rule for 1267:0000; asks for your password once
```

Linux gives write access to `/dev/bus/usb/*` only to root. The script installs a udev rule so your
normal user can open the arm. **Unplug and replug the arm afterwards** for the rule to apply.

Then confirm the device is there. This is read-only — nothing moves:

```
python3 cebek.py info
```

You should see `1267:0000` and its endpoint table.

## First run

Put the arm somewhere clear, gripper pointing at nothing, hands away. Then:

```
python3 cebek.py test --yes
```

It does two things only: light on, light off, then open and close the gripper for 300 ms each.
**Light on and gripper moving means the protocol is correct.**

Then start the GUI:

```
python3 cebek_oneclick.py
```

or double-click `机械臂控制台.desktop`. Holding a button moves the joint and releasing stops it;
the timed buttons run one bounded move; the red button is an immediate stop. The GUI retries the
connection on its own if the arm is unplugged and replugged, and when the window is closed it sends
a stop frame.

`python3 cebek_oneclick.py --selftest` runs the same check as `cebek.py test` without showing the
window.

## Command reference

```
python3 cebek.py info                        # enumerate the device (read-only)
python3 cebek.py test --yes                  # light + gripper self-check
python3 cebek.py move shoulder up 300 --yes  # shoulder up for 300 ms
python3 cebek.py move base cw 500 --yes      # base clockwise for 500 ms
python3 cebek.py light on                    # gripper light on
python3 cebek.py stop                        # stop now
python3 cebek.py raw 00C000                  # send three raw bytes
```

Joints: `shoulder` / `elbow` / `wrist` / `gripper` / `base`, also accepted as `m1`–`m5` or the
Chinese names `肩部` / `肘部` / `腕部` / `夹爪` / `底座`.

Directions: `up|down` for shoulder, elbow, wrist; `cw|ccw` for the base; `open|close` for the
gripper.

## Serial bridge (for the STM32 console)

`cebek_bridge.py` reads ASCII lines from a serial port and forwards each one to the arm as a
three-byte USB command. It also runs a watchdog: if no new command arrives for 1 500 ms it sends
`00 00 00` itself.

That watchdog is not optional. **The arm keeps moving after a command until something replaces it**,
so a dead STM32, a loose UART cable or a stuck program all need something else to brake.

```
STM32 (USART2, PA2/PA3) ──ST-LINK virtual COM──▶ Pi /dev/ttyACM0
                                                    │
                                                    ▼
                                            control transfer
                                                    │
                                                    ▼
                                              arm interface board
```

### Line protocol

| Direction | Message |
|---|---|
| STM32 → Pi | `ARM <b0> <b1> <b2>` — three hex bytes, e.g. `ARM 41 00 00` |
| STM32 → Pi | `PING` — heartbeat |
| STM32 → Pi | `NOP` — refresh the watchdog only |
| STM32 → Pi | `STOP` — brake now |
| Pi → STM32 | `OK` / `PONG` / `ERR <reason>` / `TMO` (watchdog fired) |

### Usage

```
python3 cebek_bridge.py --port /dev/ttyACM0 -v      # driven by the STM32
python3 cebek_bridge.py --stdio -v                  # driven from stdin, no STM32 needed
python3 cebek_bridge.py --stdio --no-usb            # parse only, never opens the arm
```

Driven by the real hardware, these have been confirmed: `PING` → `PONG`, `ARM 00 00 00` → every
joint stops, `ARM 00 00 01` → light on and **stays on** until `STOP`. The last one is the direct
proof of the latching behaviour the whole safety design rests on.

## Why there is no pip install

`cebek.py` uses only `ctypes` and calls the `libusb-1.0.so.0` already present on the system.

- Debian 13 enforces PEP 668, so `pip install` is refused outside a virtualenv. This approach is
  unaffected.
- No virtualenv, no network access, no root at runtime.
- One file copy runs on any Linux with libusb installed.

## Safety notes

1. **There is no position feedback.** The accumulated seconds shown in the GUI are a sum of
   commanded durations, not a measured position. It drifts. Do not read it as an angle.
2. **3 000 ms is the hard limit** for a single move, written into the code to catch a stuck key.
3. **The program sends a stop frame on abnormal exit** (in a `finally` block), but if you power off
   the Pi or pull the USB cable, the arm keeps executing its last command until you cut power.
4. **Limits are protected only by the gears slipping.** First moves should be 100–200 ms.
5. **Power the arm from `BKR`,** never from the Pi's USB port.

## Limitations

- The GUI is syntax-checked but has not been run on the Pi. The libusb layer and the serial bridge
  underneath it both have.
- Gripper polarity may be reversed on a rebadged unit; `cebek.py test` settles it.
- No per-joint speed data exists; it varies with load. Calibration must be measured.

## References

- [owi535py — Message Rules](https://github.com/XinArkh/owi535py/blob/master/docs/rules.md)
- [flaviomauro/owi535-robotic-arm-with-python](https://github.com/flaviomauro/owi535-robotic-arm-with-python)
- [alexsigaras/OWI535-RoboticArm](https://github.com/alexsigaras/OWI535-RoboticArm) (C#)

---

# 树莓派侧主机软件

三个在树莓派上驱动机械臂的程序。只用 Python 标准库 —— 不需要 `pyusb`、不需要 `pyserial`、
不需要虚拟环境。

| 程序 | 是什么 |
|---|---|
| `cebek.py` | libusb 层（经 `ctypes` 调用）加一个命令行界面 |
| `cebek_bridge.py` | 串口 ↔ USB 桥，给 STM32 操作台驱动机械臂用 |
| `cebek_oneclick.py` | 建立在 `cebek.py` 之上的图形界面：双击、自己连上 |

## 安装

把这个目录拷到树莓派上，例如 `~/Desktop/CebekArm/`，然后：

```
sudo ./授权USB访问.sh          # 为 1267:0000 装一条 udev 规则，要输一次密码
```

Linux 默认只允许 root 写 `/dev/bus/usb/*`。这个脚本装一条 udev 规则，让你以普通用户就能打开
机械臂。**装完之后把机械臂拔下再插上**，规则才会生效。

然后确认设备在。这一步只读，什么都不会动：

```
python3 cebek.py info
```

应该看到 `1267:0000` 和它的端点表。

## 第一次跑

把机械臂放在空旷处，爪子朝外，手离开。然后：

```
python3 cebek.py test --yes
```

它只做两件事：开灯、关灯，然后夹爪开合各 300 ms。**灯亮了、夹爪动了，就说明协议对了。**

然后启动图形界面：

```
python3 cebek_oneclick.py
```

或者双击 `机械臂控制台.desktop`。按住按钮关节就动，松开立刻停；定时按钮只动一次有限时长；
红色按钮是立即停止。机械臂被拔掉再插回来时，界面自己会重连；关窗口时会发一帧停止。

`python3 cebek_oneclick.py --selftest` 做和 `cebek.py test` 一样的检查，但不显示窗口。

## 命令速查

```
python3 cebek.py info                        # 枚举设备（只读）
python3 cebek.py test --yes                  # 灯 + 夹爪自检
python3 cebek.py move shoulder up 300 --yes  # 肩部向上 300 ms
python3 cebek.py move base cw 500 --yes      # 底座顺时针 500 ms
python3 cebek.py light on                    # 爪内灯开
python3 cebek.py stop                        # 立刻停
python3 cebek.py raw 00C000                  # 直接发三个字节
```

关节名：`shoulder` / `elbow` / `wrist` / `gripper` / `base`，也可以写 `m1`–`m5`，
或中文 `肩部` / `肘部` / `腕部` / `夹爪` / `底座`。

方向：肩、肘、腕用 `up|down`；底座用 `cw|ccw`；夹爪用 `open|close`。

## 串口桥（给 STM32 操作台用）

`cebek_bridge.py` 从串口读 ASCII 行，逐条转成三字节 USB 指令发给机械臂。它同时跑一个看门狗：
1 500 ms 内没有新指令，就自己发 `00 00 00`。

这个看门狗不是可选项。**机械臂收到一条指令后会一直动，直到被下一条替换**，
所以 STM32 挂了、UART 线松了、程序卡死，都必须有别人来踩刹车。

```
STM32 (USART2, PA2/PA3) ──ST-LINK 虚拟串口──▶ 树莓派 /dev/ttyACM0
                                                    │
                                                    ▼
                                            控制传输
                                                    │
                                                    ▼
                                              机械臂接口板
```

### 线协议

| 方向 | 内容 |
|---|---|
| STM32 → Pi | `ARM <b0> <b1> <b2>` —— 三个十六进制字节，如 `ARM 41 00 00` |
| STM32 → Pi | `PING` —— 心跳 |
| STM32 → Pi | `NOP` —— 只刷新看门狗 |
| STM32 → Pi | `STOP` —— 立刻刹车 |
| Pi → STM32 | `OK` / `PONG` / `ERR <原因>` / `TMO`（看门狗触发） |

### 用法

```
python3 cebek_bridge.py --port /dev/ttyACM0 -v      # 由 STM32 驱动
python3 cebek_bridge.py --stdio -v                  # 从标准输入驱动，不用 STM32
python3 cebek_bridge.py --stdio --no-usb            # 只解析协议，根本不打开机械臂
```

在真实硬件上已经确认：`PING` → `PONG`、`ARM 00 00 00` → 所有关节停、`ARM 00 00 01` → 灯亮并且
**一直亮到 `STOP`**。最后这一条直接证明了整套安全设计所依赖的锁存语义。

## 为什么不用 pip 装东西

`cebek.py` 只用 `ctypes`，调用系统里已有的 `libusb-1.0.so.0`。

- Debian 13 执行 PEP 668，虚拟环境外 `pip install` 会被拒。本方案完全不受影响。
- 运行时不需要虚拟环境、不需要联网、不需要 root。
- 一个文件拷走就能在装了 libusb 的任何 Linux 上跑。

## 安全提醒

1. **没有任何位置反馈。** 界面上显示的累计秒数是命令时长之和，不是实测位置，会漂移。
   **别把它当角度读。**
2. **单次动作硬上限 3 000 ms**，写在代码里防手滑。
3. **程序异常退出时会发停止帧**（在 `finally` 里），但如果你关掉树莓派或拔掉 USB，
   机械臂会保持最后一条指令直到断电。
4. **撞限位只有齿轮打滑这一层保护。** 第一次试动作请从 100–200 ms 开始。
5. **机械臂从 `BKR` 取电**，绝不要从树莓派的 USB 口取。

## 限制

- 图形界面只过了语法检查，没在树莓派上跑过。它下面的 libusb 层和串口桥都在实机跑过。
- 贴牌版本的夹爪极性可能接反；跑一次 `cebek.py test` 就能确定。
- 没有任何关节转速数据，且随负载变化。要标定必须实测。

## 参考

- [owi535py —— Message Rules](https://github.com/XinArkh/owi535py/blob/master/docs/rules.md)
- [flaviomauro/owi535-robotic-arm-with-python](https://github.com/flaviomauro/owi535-robotic-arm-with-python)
- [alexsigaras/OWI535-RoboticArm](https://github.com/alexsigaras/OWI535-RoboticArm)（C#）
