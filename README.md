# MP3000 毕设代码仓库 · 视觉 + 神经网络 + 机械臂

UCLan **MP3000 Engineering Project with Sustainability**（毕业设计）的工作仓库。

**最终成品：摄像头看到实物 → 神经网络识别类别 → 桌面机械臂执行分拣。**
识别用什么模型、手臂怎么动，都是为这一条链路服务的。

**当前进度 V0.0.1（2026-10-18）：感知端已跑通。** 树莓派 4B + 摄像头识别真实生活垃圾，
MobileNetV2 压成 int8 TFLite（2.62 MB），Pi 上 **28.8–29.1 ms/张**，浏览器里能看实时判定。
**动作端（手臂）还没接上** —— 那是下一阶段的主体工作。

| 项 | 值 |
|---|---|
| 选题 | **自拟题（student-proposed），已获批准** |
| 导师 | **Dr Yu Zhou**（个人导师同人）；机械臂借自 **Dr Carl Berry** |
| 器材 | Cebek **C-9895.2** 桌面机械臂（5 轴 + 夹爪，USB） |
| 押分重点 | **机器学习 + 神经网络**（报告叙事主线，非纯电子） |
| 技术报告 | **2027-04-12** |
| 海报答辩 | **2027-05-06** |
| 课程比重 | 技术报告 80% + 答辩 20%；非技术报告 Pass/Fail 必过 |

## 版本路线

| 版本 | 内容 | 状态 |
|---|---|---|
| **V0.0.1** | **感知端**：Pi 4B + 摄像头识别真实生活垃圾（6 类），int8 模型 2.62 MB、28.8–29.1 ms/张，演示页把判定烙在图上（判对绿底 / 判错红底，判错的刻意保留） | ✅ 2026-10-18 |
| **V0.1.0** | **动作端**：识别结果 → 机械臂指令。先打通「上位机 → 舵机控制板 → 机械臂」这一层，再谈分拣精度 | next |
| **V1.0.0** | **成品**：摄像头看到真实垃圾 → 分类 → 机械臂自动抓取并放进对应容器，端到端一次跑完 | next |

> ⚠️ **V0.0.1 是成品的一半（感知），不是一次性的技术彩排。**
> 手臂那半（动作映射 + 分拣闭环）才是毕设的主体工作量，也是评分表上看「系统」而不是「一个分类器」的地方。

## 为什么这个仓库在工作区外面

工作区 `C:\Users\<you>\Desktop\普雷斯顿生存指南` **本身就是一个 git 仓库**（本地、不推远端，里面是笔记与升学材料）。
代码单独成库有两个理由：**① 将来可以独立推到 GitHub 当作品链接**（工作区仓库做不到）；**② 避开嵌套仓库**——在工作区里再 `git init`，父仓库会把该目录当成 gitlink，文件提交不上、状态永远脏。

## 目录

| 路径 | 内容 | 入 git？ |
|---|---|---|
| `src/gesture_trial/` | 试跑项目本体：采集/训练/实时演示/量化 四个脚本 + 5 个 `.cmd` 启动器 + 课件与讲稿 md | 代码与 md ✅；`data/` `models/` `_selftest_snapshot/` ❌ |
| `docs/notes_snapshot_2026-10-15/` | 工作区 MP3000 笔记的**快照**（选题、面谈准备、Proposal 填表、机械臂评估等） | ❌ 本地留存（含他人联系方式与 Proposal 草稿） |
| `docs/emails/` | 给导师与模块办的邮件草稿 | ❌ 本地留存 |
| `tools/` | 辅助脚本（Pi 取证与稳定性、机械臂手册提取、表单自检） | ✅ |
| `open_source_reference/` | 大学给的题册、模块信息包（MIP）、项目手册、任务书与评分标准、模板表格、文本提取、讲座转写；`github/` 子目录放从 GitHub 下载的第三方开源仓库 | ❌ 本地留存 |
| `hardware/vendor_cd/` | 机械臂厂商光盘：4 语说明书 PDF、Windows 驱动 x86/x64、`Install.exe`、`CD_Driver.zip`（34.7 MB） | ❌ 本地留存 |
| `hardware/manual_extracts/` | 从厂商 PDF 抽出的纯文本 + 页面截图（给 agent 读的） | ❌ 本地留存 |
| `hardware/photos/` | 机械臂实物照片 2 张 | ❌ 本地留存 |
| `data/` `models/` | 给正式项目预留的空目录（`.gitkeep`） | ❌ |

> **`open_source_reference/`、`hardware/`、`docs/notes_snapshot_*/`、`docs/emails/` 都在 `.gitignore` 里**：本地随时能读，但**永远不会进 git 历史** —— 大学材料、第三方仓库、厂商光盘、含他人联系方式的笔记与邮件草稿都不该出现在公开仓库里。

## 现在有什么

### 感知端 · V0.0.1（`src/trashnet_trial/`）

- **数据**：TrashNet 2,528 张 / 6 类（cardboard / glass / metal / paper / plastic / trash）；分层划分 2,148 训练 / 379 验证
- **模型**：MobileNetV2 → int8 TFLite，**2.62 MB**（float32 20.93 MB，压 **8.00 倍**）
- **精度**：float32 **81.53%** → int8 **78.89%**（−2.64 点，n=379）
- **延迟**：PC 3.86 ms / **Raspberry Pi 4B 28.8–29.1 ms**
- **演示页**（`08_pi_demo.py`，纯标准库 MJPEG）：36 张验证集图片循环，判定烙在图上，
  判对绿底 / 判错红底，**判错的刻意保留**；页面视口自适应
- **教程**：[`docs/2026-10-16_垃圾分类复刻_StepByStep.md`](docs/2026-10-16_垃圾分类复刻_StepByStep.md)

### 手势试跑 · 早期链路验证（`src/gesture_trial/`）

2026-10-15 为打通「采集 → 训练 → 实时推理 → int8 量化」整条链路做的自采数据实验，
证明这条技术路线可行；后续感知端换了 MobileNetV2 和公开数据集。

- **数据**：3 类手势 **978 张**（`fist` 311 / `palm` 313 / `scissors` 354）——自己用笔记本摄像头采的
- **模型**：`gesture_cnn.keras`（2.52 MB，float32）
- **证据**（`src/gesture_trial/reports/`）：`training_curves.png`、`confusion_matrix.png`、`metrics.json`、`metrics.txt`、`看网络内部.png`
- **网络**：64×64 灰度 → Conv16/Conv32/Conv48（各 + ReLU + 2×2 MaxPool）→ FC64 + Dropout 0.3 → FC3 + Softmax

## 怎么跑

已建好的虚拟环境（**不要用 `py` 启动器那个 3.14，装不了 TensorFlow**）：

```
C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe        # Python 3.13.12, 已装 tf / opencv / matplotlib / numpy
```

优先**双击 `.cmd`**（`训练.cmd` / `实时演示.cmd` / `量化对比.cmd` / `重来_存档并采集.cmd` / `看网络内部.cmd`）；
命令行则按 `01_capture.py → 02_train.py → 03_live_demo.py → 04_quantize.py` 的顺序跑。细节看 [`src/gesture_trial/README.md`](src/gesture_trial/README.md)（170 行，含演示流程与失败排查）。

## 下一步（按优先级）

1. **接上机械臂（→ V0.1.0 主线）**：把分类结果映射成抓取/分拣动作。先拿「单类 → 单个固定动作」
   打通「上位机 → 舵机控制板 → 机械臂」这一层，再谈精度
2. **分拣闭环（→ V1.0.0）**：摄像头看到实物 → 分类 → 手臂抓起来放进对应容器，端到端一次跑完
3. **端侧部署（加分项）**：TFLite Micro / CMSIS-NN 跑在 **STM32L476RG** 上，实测推理延迟、Flash、RAM
   —— 这一步把 demo 从「树莓派上的软件」升级成「嵌入式系统」
4. **严格评估**：k-fold 交叉验证、留出测试集、错误分析（评分表看重「评估诚实性」）
5. **传统方法 baseline**（HOG + SVM）：有对比才叫实验
6. **扩大类别与数据量**，或换公开数据集做对照

## 纪律红线

⚠️ **MP3000 明文禁止用 AI 工具撰写报告**（Turnitin 查重）。
**`src/` 里的代码、`reports/` 里的图表与指标都是项目产物，可以正常使用与迭代；但技术报告的每一个字必须由你自己写。**

## 约定

- 工作区 `笔记库/2_课业笔记/MP3000_毕业设计/` 是**笔记的真相源**；`docs/notes_snapshot_*/` 只是带日期的快照，改快照不算改笔记。
- 规则以工作区根 `AGENTS.md` 为准（本仓库在工作区外，会话**不会自动加载**那些规则，见 [`AGENTS.md`](AGENTS.md)）。
- 进度看板见 [`KANBAN.md`](KANBAN.md)。
- ⚠️ **提交身份**：公开版本统一使用 GitHub 的 no-reply 邮箱（`Lowlife555@users.noreply.github.com`）。不要把私人邮箱配置进 `user.email`，它会被写进每一条提交并永久公开。
