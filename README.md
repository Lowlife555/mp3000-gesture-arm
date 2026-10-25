# MP3000 — Vision-Guided Robotic Sorting Arm

A UCLan final-year engineering project (MP3000 Engineering Project with Sustainability): a camera
looks at a piece of household waste, a neural network classifies it, and a desktop robot arm picks
it up and drops it into the matching bin.

The project is built and tested in two halves:

- **Perception** — Raspberry Pi 4B, camera, MobileNetV2 classifier. Working.
- **Actuation** — a Cebek C-9895.2 arm driven from an STM32L476 operator console, forwarded over
  USB by the same Raspberry Pi. Manual control works.

The two halves are **not connected yet**. Nothing in this repository turns a classification result
into a pick-and-place motion; that link is the remaining work.

## What works today

| Stage | Runs on | Status |
|---|---|---|
| Classifier training | PC, TensorFlow 2.x / Python 3.13 | MobileNetV2, 6 classes, 2 148 training / 379 held-out images |
| int8 conversion | PC | 20.93 MB → **2.62 MB** (8.00×); accuracy 81.53% → **78.89%** (−2.64 points, n = 379) |
| Inference | Raspberry Pi 4B | **28.8 ms/frame** on the two-thread demo page; 45.0 ms with single-threaded LiteRT |
| Live demo page | Pi, viewed in a browser | 36 held-out images looping, verdict stamped onto each image (green = correct, red = wrong; wrong ones kept deliberately) |
| Arm manual control | Pi → USB | Protocol confirmed on the hardware: gripper and shoulder move, gripper light switches |
| Arm operator console | STM32L476RG + ILI9341 TFT | Builds 0 error / 0 warning; **not yet run on a board** |

## Repository layout

```
src/
  trashnet_trial/     Perception pipeline, numbered in run order:
                        00_split.py → 01_inspect.py → 02_train.py → 03_quantize.py
                        → 04_verify_tflite.py → 05_pi_predict.py → 06_pi_live.py
                        → 07_pi_webcam.py → 08_pi_demo.py → 09_pi_fullval.py
  gesture_trial/      Early three-class proof that the whole chain works (capture → train →
                      live → quantize) on 978 self-collected images. Superseded by
                      trashnet_trial; kept because it is the only place the raw capture
                      step and its notes exist.
  cebek_arm/          Actuation. See src/cebek_arm/README.md for the protocol write-up.
    pi/               Three Python programs, standard library only (no pyusb, no venv):
                        cebek.py           libusb layer via ctypes, plus the old CLI/GUI
                        cebek_bridge.py    USART ↔ USB bridge with a 1 500 ms watchdog
                        cebek_oneclick.py  double-click GUI: auto-connect, auto-reconnect,
                                           press-and-hold jogging, E-STOP
    stm32/            Keil MDK project for the STM32L476 operator console — register-level
                      C, no HAL. CMSIS and the device header are vendored under stm32/cmsis/,
                      so the project needs nothing but the compiler.
docs/                 Dated write-ups: the step-by-step reproduction of the classifier, the
                      Pi page deployment, the Pi disconnection investigation, and the
                      vision-servoing plan for the missing classifier→arm link.
tools/                One-off scripts used while developing. Not part of the runtime.
```

Deliberately **not** committed, and why:

- `data/`, `models/` — the TrashNet copy and every trained weight are reproducible from the
  scripts; the int8 model alone is 2.62 MB and grows with every experiment.
- `hardware/` — the vendor CD, its manual, and photographs of the arm. Third-party material.
- `docs/notes_snapshot_*/`, `docs/emails/` — working notes and draft correspondence, not project output.
- `new/`, `*.hex`, `*.axf`, `*.map` — Keil build output.

## Hardware and toolchain

- **Perception compute:** Raspberry Pi 4B, 8 GB, Raspberry Pi OS Trixie 64-bit, headless;
  `ai-edge-litert` 2.3.0 for inference. The PC side trains in TensorFlow on Python 3.13.
- **Camera:** Raspberry Pi Camera Module v2 (IMX219).
- **Arm:** Cebek C-9895.2. This is a rebadged **OWI Robotic Arm Edge (OWI-535)** — USB ID
  `1267:0000` (`0x1267` is OWI Inc.), five DC gearmotors plus a light in the gripper, no
  position feedback of any kind.
- **Operator console:** STM32L476RGTx (LQFP64) on a custom board, ILI9341 240×320 SPI display,
  four push buttons.
- **Toolchain:** Keil MDK-ARM with ARM Compiler 5.06; the STM32 side is written against the
  register definitions in `stm32/cmsis/` — there is no HAL and no CubeMX project.

## How to run

### 1. Perception pipeline

Training happens on a PC. TrashNet is not included; download it and point `00_split.py` at it.

```
python 00_split.py            # stratified split: 2 148 train / 379 validation
python 02_train.py            # MobileNetV2, float32, writes models/
python 03_quantize.py         # int8 TFLite
python 04_verify_tflite.py    # re-scores the quantised model on the held-out set
```

On the Pi, the same model file plus a camera is enough:

```
python3 06_pi_live.py         # live classification in a window
python3 08_pi_demo.py         # the demo page, http://<pi>:8090/
```

`08_pi_demo.py` serves a plain MJPEG stream from the standard library — no Flask, no PIL
required if the images are pre-encoded. It loops over the held-out set and stamps each verdict
onto the frame so a viewer can see the mistakes, not just the wins.

### 2. Arm console on the Pi

The arm is a USB **device**, so something with a USB host controller has to send it commands.
That is the Pi. Give the Pi permission to open the device once, then run the GUI:

```
sudo ./授权USB访问.sh          # installs the udev rule for 1267:0000
python3 cebek_oneclick.py      # or double-click 机械臂控制台.desktop
```

There is also a smoke test that needs no GUI — it switches the light on and nudges the gripper:

```
python3 cebek.py test --yes
```

`cebek_bridge.py` is the program the STM32 talks to. It reads ASCII lines from a serial port
and forwards each one to the arm as a three-byte USB command, and it sends a stop frame if no
new command arrives for 1 500 ms.

### 3. STM32 operator console

1. Open `src/cebek_arm/stm32/CebekArm.uvprojx` in Keil MDK-ARM.
2. Build. The result is `new/CebekArm.hex` (26 593 bytes) — this directory is gitignored.
3. Flash it. On power-up the screen shows `LINK DOWN` until the Pi answers a heartbeat — that
   is the expected state when the Pi is not connected, not a fault.

Buttons: short press starts a joint moving, long press does the second function of the same
button, so eight functions fit on four keys without menus.

## How it works

### Classifier

MobileNetV2 with a 6-way head, trained on TrashNet (cardboard, glass, metal, paper, plastic,
trash) at 2 148/379 stratified split. Quantised to int8 with a representative dataset drawn
from the training set; the accuracy cost is 2.64 points on the held-out 379, which is within
what this model has to lose before the demo stops looking convincing. The int8 model runs
comfortably inside the Pi's budget: at 28.8 ms/frame there is room for a camera capture and a
servo command in the same 33 ms frame.

### The arm's control protocol

The vendor documents the Windows application, not the wire protocol. This part was recovered
by observation and verified against the hardware:

Three bytes travel in a single HID class control transfer
(`bmRequestType = 0x40`, `bRequest = 0x06`, `wValue = 0x0100`, `wIndex = 0`):

| Byte | Bits | Joint | 00 | 01 | 10 |
|---|---|---|---|---|---|
| 0 | 1:0 | Gripper | stop | close | open |
| 0 | 3:2 | Wrist | stop | up | down |
| 0 | 5:4 | Elbow | stop | up | down |
| 0 | 7:6 | Shoulder | stop | up | down |
| 1 | 1:0 | Base | stop | clockwise | counter-clockwise |
| 2 | 0 | Gripper light | off | on | — |

Two properties of this protocol drive the whole design:

**Commands latch.** A command keeps the joint moving until the next command arrives. `00 00 00`
is the only stop. All timing is therefore the host's responsibility — the arm has no notion of
"move for 300 ms".

**Control transfer is the only transport.** The device enumerates as USB Low Speed with a single
`0x81` interrupt IN endpoint and no OUT endpoint at all, so a bulk OUT write is not merely
awkward, it is impossible. Any host has to use control transfers.

This is why the STM32 cannot drive the arm directly: the L476's USB peripheral can act as a host,
but doing so from a bare-metal project means a full host stack, and the pin pair it needs is
already taken by the display on this board. The Pi does the USB work instead and the STM32 is a
console that talks to it over a serial line.

## Known limitations

- **The two halves are not joined.** There is no `classify → plan → move` code. The arm moves
  when a human presses a button.
- **The arm has no feedback.** No encoders, no limit switches, no current sensing. "Move for
  800 ms" is the only control primitive; whether the gripper actually closed on the object is
  unknown to the software. Repeatability is therefore bounded by battery voltage and load, and
  any calibration has to be done on a bench supply rather than on batteries.
- **The STM32 firmware has been compiled but never executed on a board.** 0 error / 0 warning
  is a compiler result, not a hardware result.
- **`cebek_oneclick.py` has been syntax-checked but never run on a Pi.** The libusb layer and the
  serial bridge underneath it were both exercised on the real hardware; the GUI on top of them
  was written while the Pi was offline.
- **The int8 accuracy figure is one split.** 379 images, single stratified hold-out, no k-fold,
  no per-class error analysis yet.
- **`gesture_trial/` is dead code kept for its notes.** Do not read it as the current pipeline.

## Project

| | |
|---|---|
| Course | UCLan MP3000 Engineering Project with Sustainability (2026–27) |
| Supervisor | Dr Yu Zhou |
| Equipment | Cebek C-9895.2 arm on loan from Dr Carl Berry |
| Technical report | 2027-04-12 |
| Poster and viva | 2027-05-06 |

The classifier, the arm console and the protocol write-up are project output and can be read and
reused. The technical report itself is submitted work and is not in this repository.

---

# MP3000 —— 视觉引导的机械臂分拣系统

英国中央兰开夏大学（UCLan）毕业设计，MP3000 Engineering Project with Sustainability。
摄像头看到一件生活垃圾，神经网络判断它属于哪一类，桌面机械臂把它抓起来放进对应的桶。

项目分两半，分别开发和验证：

- **感知端** —— 树莓派 4B + 摄像头 + MobileNetV2 分类器。已跑通。
- **动作端** —— Cebek C-9895.2 机械臂，由 STM32L476 操作台发指令、树莓派转发到 USB。手动控制已可用。

两半**目前没有接上**。仓库里没有任何"分类结果 → 抓取动作"的代码，那一段是剩下的工作。

## 现在能做到什么

| 环节 | 跑在哪 | 状态 |
|---|---|---|
| 分类器训练 | PC，TensorFlow 2.x / Python 3.13 | MobileNetV2，6 类，2 148 训练 / 379 验证 |
| int8 量化 | PC | 20.93 MB → **2.62 MB**（8.00×）；精度 81.53% → **78.89%**（−2.64 点，n = 379） |
| 推理 | 树莓派 4B | 双线程演示页 **28.8 ms/帧**；单线程 LiteRT 45.0 ms |
| 演示页 | 树莓派，浏览器打开 | 36 张验证集图片循环，判定烙印在图上（绿=对、红=错，判错的刻意保留） |
| 机械臂手动控制 | 树莓派 → USB | 协议已在实物上确认：夹爪、肩部能转，爪内灯能开关 |
| 机械臂操作台 | STM32L476RG + ILI9341 彩屏 | 编译 0 error / 0 warning；**尚未在板上运行** |

## 仓库结构

```
src/
  trashnet_trial/     感知端流水线，按运行顺序编号：
                        00_split.py → 01_inspect.py → 02_train.py → 03_quantize.py
                        → 04_verify_tflite.py → 05_pi_predict.py → 06_pi_live.py
                        → 07_pi_webcam.py → 08_pi_demo.py → 09_pi_fullval.py
  gesture_trial/      早期用 978 张自采图片验证"采集 → 训练 → 实时 → 量化"整条链路的三分类实验。
                      已被 trashnet_trial 取代，留着是因为只有它记录了原始采集步骤和过程笔记。
  cebek_arm/          动作端。协议细节见 src/cebek_arm/README.md。
    pi/               三个纯标准库 Python 程序（不用 pyusb、不建 venv）：
                        cebek.py           ctypes 直调 libusb，附旧的命令行/GUI
                        cebek_bridge.py    USART ↔ USB 串口桥，带 1 500 ms 看门狗
                        cebek_oneclick.py  双击即用：自动连接、拔插重连、按住点动、急停
    stm32/            STM32L476 操作台的 Keil MDK 工程 —— 纯寄存器 C，不用 HAL。
                      CMSIS 与器件头文件已放在 stm32/cmsis/ 下，除编译器外无需装任何包。
docs/                 带日期的过程记录：分类器复刻步骤、树莓派页面部署、树莓派反复断线的排查、
                      以及"分类结果 → 机械臂"这一环的视觉伺服方案。
tools/                开发期间用的一次性脚本，不属于运行时代码。
```

**以下内容刻意不入库，以及原因：**

- `data/`、`models/` —— TrashNet 副本与所有训练权重都能由脚本重跑出来；光 int8 模型就 2.62 MB，且每次实验都会变。
- `hardware/` —— 厂商光盘、说明书、机械臂照片。第三方材料。
- `docs/notes_snapshot_*/`、`docs/emails/` —— 工作笔记与邮件草稿，不是项目产出。
- `new/`、`*.hex`、`*.axf`、`*.map` —— Keil 编译产物。

## 硬件与工具链

- **感知端算力**：树莓派 4B / 8 GB，Raspberry Pi OS Trixie 64-bit，无桌面；推理用 `ai-edge-litert` 2.3.0。PC 侧用 Python 3.13 + TensorFlow 训练。
- **相机**：Raspberry Pi Camera Module v2（IMX219）。
- **机械臂**：Cebek C-9895.2。实为 **OWI Robotic Arm Edge (OWI-535)** 贴牌版 —— USB ID `1267:0000`（`0x1267` 属 OWI Inc.），5 个直流减速电机加一个爪内灯，**没有任何位置反馈**。
- **操作台**：STM32L476RGTx（LQFP64）自制板，ILI9341 240×320 SPI 彩屏，四个按键。
- **工具链**：Keil MDK-ARM + ARM Compiler 5.06；STM32 侧直接对着 `stm32/cmsis/` 里的寄存器定义写，**没有 HAL，也没有 CubeMX 工程**。

## 怎么跑

### 1. 感知端流水线

训练在 PC 上做。仓库不含 TrashNet，自己下载后把 `00_split.py` 指向它。

```
python 00_split.py            # 分层划分：2 148 训练 / 379 验证
python 02_train.py            # MobileNetV2，float32，产物写到 models/
python 03_quantize.py         # 转 int8 TFLite
python 04_verify_tflite.py    # 在验证集上重新评一遍量化后的模型
```

在树莓派上，只要有同一个模型文件和相机就够：

```
python3 06_pi_live.py         # 窗口内实时分类
python3 08_pi_demo.py         # 演示页，http://<pi>:8090/
```

`08_pi_demo.py` 用标准库发 MJPEG 流 —— 不需要 Flask；如果图片预先编码过，连 PIL 都不用装。
它循环播放验证集，把判定烙在帧上，让看的人能看到错误，而不只是看到对的。

### 2. 树莓派上的机械臂控制台

机械臂是一个 USB **设备**，必须由带 USB 主机控制器的一方给它下指令 —— 这个角色是树莓派。
先一次性授权，再运行图形界面：

```
sudo ./授权USB访问.sh          # 为 1267:0000 装 udev 规则
python3 cebek_oneclick.py      # 或双击 机械臂控制台.desktop
```

也有不需要界面的自检 —— 开灯 + 让夹爪轻动一下：

```
python3 cebek.py test --yes
```

STM32 对话的对象是 `cebek_bridge.py`：它从串口读 ASCII 行，逐条转成三字节 USB 指令发给机械臂；
若 1 500 ms 内没有新指令，它自己发停止帧。

### 3. STM32 操作台

1. 用 Keil MDK-ARM 打开 `src/cebek_arm/stm32/CebekArm.uvprojx`。
2. 编译，产物是 `new/CebekArm.hex`（26 593 字节），该目录不入库。
3. 烧进去。上电后屏幕显示 `LINK DOWN` 直到树莓派回心跳 —— 树莓派没接时这就是正常状态，不是故障。

按键：短按让某个关节动，长按是同一个键的第二个功能 —— 四个键放八个功能，不用翻菜单。

## 工作原理

### 分类器

MobileNetV2 加一个 6 分类头，在 TrashNet（cardboard / glass / metal / paper / plastic / trash）上训练，
按 2 148 / 379 分层划分。量化用训练集里抽的代表性数据集做 int8，验证集 379 张上掉 2.64 个点 ——
这个代价还在"演示仍然成立"的范围内。int8 模型在树莓派上余量充足：28.8 ms/帧意味着
在同一帧里还塞得下相机采集和一条指令下发。

### 机械臂控制协议

厂商说明书讲的是 Windows 软件，不是线上协议。这部分是观察加实物验证得来的：

三个字节装在一次 HID 类控制传输里
（`bmRequestType = 0x40`、`bRequest = 0x06`、`wValue = 0x0100`、`wIndex = 0`）：

| 字节 | 位 | 关节 | 00 | 01 | 10 |
|---|---|---|---|---|---|
| 0 | 1:0 | 夹爪 | 停 | 合 | 开 |
| 0 | 3:2 | 腕 | 停 | 上 | 下 |
| 0 | 5:4 | 肘 | 停 | 上 | 下 |
| 0 | 7:6 | 肩 | 停 | 上 | 下 |
| 1 | 1:0 | 底座 | 停 | 顺时针 | 逆时针 |
| 2 | 0 | 爪内灯 | 灭 | 亮 | — |

这个协议有两条性质，整个设计都被它们决定了：

**指令是锁存的。** 一条指令会让关节一直动，直到下一条指令到达；`00 00 00` 是唯一的停止。
所以"延时"全部是主机的责任 —— 机械臂本身没有"动 300 ms"这个概念。

**控制传输是唯一通路。** 设备枚举为 USB Low Speed，只有一个 `0x81` 中断 IN 端点，
**完全没有 OUT 端点** —— bulk OUT 写入不是麻烦，而是物理上做不到。任何主机都只能用控制传输。

这也是 STM32 无法直接驱动机械臂的原因：L476 的 USB 外设确实能当主机，但裸机工程里做这件事
要写一整套主机协议栈，而它要用的那对引脚在这块板上已经给显示屏占了。于是 USB 的活交给树莓派，
STM32 退化成一台通过串口跟树莓派说话的操作台。

## 已知限制

- **两半还没接上。** 没有 `分类 → 规划 → 动作` 的代码。机械臂只在人按键时动。
- **机械臂没有任何反馈。** 无编码器、无限位开关、无电流检测。"动 800 ms"就是唯一的控制原语；
  夹爪到底有没有夹住物体，软件不知道。因此重复性受电池电压和负载制约，
  任何标定都必须在稳压电源上做，不能在电池上做。
- **STM32 固件只编译过，没在板上跑过。** 0 error / 0 warning 是编译器的结论，不是硬件的结论。
- **`cebek_oneclick.py` 只过了语法检查，没在树莓派上跑过。** 它下面的 libusb 层和串口桥
  都在实机验证过；叠在上面的界面是在树莓派离线期间写的。
- **int8 的精度数字只有一次划分。** 379 张、单次分层留出，没有 k-fold，也还没有逐类错误分析。
- **`gesture_trial/` 是死代码，只为留住它的笔记。** 不要把它当成现在的流水线读。

## 项目信息

| | |
|---|---|
| 课程 | UCLan MP3000 Engineering Project with Sustainability（2026–27） |
| 导师 | Dr Yu Zhou |
| 器材 | Cebek C-9895.2 机械臂，借自 Dr Carl Berry |
| 技术报告 | 2027-04-12 |
| 海报与答辩 | 2027-05-06 |

分类器、机械臂控制台与这份协议记录属于项目产出，可以阅读和复用。
技术报告本身是提交作业，不在本仓库内。
