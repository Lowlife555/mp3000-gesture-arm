# STM32L476 Operator Console

A handheld console for the arm: an ILI9341 colour display, four buttons, and a serial link to the
Raspberry Pi that actually talks USB. Register-level C, no HAL, no CubeMX project.

```
build:  0 errors, 0 warnings  (Keil MDK-ARM, ARM Compiler 5.06 update 5)
size:   Code 7 380 B  RO 1 984 B  RW 72 B  ZI 2 384 B
output: new/CebekArm.hex, 26 593 B
```

Verified only as far as the linker. It has not been run on a board yet.

## Wiring

| From | To | Note |
|---|---|---|
| Arm, USB connector | Pi USB port | the Pi is the USB host |
| Nucleo/board micro-USB | Pi USB port | one cable carries power and `/dev/ttyACM0` |
| Arm `BKR` | 6 V supply | do **not** power the motors from the Pi's USB |
| Display and buttons on the expansion board | the STM32 | — |

## Pin map

The pinout, the LCD initialisation sequence, the 8×16 font table and the startup file were carried
over from an earlier board in this account that already worked
([`wellspan-health-watch`](https://github.com/Lowlife555/wellspan-health-watch),
`firmware/tft-lcd/App/LCD/`). The pin map below matches that board exactly.

| Function | Pin | Alternate function |
|---|---|---|
| LCD SCK | **PA5** | AF5 (SPI1) |
| LCD MOSI | **PA7** | AF5 (SPI1) |
| LCD DC | **PA11** | GPIO output |
| LCD RST | **PA12** | GPIO output |
| Button UP | **PA0** | input, pull-up |
| Button DOWN | **PA4** | input, pull-up |
| Button OK | **PB1** | input, pull-up |
| Button BACK | **PC13** | input, pull-up |
| UART TX | **PA2** | AF7 (USART2) |
| UART RX | **PA3** | AF7 (USART2) |

The display has no CS and no backlight pin — both are tied on the board, so the driver does not
drive them.

**PA11 and PA12 are the L476's USB_DM and USB_DP.** On this board they belong to the display, which
is the physical reason this console cannot also be a USB host: the peripheral is wired away.

## Buttons

Each button has a short and a long press, giving eight functions on four keys with no menu
navigation:

| Button | Short press | Long press (> 500 ms) |
|---|---|---|
| **UP** | previous joint | duration +1 step |
| **DOWN** | next joint | duration −1 step |
| **OK** | run the selected joint once, for the set duration | run continuously; release to stop |
| **BACK** | flip direction | emergency stop |

Durations: 50 / 100 / 150 / 200 / 300 / 500 / 750 / 1 000 / 1 500 / 2 000 / 3 000 ms.
Power-up default is shoulder, forward, 300 ms.

The gripper light is one more entry in the joint list (`LED`); OK toggles it.

## Screen

```
┌────────────────────────────────┐
│ CEBEK ARM  L476                │  title bar
│ LINK OK / LINK DOWN !          │  green / red
├────────────────────────────────┤
│   M1 GRIPPER                   │
│   M2 WRIST                     │
│   M3 ELBOW                     │
│ > M4 SHOULDER          12.3s   │  selected row highlighted, EST total on the right
│   M5 BASE                      │
│   LED LIGHT                    │
├────────────────────────────────┤
│ DIR   POSITIVE                 │
│ TIME  300 ms                   │
│ EST   12.3 s                   │  accumulated command time, NOT an angle
├────────────────────────────────┤
│ READY / RUN M3 +  STEP         │  cyan idle, orange running
│ ELBOW  123 ms                  │
├────────────────────────────────┤
│ OK   tap = step                │
│ OK   hold= run                 │
│ BACK tap = dir                 │
│ BACK hold= STOP                │  red
└────────────────────────────────┘
```

Two things it deliberately does not do. **It shows no angles** — the arm has no position feedback,
so displaying one would be inventing data; `EST` is a command total and is labelled as such.
**It shows only ASCII** — `font_data.h` holds 8×16 ASCII glyphs, and adding CJK glyphs would mean
building a new font table, which this version does not attempt.

## Safety

Because a command latches, a stop has to be redundant:

| Layer | Owner | Condition | Action |
|---|---|---|---|
| 1 | STM32 | a single motion exceeds **3 000 ms** | send `00 00 00`; hold mode is bounded the same way and has to be released to restart |
| 2 | STM32 | no `PONG` from the Pi for **1 500 ms** | stop immediately and refuse to start any further motion |
| 3 | Pi | no new command for **1 500 ms** | watchdog sends `00 00 00` |

Layer 2 is the important one: once the link is down this console can no longer issue a valid
command, so only the Pi can still brake. In the other direction, when the Pi dies this console
notices the silence and stops issuing commands. The two layers are each other's failure case.

`arm_init()` also sends `00 00 00` as its first command at power-up, so an arm that was left
running by something else does not move when this board is plugged in.

## Line protocol

Plain ASCII lines, so a dropped half-packet resynchronises on the next newline. 115 200 8N1 over
the ST-LINK virtual COM port; on the Pi that is `/dev/ttyACM0`.

| Direction | Message |
|---|---|
| STM32 → Pi | `ARM <b0> <b1> <b2>` — three hex bytes, e.g. `ARM 41 00 00` |
| STM32 → Pi | `PING` — heartbeat, every 500 ms |
| STM32 → Pi | `STOP` — brake (`ARM 00 00 00` is sent alongside) |
| Pi → STM32 | `OK` / `PONG` / `ERR <reason>` / `TMO` (Pi watchdog fired) |

The Pi side is `../pi/cebek_bridge.py`:

```
python3 cebek_bridge.py --port /dev/ttyACM0 -v
```

## Files

| File | Purpose |
|---|---|
| `CebekArm.uvprojx` | the Keil project — open this |
| `_gen_uvprojx.py` | regenerates the project file; needs a working MDK5 `.uvprojx` as a skeleton, path passed in `CEBEK_UVPROJX_TEMPLATE`. Only needed if the source list changes |
| `system.c` | minimal startup support: FPU enable, `SystemInit`, `SystemCoreClock` |
| `clock.c/.h` | HSI16 → PLL → 80 MHz. Order matters: voltage range 1, then flash wait states, then switch SYSCLK |
| `delay.c/.h` | SysTick at 1 kHz plus DWT microsecond delays — not spin loops, so they survive an optimisation-level change |
| `board_pins.h` | every pin in one place, with `gpio_mode` / `pull` / `af` / `speed` helpers |
| `lcd.c/.h` | ILI9341 over SPI1 at 10 MHz; no framebuffer, partial-window refresh; text is packed into a row-major buffer and sent as one burst |
| `keys.c/.h` | four-button scan with 20 ms debounce — polled, not EXTI, because polling is easier to debug |
| `uart2.c/.h` | USART2 interrupt receive, ring buffer, line assembly; overflows are dropped rather than blocking the ISR |
| `arm.c/.h` | command encoding (joint + direction → 3 bytes), reply parsing, link state |
| `ui.c/.h` | menu state machine, short/long press handling, timeouts and safety, partial redraw on change |
| `main.c` | init and main loop |
| `font_data.h` | 8×16 ASCII glyphs, from the WellSpan project's `App/LCD/FONT.H` |
| `cmsis/` | CMSIS 5.0.1 core headers and DFP 2.7.0 device header, vendored so the project does not depend on an installed pack |
| `startup_stm32l476xx.s` | startup file, from the WellSpan project |

## Why the STM32 does not act as USB host

USB Low Speed is 666.7 ns per bit. At 80 MHz that leaves 53 cycles per bit, and the edge jitter
budget is roughly ±10 ns — under one clock period. On top of the bit timing, USB needs NRZI
encoding with bit stuffing, CRC5 and CRC16, a SETUP/DATA/ACK handshake answered within 165 ns, and
a SOF every 1 ms. Toggling GPIO cannot meet that, and there is no usable open-source bit-bang host
implementation to borrow.

Two real options exist for a self-contained STM32, both deferred to a later revision:

| Option | Hardware | Effort | Cost |
|---|---|---|---|
| **MAX3421E** (SPI to USB host) | ¥20–40 module | roughly 400 lines | recommended; does not touch PA11/PA12 |
| L476 OTG_FS in host mode | ¥0 | weeks, writing a host stack | PA11/PA12 collide with the display, so the board has to change |

## Notes for anyone editing this

1. **Do not regenerate from CubeMX.** The project is hand-written register-level code and has no `.ioc`.
2. `board_pins.h` is the only place to change a pin.
3. The LCD register sequence came from a board that already displayed correctly. Do not replace it
   with a generic sequence from the internet without testing on the hardware.
4. If the display is upside down, change `MADCTL_180` in `lcd.c`: `0xC8` (180°), `0x08` (0°),
   `0x68` (90°), `0xA8` (270°).
5. If PC13 reads 0 permanently, the board uses a pull-down on that key; set `KEY_BACK_PULL` to
   `GPIO_PULL_NONE` in `keys.c`.

---

# STM32L476 操作台

机械臂的手持控制台：一块 ILI9341 彩屏、四个按键，以及一条连到树莓派的串口 —— USB 的活由树莓派干。
纯寄存器 C，不用 HAL，也没有 CubeMX 工程。

```
编译：  0 error, 0 warning  （Keil MDK-ARM，ARM Compiler 5.06 update 5）
尺寸：  Code 7 380 B  RO 1 984 B  RW 72 B  ZI 2 384 B
产物：  new/CebekArm.hex，26 593 B
```

验证只做到链接为止。**还没有在板上跑过。**

## 接线

| 从 | 到 | 说明 |
|---|---|---|
| 机械臂 USB 口 | 树莓派 USB 口 | 树莓派才是 USB 主机 |
| 开发板 micro-USB | 树莓派 USB 口 | 一根线同时供电并提供 `/dev/ttyACM0` |
| 机械臂 `BKR` | 6 V 电源 | **不要**从树莓派 USB 给电机取电 |
| 扩展板上的屏与按键 | STM32 | — |

## 引脚

引脚分配、LCD 初始化序列、8×16 字库和启动文件，都来自本账号下另一块已经跑通的板子
（[`wellspan-health-watch`](https://github.com/Lowlife555/wellspan-health-watch)，
`firmware/tft-lcd/App/LCD/`）。下表的引脚与该板完全一致。

| 功能 | 引脚 | 复用 |
|---|---|---|
| LCD SCK | **PA5** | AF5 (SPI1) |
| LCD MOSI | **PA7** | AF5 (SPI1) |
| LCD DC | **PA11** | GPIO 输出 |
| LCD RST | **PA12** | GPIO 输出 |
| 按键 UP | **PA0** | 输入 + 上拉 |
| 按键 DOWN | **PA4** | 输入 + 上拉 |
| 按键 OK | **PB1** | 输入 + 上拉 |
| 按键 BACK | **PC13** | 输入 + 上拉 |
| 串口 TX | **PA2** | AF7 (USART2) |
| 串口 RX | **PA3** | AF7 (USART2) |

屏上没有 CS、也没有背光脚 —— 两者在板上直接拉死，驱动里也就不需要。

**PA11 与 PA12 正是 L476 的 USB_DM / USB_DP。** 这块板把它们给了显示屏，这就是本操作台
不可能同时当 USB 主机的物理原因：外设引脚已经被占走了。

## 按键

每个键都有短按和长按，四个键出八个功能，不用翻菜单：

| 键 | 短按 | 长按（> 500 ms） |
|---|---|---|
| **UP** | 上一个关节 | 时长 +1 档 |
| **DOWN** | 下一个关节 | 时长 −1 档 |
| **OK** | 按当前时长动作一次 | 持续动作，松手即停 |
| **BACK** | 反转方向 | 急停 |

时长档位：50 / 100 / 150 / 200 / 300 / 500 / 750 / 1 000 / 1 500 / 2 000 / 3 000 ms。
上电默认是肩部、正转、300 ms。

爪内灯在关节列表里单独占一项（`LED`），短按 OK 开关。

## 屏幕

```
┌────────────────────────────────┐
│ CEBEK ARM  L476                │  标题条
│ LINK OK / LINK DOWN !          │  绿 / 红
├────────────────────────────────┤
│   M1 GRIPPER                   │
│   M2 WRIST                     │
│   M3 ELBOW                     │
│ > M4 SHOULDER          12.3s   │  选中行高亮，右端是该关节的 EST 累计
│   M5 BASE                      │
│   LED LIGHT                    │
├────────────────────────────────┤
│ DIR   POSITIVE                 │
│ TIME  300 ms                   │
│ EST   12.3 s                   │  命令累计时间，不是角度
├────────────────────────────────┤
│ READY / RUN M3 +  STEP         │  就绪青色，动作中橙色
│ ELBOW  123 ms                  │
├────────────────────────────────┤
│ OK   tap = step                │
│ OK   hold= run                 │
│ BACK tap = dir                 │
│ BACK hold= STOP                │  红色
└────────────────────────────────┘
```

有两件事它是刻意不做的。**不显示角度** —— 这只臂没有任何位置反馈，显示角度就是编数据；
`EST` 是命令累计值，界面上也这么标。**只显示 ASCII** —— `font_data.h` 里是 8×16 的 ASCII 字模，
要显示中文得另做字模表，这一版没做。

## 安全

因为指令会锁存，刹车必须有冗余：

| 层 | 谁 | 条件 | 动作 |
|---|---|---|---|
| 1 | STM32 | 单次动作超过 **3 000 ms** | 发 `00 00 00`；按住模式同样受限，必须松手才能重来 |
| 2 | STM32 | **1 500 ms** 收不到树莓派的 `PONG` | 立刻停，并且在链路恢复前拒绝启动任何新动作 |
| 3 | 树莓派 | **1 500 ms** 没有新指令 | 看门狗发 `00 00 00` |

第 2 层是关键：链路断了以后本操作台已经发不出有效指令，只剩树莓派还能刹车。反过来，
树莓派挂掉时本操作台察觉沉默并停止发令。两层互为对方的失效场景。

`arm_init()` 上电发的第一条命令也是 `00 00 00`，这样即使臂此前被别的东西驱动过、还在转，
插上本板也不会跟着乱动。

## 线协议

纯 ASCII 文本行，丢半个包也能在下一个换行符重新对齐。115 200 8N1，走 ST-LINK 虚拟串口；
在树莓派上就是 `/dev/ttyACM0`。

| 方向 | 内容 |
|---|---|
| STM32 → Pi | `ARM <b0> <b1> <b2>` —— 三个十六进制字节，如 `ARM 41 00 00` |
| STM32 → Pi | `PING` —— 心跳，每 500 ms |
| STM32 → Pi | `STOP` —— 刹车（同时会发 `ARM 00 00 00`） |
| Pi → STM32 | `OK` / `PONG` / `ERR <原因>` / `TMO`（树莓派看门狗触发） |

树莓派侧程序是 `../pi/cebek_bridge.py`：

```
python3 cebek_bridge.py --port /dev/ttyACM0 -v
```

## 文件

| 文件 | 作用 |
|---|---|
| `CebekArm.uvprojx` | Keil 工程 —— 用这个打开 |
| `_gen_uvprojx.py` | 重新生成工程文件；需要一个能编译的 MDK5 `.uvprojx` 当骨架，路径由环境变量 `CEBEK_UVPROJX_TEMPLATE` 传入。只有改源文件清单时才用得到 |
| `system.c` | 最小启动支撑：开 FPU、`SystemInit`、`SystemCoreClock` |
| `clock.c/.h` | HSI16 → PLL → 80 MHz。顺序不能错：先电压档 Range 1，再 Flash 等待周期，最后切 SYSCLK |
| `delay.c/.h` | SysTick 1 kHz 时基，加 DWT 微秒延时 —— 不是空转循环，改优化等级也不会漂 |
| `board_pins.h` | 所有引脚集中在这一个文件，附 `gpio_mode` / `pull` / `af` / `speed` 内联工具 |
| `lcd.c/.h` | ILI9341 走 SPI1 10 MHz；无帧缓冲、局部窗口刷新；整字打包进行主序缓冲区后一次连写 |
| `keys.c/.h` | 四键扫描 + 20 ms 消抖 —— 轮询而非 EXTI，因为轮询更好调试 |
| `uart2.c/.h` | USART2 中断接收 + 环形缓冲 + 行拼装；溢出直接丢，不在中断里阻塞 |
| `arm.c/.h` | 指令编码（关节 + 方向 → 3 字节）、回话解析、链路判定 |
| `ui.c/.h` | 菜单状态机、长短按处理、超时与安全、按需局部重绘 |
| `main.c` | 初始化与主循环 |
| `font_data.h` | 8×16 ASCII 字模，来自 WellSpan 工程的 `App/LCD/FONT.H` |
| `cmsis/` | CMSIS 5.0.1 内核头与 DFP 2.7.0 器件头，随工程附带，不依赖 pack 安装位置 |
| `startup_stm32l476xx.s` | 启动文件，来自 WellSpan 工程 |

## 为什么 STM32 不自己当 USB 主机

USB Low Speed 每位 666.7 ns。80 MHz 下每位只有 53 个周期，而边沿抖动预算约 ±10 ns ——
还不到一个时钟周期。位时序之外，USB 还要 NRZI 编码加位填充、CRC5 与 CRC16、
165 ns 内应答的 SETUP/DATA/ACK 三段握手，以及每 1 ms 一个 SOF。
GPIO 翻转做不到这一点，也没有可用的开源 bit-bang 主机实现可以借。

要让 STM32 独立控制，真正可行的只有两条路，都留给后续版本：

| 方案 | 硬件 | 工作量 | 代价 |
|---|---|---|---|
| **MAX3421E**（SPI 转 USB 主机） | ¥20–40 模块 | 约 400 行 | 推荐；不占 PA11/PA12 |
| L476 OTG_FS 做主机 | ¥0 | 周级，要自写主机协议栈 | PA11/PA12 与显示屏冲突，得改板 |

## 改代码时注意

1. **不要用 CubeMX 重新生成。** 本工程是纯寄存器手写，没有 `.ioc`。
2. `board_pins.h` 是唯一改引脚的地方。
3. LCD 寄存器序列来自一块已经正常点亮的板子。不要换成网上通用的那份，除非先在实物上验过。
4. 若屏幕上下颠倒，改 `lcd.c` 里的 `MADCTL_180`：`0xC8`（180°）、`0x08`（0°）、`0x68`（90°）、`0xA8`（270°）。
5. 若 PC13 一直读 0，说明板上该键是下拉接法，把 `keys.c` 里的 `KEY_BACK_PULL` 改成 `GPIO_PULL_NONE`。
