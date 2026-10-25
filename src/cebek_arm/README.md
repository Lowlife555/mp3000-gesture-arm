# Cebek C-9895.2 Robot Arm — Control Stack

Everything needed to move a Cebek C-9895.2 arm from your own code: the USB protocol, a
double-click console for the Raspberry Pi, and an optional STM32 handheld console.

The arm has no SDK, no serial protocol and no documentation for the wire format — the vendor
ships a Windows application and nothing else. This directory replaces that application.

## The arm

The C-9895.2 is a rebadged **OWI Robotic Arm Edge (OWI-535)**. The evidence:

| | |
|---|---|
| USB ID | `1267:0000` — vendor `0x1267` is OWI Inc. |
| Mechanism | Five DC gearmotors plus a light in the gripper; **no position feedback anywhere** |
| Rated motion | Base 270°, shoulder 180°, elbow 300°, wrist 120°, gripper opening 45 mm |
| Vendor software | "Basic" mode = hold to move, "Program" mode = pick a motor and a duration — the same layout as OWI's own software |

So the timing in "Program" mode is not a feature of the arm. Everything below follows from that.

## The protocol

Three bytes, bit-packed, sent in one USB control transfer.

| Byte | Bits | Joint | `00` | `01` | `10` |
|---|---|---|---|---|---|
| 0 | 1:0 | Gripper | stop | close | open |
| 0 | 3:2 | Wrist | stop | up | down |
| 0 | 5:4 | Elbow | stop | up | down |
| 0 | 7:6 | Shoulder | stop | up | down |
| 1 | 1:0 | Base | stop | clockwise | counter-clockwise |
| 2 | 0 | Gripper light | off | on | — |

```
bmRequestType = 0x40    bRequest = 0x06    wValue = 0x0100    wIndex = 0
data          = 3 bytes
```

**Commands latch.** A command keeps the joint running until the next command arrives. `00 00 00`
is the only stop. Real motion timing therefore has to happen on the host:

```
send command -> host sleeps N ms -> send 00 00 00
```

That one property explains the arm's other oddities: the 100 g lifting figure, the ratcheting
noise when it hits a limit (gears slipping, not a sensor), and why it has no idea where it is
after a power cycle.

**Control transfer is the only transport.** The device enumerates as USB Low Speed with one
`0x81` interrupt IN endpoint (8-byte packets) and **no OUT endpoint at all**. A bulk OUT write is
not awkward here, it is impossible — the endpoint does not exist. An earlier version of this
document assumed both were possible and probed for a bulk path; that assumption was wrong.

Because of this, something with a USB host controller has to own the arm. The Raspberry Pi does.

## Two ways to drive it

| | Raspberry Pi console | STM32 handheld console |
|---|---|---|
| Where the command is entered | GUI or CLI on the Pi | buttons on the device |
| Who sends the USB transfer | the Pi | the Pi, forwarded over a serial line |
| Runs without a laptop | yes | yes |
| Code | `pi/cebek_oneclick.py` | `stm32/` + `pi/cebek_bridge.py` |

The STM32 is an input device, not a USB host — `stm32/README.md` explains why making it one is
not worth the trouble on this board.

## What's in this directory

```
pi/        Raspberry Pi side — three programs, Python standard library only
             cebek.py            libusb bindings via ctypes, plus a CLI
             cebek_bridge.py     serial ↔ USB bridge with a 1 500 ms watchdog
             cebek_oneclick.py   the double-click GUI
stm32/     STM32L476 console — Keil MDK project, register-level C, no HAL
             CebekArm.uvprojx    open this in Keil
             cmsis/              CMSIS + device headers, vendored
             board_pins.h        every pin, in one file
```

## Getting started

On the Pi, with the arm plugged in:

```
sudo ./pi/授权USB访问.sh         # udev rule for 1267:0000, asks for your password once
python3 pi/cebek.py info        # enumerate the device — read-only, nothing moves
python3 pi/cebek.py test --yes  # light on, light off, gripper open/close for 300 ms each
```

If the light comes on and the gripper moves, the protocol is right and the arm is yours to
command. Then either open `机械臂控制台.desktop`, or from a terminal:

```
python3 pi/cebek_oneclick.py
```

For the STM32 console, plug the arm and the board into separate USB ports on the Pi, then:

```
python3 pi/cebek_bridge.py --port /dev/ttyACM0 -v
```

Full command reference in `pi/README.md`; pinout, button map and line protocol in
`stm32/README.md`.

## Safety

The latching behaviour is the hazard: lose the host while a joint is running and the arm keeps
going until something stops it. Three independent stops are in place:

1. **STM32** — a single commanded motion is cut at 3 000 ms, hard-coded.
2. **STM32** — if the Pi stops answering the heartbeat for 1 500 ms, the console stops and
   refuses to start another motion until the link returns.
3. **Pi** — the bridge sends `00 00 00` if no new command arrives within 1 500 ms.

Layers 2 and 3 cover each other's failure mode: with the Pi gone the STM32 knows and stops; with
the STM32 gone the Pi notices the silence and stops.

Two rules come from the hardware itself:

- **Power the arm from the `BKR` connector.** Never from the Raspberry Pi's USB port — that link
  carries data only, and the motors will brown out the Pi.
- **Start at 100–200 ms.** Hitting a mechanical limit is protected only by the gears slipping.

## Limitations

- No position feedback means no closed loop. The `EST` figure on the STM32 screen is an
  accumulated command duration, not an angle; it drifts and it is not a measurement.
- Gripper polarity (`01` = close or open?) is fixed on an OWI-535, but a rebadged unit could be
  wired either way. `cebek.py test` settles it in one run.
- No published figures for joint speed, and it varies with load. Calibration has to be measured —
  an ArUco marker and a camera is the cheap route.
- The STM32 firmware compiles clean but has not been run on a board yet. The Pi software has been
  exercised on the real arm; the GUI on top of it has not.

## References

The protocol described above matches the community reverse-engineering of the OWI-535:

- [owi535py — Message Rules](https://github.com/XinArkh/owi535py/blob/master/docs/rules.md)
- [flaviomauro/owi535-robotic-arm-with-python](https://github.com/flaviomauro/owi535-robotic-arm-with-python)
- [alexsigaras/OWI535-RoboticArm](https://github.com/alexsigaras/OWI535-RoboticArm) (C#)

No vendor binary, driver or decompiled artefact is included in this directory.

---

# Cebek C-9895.2 机械臂 —— 控制栈

用你自己的代码驱动 Cebek C-9895.2 机械臂所需的一切：USB 协议、树莓派上双击即用的控制台，
以及一个可选的 STM32 手持操作台。

这只臂没有 SDK、没有串口协议，也没有任何关于线上协议的文档 —— 厂商只给了一个 Windows 程序。
本目录就是用来替掉那个程序的。

## 这台臂是什么

C-9895.2 是 **OWI Robotic Arm Edge (OWI-535)** 的贴牌版本。证据：

| | |
|---|---|
| USB ID | `1267:0000` —— 厂商号 `0x1267` 属 OWI Inc. |
| 机械结构 | 5 个直流减速电机，加爪内一盏灯；**全机没有任何位置反馈** |
| 标称行程 | 底座 270°、肩 180°、肘 300°、腕 120°、夹爪开口 45 mm |
| 厂商软件 | "Basic" 模式按住才动，"Program" 模式选电机加时长 —— 与 OWI 官方软件同一套布局 |

所以 "Program" 模式里的计时根本不是机械臂的功能。下面所有设计都从这一条推出来。

## 协议

三个字节，位打包，装在一次 USB 控制传输里。

| 字节 | 位 | 关节 | `00` | `01` | `10` |
|---|---|---|---|---|---|
| 0 | 1:0 | 夹爪 | 停 | 合 | 开 |
| 0 | 3:2 | 腕 | 停 | 上 | 下 |
| 0 | 5:4 | 肘 | 停 | 上 | 下 |
| 0 | 7:6 | 肩 | 停 | 上 | 下 |
| 1 | 1:0 | 底座 | 停 | 顺时针 | 逆时针 |
| 2 | 0 | 爪内灯 | 灭 | 亮 | — |

```
bmRequestType = 0x40    bRequest = 0x06    wValue = 0x0100    wIndex = 0
数据          = 3 字节
```

**指令是锁存的。** 一条指令会让关节一直转，直到下一条指令到达；`00 00 00` 是唯一的停止。
所以真正的"动作时长"必须由主机来做：

```
发指令 -> 主机 sleep N 毫秒 -> 发 00 00 00
```

这一条性质解释了机械臂其他所有古怪之处：标称只有 100 g 起重、撞到限位时"哒哒哒"（那是
齿轮打滑，不是传感器）、以及断电之后完全不知道自己转到哪了。

**控制传输是唯一通路。** 设备枚举为 USB Low Speed，只有一个 `0x81` 中断 IN 端点（8 字节包），
**完全没有 OUT 端点**。bulk OUT 写入在这里不是麻烦，而是不可能 —— 端点根本不存在。
本文件早期版本假设两种都可能、还去探测了 bulk 通路，那个假设是错的。

也正因为如此，必须由带 USB 主机控制器的一方来管这只臂。这个角色是树莓派。

## 两种驱动方式

| | 树莓派控制台 | STM32 手持操作台 |
|---|---|---|
| 指令在哪输入 | 树莓派上的图形界面或命令行 | 设备上的按键 |
| 谁发 USB 传输 | 树莓派 | 树莓派，经串口转发 |
| 不用电脑也能用 | 是 | 是 |
| 代码 | `pi/cebek_oneclick.py` | `stm32/` + `pi/cebek_bridge.py` |

STM32 在这里是输入设备，不是 USB 主机 —— 在这块板上把它做成主机为什么不划算，
见 `stm32/README.md`。

## 目录里有什么

```
pi/        树莓派侧 —— 三个程序，只用 Python 标准库
             cebek.py            ctypes 调 libusb，外加命令行
             cebek_bridge.py     串口 ↔ USB 桥，带 1 500 ms 看门狗
             cebek_oneclick.py   双击即用的图形界面
stm32/     STM32L476 操作台 —— Keil MDK 工程，纯寄存器 C，不用 HAL
             CebekArm.uvprojx    用 Keil 打开这个
             cmsis/              CMSIS 与器件头文件，随工程附带
             board_pins.h        所有引脚集中在这一个文件
```

## 上手

在树莓派上，插好机械臂：

```
sudo ./pi/授权USB访问.sh         # 为 1267:0000 装 udev 规则，要输一次密码
python3 pi/cebek.py info        # 枚举设备 —— 只读，什么都不会动
python3 pi/cebek.py test --yes  # 开灯、关灯、夹爪各开合 300 ms
```

**灯亮了、夹爪动了，就说明协议对上了**，接下来随你指挥。然后双击 `机械臂控制台.desktop`，
或在终端里跑：

```
python3 pi/cebek_oneclick.py
```

要用 STM32 操作台，把机械臂和开发板分别插到树莓派的两个 USB 口，然后：

```
python3 pi/cebek_bridge.py --port /dev/ttyACM0 -v
```

完整命令表在 `pi/README.md`；引脚、按键表和线协议在 `stm32/README.md`。

## 安全

锁存特性就是危险源：关节正转着的时候主机失联，机械臂会一直转下去，直到有什么东西叫停它。
所以有三道独立的刹车：

1. **STM32** —— 单次指令动作到 3 000 ms 强制切断，写死在代码里。
2. **STM32** —— 树莓派 1 500 ms 不回心跳，操作台立即停止，且在链路恢复前拒绝开始新动作。
3. **树莓派** —— 桥程序 1 500 ms 没收到新指令，自己发 `00 00 00`。

第 2 层和第 3 层互为对方的失效场景：树莓派没了，STM32 知道并停下；STM32 没了，
树莓派察觉沉默并停下。

此外，硬件上有两条硬规矩：

- **机械臂从 `BKR` 接口取电。** 绝不能从树莓派的 USB 口取电 —— 那条链路只走数据，
  电机一拉电流就会把树莓派拖垮。
- **第一次试动作从 100–200 ms 开始。** 撞到机械限位只有齿轮打滑这一层保护。

## 限制

- 没有位置反馈就没有闭环。STM32 屏上的 `EST` 是命令累计时长，不是角度；它会漂移，也不是测量值。
- 夹爪极性（`01` 到底是合还是开）在 OWI-535 上是确定的，但贴牌版可能接反。
  跑一次 `cebek.py test` 就能定。
- 关节转速没有公开数据，且随负载变化。要标定必须实测 —— ArUco 标记加相机是便宜的路子。
- STM32 固件编译干净，但还没在板上跑过。树莓派侧软件在实物上验证过，叠在上面的图形界面还没有。

## 参考

下面的协议描述与社区对 OWI-535 的逆向结果一致：

- [owi535py —— Message Rules](https://github.com/XinArkh/owi535py/blob/master/docs/rules.md)
- [flaviomauro/owi535-robotic-arm-with-python](https://github.com/flaviomauro/owi535-robotic-arm-with-python)
- [alexsigaras/OWI535-RoboticArm](https://github.com/alexsigaras/OWI535-RoboticArm)（C#）

本目录不含任何原厂二进制、驱动或反编译产物。
