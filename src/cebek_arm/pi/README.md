# Cebek C-9895.2 机械臂 · 树莓派控制台

## 这台臂是什么

**它其实是 OWI Robotic Arm Edge（OWI-535）的贴牌版本。**

| 证据 | 内容 |
|---|---|
| USB ID | `1267:0000` —— `0x1267` 是 **OWI Inc.** 的厂商标识 |
| 关节构成 | 5 个直流减速电机 + 爪内 Search Light，**无任何位置反馈** |
| 标称参数 | 底座旋转 270°、肩 180°、肘 300°、腕 120°、夹爪开口 45 mm |
| 说明书画的界面 | Basic 模式按住即动、Program 模式"选电机 + 设时间"，与 OWI 官方软件一致 |

`Cebek C-9895.2` 是 `CIC Components Industries`（台湾）的销售品牌，
代工方就是做 OWI 的那条线。

## 协议（这是重点）

**3 字节，位打包，USB control transfer 发送。**

```
byte0  位[1:0] = 夹爪 Gripper
       位[3:2] = 腕   Wrist
       位[5:4] = 肘   Elbow
       位[7:6] = 肩   Shoulder
       每 2 位取值： 00 = 不动 / 01 = 一个方向 / 10 = 另一个方向

byte1  位[1:0] = 底座 Base
       00 = 不动 / 01 = 顺时针 / 10 = 逆时针

byte2  位[0]   = 爪内 LED
       0 = 关 / 1 = 开
```

**发送方式（OWI 开源实现通用写法）：**

```
bmRequestType = 0x40   bRequest = 0x06   wValue = 0x0100   wIndex = 0
数据 = 3 字节
```

原厂的 Windows 驱动是 WDK BulkUsb 示例改的，说明设备**同时有 bulk 端点**。
本程序**先试 control，失败自动退 bulk OUT**，并把成功的那种记住。

### 最关键的一条语义

> **发一次命令，机械臂会一直动，直到下一次命令。** `00 00 00` 是通用停止。

所以原厂说明书 Program 模式里的"时间"是这么实现的：

```
发命令 → 主机 sleep N 毫秒 → 发 00 00 00
```

**这不是机械臂内部在计时，是电脑在计时。** 这一点解释了为什么它标称
"最大起重 100 g"、为什么会"da da da"打滑、为什么断电后不知道自己在哪。

## 装到树莓派上

```
~/Desktop/CebekArm/
├── cebek.py                    主程序（单文件，零依赖）
├── 启动GUI.sh                  双击启动图形界面
├── 授权USB访问.sh              ★ 第一次必须跑一次（要输密码）
├── Cebek控制台.desktop         桌面图标
└── README.md                   本文件
```

### 第一步：授权 USB 访问（必须做一次）

Linux 默认只有 root 能写 `/dev/bus/usb/*`。跑：

```bash
bash ~/Desktop/CebekArm/授权USB访问.sh
```

它会让你输密码，然后添加一条 udev 规则。**之后把机械臂 USB 拔下再插上**。

### 第二步：确认设备在

```bash
cd ~/Desktop/CebekArm
python3 cebek.py info
```

应该看到 `1267:0000` 和它的端点表。**这一步只看不写，零风险。**

### 第三步：安全自检

把臂放在空旷处，爪子朝外，手离开：

```bash
python3 cebek.py test --yes
```

它只做两件事：开灯 → 关灯 → 夹爪夹/松各 300 ms。
**灯亮了、夹爪动了 = 协议对上了。**

### 第四步：用图形界面

双击桌面上的 **Cebek控制台**，或者：

```bash
bash ~/Desktop/CebekArm/启动GUI.sh
```

界面里：

- **按住按钮 = 一直动，松开 = 立刻停**（对应原厂 Basic 模式）
- **"点头按"按钮 = 动一个滑块设定的时长后自动停**（对应原厂 Program 模式）
- 红色 **■ 全部停止** 是急停
- 勾选 **爪内 LED** 控制爪子里的灯

## 命令行速查

```bash
python3 cebek.py info                        # 枚举设备（只读）
python3 cebek.py test --yes                  # 灯 + 夹爪自检
python3 cebek.py move shoulder up 300 --yes  # 肩部向上 300 ms
python3 cebek.py move base cw 500 --yes      # 底座顺时针 500 ms
python3 cebek.py light on                    # 爪内 LED 开
python3 cebek.py stop                        # 立刻停
python3 cebek.py raw 00C000                  # 发原始 3 字节
```

关节名：`shoulder` / `elbow` / `wrist` / `gripper` / `base`
（也可以用 `m1`–`m5`，或中文 `肩部` / `肘部` / `腕部` / `夹爪` / `底座`）

方向：`up|down`（肩肘腕）、`cw|ccw`（底座）、`open|close`（夹爪）

## 安全注意

1. **没有任何位置反馈。** 界面上的"累计秒数"是**命令累加值**，不是实测位置，会随时间漂移。**别把它当成角度。**
2. **单次动作硬上限 3 秒**，代码里写死的，防手滑。
3. **程序异常退出时会发停止帧**（`finally` 里），但如果**关掉树莓派或拔 USB**，臂会保持最后一条命令直到断电。
4. **撞限位只有齿轮打滑保护**（"da da da"）。第一次试动作请从 **100–200 ms** 开始。
5. **机械臂的 6 V 电源必须来自 `BKR` 接口，不要从树莓派的 USB 取电。** 树莓派的 USB 只负责数据。

## 为什么不用 pip / 不用装 pyusb

`cebek.py` 只用 Python 标准库的 `ctypes`，直接调用系统里已经装好的
`libusb-1.0.so.0`。这样做的好处：

- Debian 13 有 PEP 668 限制（`pip install` 会被拒），本方案完全不受影响
- 不需要 venv、不需要联网、不需要 root
- 一个文件拷走就能在别的 Linux 上跑

## 已知未确认的事

- **control transfer 还是 bulk OUT**：两种都可能，代码自动探测。第一次跑完会告诉你哪种成功了。
- **夹爪"01/10"哪个是夹、哪个是松**：`up down` 的极性在 OWI-535 上是确定的，但贴牌版可能有反接。`cebek.py test` 跑一遍就知道。
- **每个关节的转速**：没有任何官方数据（不同负载下不一样）。要拿标定数据只能自己做（ArUco 标记 + 相机测位移）。

## 串口桥（给 STM32 用）

`cebek_bridge.py` 把 STM32 从串口发来的 3 字节转发到机械臂 USB，并带一个
**看门狗**：1500 ms 没收到新命令就自动发 `00 00 00`。这是必要的，因为
**这台臂发了命令就一直动**——STM32 掉电、UART 松了、程序死循环，都得有人踩刹车。

```
STM32 (USART2, PA2/PA3) ──ST-LINK 虚拟串口──▶ 树莓派 /dev/ttyACM0
                                                   │
                                                   ▼
                                            control transfer
                                                   │
                                                   ▼
                                             OWI 接口板 USB
```

### 线协议（ASCII 文本，一行一条）

| 方向 | 内容 |
|---|---|
| STM32 → Pi | `ARM <b0> <b1> <b2>`　三个十六进制字节，如 `ARM 41 00 00` |
| STM32 → Pi | `PING`　心跳 |
| STM32 → Pi | `NOP`　仅刷新看门狗 |
| STM32 → Pi | `STOP`　立刻踩刹车 |
| Pi → STM32 | `OK` / `PONG` / `ERR <原因>` / `TMO`（看门狗触发） |

### 用法

```bash
python3 cebek_bridge.py --port /dev/ttyACM0 -v      # 连 STM32
python3 cebek_bridge.py --stdio -v                  # 从标准输入测（不用 STM32）
python3 cebek_bridge.py --stdio --no-usb            # 只测协议解析，不碰硬件
```

已实测：`PING`→`PONG`、`ARM 00 00 00`→全部都停、`ARM 00 00 01`→灯亮且**保持亮**
（直到 `STOP`）—— 这直接验证了"命令是锁存的"这条核心语义。

## 为什么 STM32 不自己做 USB 主机

USB Low Speed 位宽 666.7 ns，L476 在 80 MHz 下每 bit 只有 53 个周期，
要求边沿抖动在 ±10 ns 内。GPIO 翻转做不到，而且 USB 还有 NRZI 编码、
位填充、CRC5/CRC16、SETUP/DATA/ACK 三段握手和每 1 ms 的 SOF。
**GPIO 模拟 USB 主机不可行。**

两条真正可行的"STM32 独立控制"路线：

| 方案 | 硬件 | 工作量 | 说明 |
|---|---|---|---|
| **MAX3421E**（SPI 转 USB 主机芯片） | ¥20–40 模块 | 约 400 行 | 推荐留作 V2；不用 PA11/PA12 |
| L476 自带 OTG_FS 做主机 | ¥0 | 大（要自己写主机协议栈） | PA11/PA12 与 LCD 的 DC/RST 冲突，需改板 |

## 参考

- [owi535py · Message Rules（本文用的协议描述）](https://github.com/XinArkh/owi535py/blob/master/docs/rules.md)
- [flaviomauro/owi535-robotic-arm-with-python](https://github.com/flaviomauro/owi535-robotic-arm-with-python)
- [alexsigaras/OWI535-RoboticArm（C#）](https://github.com/alexsigaras/OWI535-RoboticArm)
