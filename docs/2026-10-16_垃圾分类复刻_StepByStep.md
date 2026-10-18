# 垃圾分类复刻 · Step by Step（阶段 0–1：准备 + 在 PC 上训模型）

> **来源**：Bilibili「基于深度学习的垃圾分类【保姆级教程】」BV1RV411x7BN（2021-06-01，UP 主 芃蜀黍的果麥，10.3 万播放）
> **参考实现**：`open_source_reference/github/` 下 4 个仓库（⚠️ 只读参考，不是你的作品）
> **定稿日期**：2026-10-16
> **目的**：跑通「数据 → 训模型 → 转 TFLite → 部署到树莓派」这条链，坐实报告里 ML + 边缘部署那一章
>
> ⚠️ **学术边界**：这 4 个仓库是**参考实现**。可以读、可以跑、可以学思路并注明来源；**不可以当自己的代码提交，更不可以让它的文字进你的报告**（MP3000 用 Turnitin 查 AI 与抄袭）。

---

## 为什么不能 1:1 抄代码（先讲清，免得你白折腾）

| 教程原本 | 为什么不行 | 我们的替代 |
|---|---|---|
| `tensorflow==1.13.1` | PyPI 上**没有任何 ARM 轮子**，树莓派上装不上（换任何 Python 版本都不行） | **TF 2.21**（你已有）训练，**ai-edge-litert**（LiteRT，即 `tflite-runtime` 改名后的继任者）部署 |
| `keras==2.3.1` + `adam(lr=, decay=)` | 该版本只有 sdist，`lr`/`decay` 在 Keras 2.11+ 已改名 | TF2 内置 Keras |
| `ResNet50` 224×224 | 在 Pi 上跑一帧要好几秒，**而且 25 MB 起步** | **MobileNetV2**（约 10 MB int8，Pi 4 上几十毫秒） |
| 树莓派**只当薄客户端**，推理在 PC | 那不算「树莓派做机器学习」 | **把推理搬上 Pi**（这就是阶段 B） |
| 40 类 / 14,964 张（华为云，仅在百度网盘） | 下不动；且 40 类对第一次跑通过重 | **TrashNet 6 类 / 2,527 张 / 42.8 MB / MIT** |
| Electron 桌面前端 | `node-sass@4` 需 Python 2，`electron@2` 2018 年已 EOL | **砍掉**（对评分零增量） |

> **一句话：流程 1:1，代码重写。**

---

## 路线图（5 步，每步都能独立验证）

| 阶段 | 干什么 | 在哪台机器上 | 需要什么 | 现在能做吗 |
|---|---|---|---|---|
| **0** | 备料：买摄像头 / 灯 / SD 卡，Windows 装工具 | Windows | 花钱 | ✅ |
| **1** | **下数据 → 训 MobileNetV2 → 转 int8 TFLite → 本地验证** | **Windows** | 无 | ✅ **今晚就能做** |
| **2** | 给树莓派装系统 + SSH 进去 | 树莓派 | SD 卡、读卡器 | 〔待确认型号〕 |
| **3** | Pi 上跑 L1：**喂一张静态图，输出类别**（不用摄像头） | 树莓派 | 树莓派能开机 | 〔待阶段 2〕 |
| **4** | Pi 接摄像头做 L2：**对桌上实物实时识别** | 树莓派 | 摄像头到货 | 〔待阶段 3〕 |

**本文档只覆盖阶段 0 与阶段 1** —— 这两步**完全不依赖树莓派**，你现在就能开始。阶段 2–4 要等你回答「树莓派是什么型号 / 有没有 SD 卡 / 装系统接不接显示器」，我再补写。

---

# 阶段 0 · 备料

## 0.1 要买的东西

| 东西 | 价格 | 链接 | 必要性 |
|---|---|---|---|
| **Raspberry Pi Camera Module V2**（8MP Sony IMX219，全新） | **£12.49**（含运费） | `ebay.co.uk/itm/365524167059` | 阶段 4 必需 |
| **150mm 15-pin 相机排线**（备用） | **£1.00** | `thepihut.com/products/raspberry-pi-camera-board-replacement-cable-150mm` | ⚠️ eBay 那包**是否含线无法确认**，买条保险 |
| **5V COB LED 灯带 白光 6500K**（或 USB 白光 LED 灯 £2.60） | **£3.80** | `thepihut.com/products/5v-cob-led-strip-light-white` | ⭐⭐ **这个比升级摄像头有用** |
| **microSD 卡 32GB Class10/A1** | £6–9 | Amazon | ⚠️ 没有的话阶段 2 做不了 |
| 烘焙纸 / 描图纸 | 免费 | 厨房 | ⭐ **漫射灯带，没有它颜色分类会被高光毁掉** |

**合计 ≈ £24–26**（含 SD 卡）

**⭐ 为什么不升级摄像头**：TFLite 的 MobileNetV2 输入只有 **224×224**。8MP（3280×2464）降到这个尺寸已经**降采样约 15 倍** —— 换 12MP/16MP 多出来的像素**分类器根本看不到**。而 Camera Module V2 的镜头筒**可以手动拧焦**（官方规格：约 10 cm 到无穷），你把相机固定在桌面 30–50 cm 上方拧一次，之后永远清晰。

---

## 0.2 Windows 上装两个软件

| 软件 | 干什么 | 怎么装 |
|---|---|---|
| **Raspberry Pi Imager** | 把操作系统烧进 SD 卡 | `raspberrypi.com/software` 下载安装 |
| **VS Code 扩展 `Remote - SSH`** | 在 VS Code 里直接操作树莓派 | VS Code → 扩展 → 搜 `Remote - SSH`（ms-vscode-remote.remote-ssh）→ 安装 |
| VS Code 扩展 `Jupyter`（可选但推荐） | 交互式跑训练、看图 | 同上，搜 `Jupyter`（ms-toolsai.jupyter） |

⚠️ 你已有的 `ms-python.python` / `ms-python.vscode-pylance` 不用重装。

---

## 0.3 建训练目录

在 `mp3000-gesture-arm` 仓库根目录下：

```powershell
cd C:\Users\<you>\Desktop\mp3000-gesture-arm
New-Item -ItemType Directory -Force data\trashnet | Out-Null
New-Item -ItemType Directory -Force src\trashnet_trial | Out-Null
```

> `data/` 和 `models/` 已在 `.gitignore` 里 —— **数据集和模型不会进 git**，这是对的（体积大、可再生产）。

---

# 阶段 1 · 在 PC 上训模型

> **本阶段全程在你的 Windows 上，不需要树莓派。做完你会得到一个 `.tflite` 文件，那才是要送上 Pi 的东西。**

## 1.1 下载数据集（TrashNet，42.8 MB）

⚠️ **必须用 Python 下，不要用 `Invoke-WebRequest` 或 `curl.exe`** —— 你这台机器的 .NET HTTPS 与 Schannel TLS 是坏的，那两个会超时。Python 走 OpenSSL，没问题。

```powershell
cd C:\Users\<you>\Desktop\mp3000-gesture-arm
& C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe -c "import urllib.request; urllib.request.urlretrieve('https://huggingface.co/datasets/garythung/trashnet/resolve/main/dataset-resized.zip','data/trashnet/dataset-resized.zip')"
```

解压：

```powershell
Expand-Archive data\trashnet\dataset-resized.zip -DestinationPath data\trashnet -Force
Get-ChildItem data\trashnet\dataset-resized | Select-Object Name, @{n='张数';e={(Get-ChildItem $_.FullName -File).Count}}
```

**你应该看到 6 个文件夹**：`cardboard` `glass` `metal` `paper` `plastic` `trash`，合计 **2,527 张**。

### ⚠️ 关于这个数据集，你必须知道的三件事（写报告要用）

1. **它是 MIT 许可**，来自 `garythung/trashnet`（Thung & Yang, CS229 2016）。**引用要写对**：
   > Thung, G. and Yang, M. (2016) *Classification of Trash for Recyclability Status*. CS229 Project Report, Stanford University.
2. **官方基线是约 75% 测试准确率**（70/13/17 划分）。**这是你该拿来对比的数字。**
3. **「trash」这一类的样本最少（实测 137 张，占 5.4%）**，会拖低整体准确率 —— **这正是写「错误分析」的好素材**，不要藏起来。

---

## 1.2 先看数据（5 分钟，别跳）

新建 `src\trashnet_trial\01_inspect.py`：

```python
"""01 看数据：类别、张数、极小类、坏图"""
import pathlib
from collections import Counter
from PIL import Image

DATA = pathlib.Path(__file__).resolve().parents[2] / "data" / "trashnet" / "dataset-resized"

counts = Counter()
bad = []
sizes = Counter()
for p in DATA.rglob("*"):
    if p.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        continue
    cls = p.parent.name
    counts[cls] += 1
    try:
        with Image.open(p) as im:
            sizes[im.size] += 1
    except Exception as e:
        bad.append((p.name, str(e)))

total = sum(counts.values())
print(f"总计 {total} 张，{len(counts)} 类\n")
for cls, n in counts.most_common():
    print(f"  {cls:<12} {n:>5}  {n/total:6.1%}")
print(f"\n图片尺寸分布（前 5）: {sizes.most_common(5)}")
print(f"坏图: {len(bad)}")
for name, err in bad[:10]:
    print(f"  {name}: {err}")

if bad:
    print("\n⚠️ 有坏图，训练时会报错 —— 手工删掉或移走它们")
```

跑：

```powershell
& C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe src\trashnet_trial\01_inspect.py
```

**⚠️ 如果坏图数 > 0，先把它们移走再训练。** 这是新手最常卡的第一个坑 —— `image_dataset_from_directory` 遇到坏图会直接抛异常或静默跳过，两种都会让你怀疑人生。

---

## 1.3 训练脚本

新建 `src\trashnet_trial\02_train.py`：

```python
"""
02 训练：MobileNetV2 迁移学习（两阶段）+ 存 keras 模型

对应教程里 ResNet50 的两阶段做法，但换成 Pi 跑得动的骨干。
"""
import json
import pathlib

import numpy as np
import tensorflow as tf

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "trashnet" / "dataset-resized"   # 原始图片，00_split.py 的输入
TRAIN = ROOT / "data" / "trashnet_split" / "train"      # 00_split.py 的产出
VAL = ROOT / "data" / "trashnet_split" / "val"
OUT = ROOT / "src" / "trashnet_trial" / "models"
OUT.mkdir(parents=True, exist_ok=True)

IMG = 224
BATCH = 32
SEED = 1337

# ── 1. 数据 ───────────────────────────────────────────────────────────
# ⚠️ 不用 validation_split —— 它不分层，会把验证集切成"文件表末尾的那几个类"。
#    改成用 00_split.py 按类别切好的目录。详见下面「1.3.1 两个坑」。
train_raw = tf.keras.utils.image_dataset_from_directory(
    TRAIN, image_size=(IMG, IMG), batch_size=BATCH, seed=SEED, shuffle=True)
val_raw = tf.keras.utils.image_dataset_from_directory(
    VAL, image_size=(IMG, IMG), batch_size=BATCH, shuffle=False)
CLASS_NAMES = train_raw.class_names
print("类别:", CLASS_NAMES)

# ⚠️ 增强器是【独立层】，只挂在训练管道上，绝不放进模型图
augmenter = tf.keras.Sequential([
    tf.keras.layers.RandomFlip("horizontal"),
    tf.keras.layers.RandomRotation(0.08),
    tf.keras.layers.RandomZoom(0.10),
], name="augmenter")

AUTOTUNE = tf.data.AUTOTUNE
train_ds = (train_raw
            .map(lambda x, y: (augmenter(x, training=True), y),
                 num_parallel_calls=AUTOTUNE)
            .cache().prefetch(AUTOTUNE))
val_ds = val_raw.cache().prefetch(AUTOTUNE)

# ── 2. 模型 ───────────────────────────────────────────────────────────
# Rescaling 留在模型内部，是为了让 Pi 那边直接喂原始像素，不用另写归一化。
# ⚠️ 但 Random* 增强层【不能】在图里 —— 理由见 1.3.1。
base = tf.keras.applications.MobileNetV2(
    input_shape=(IMG, IMG, 3), include_top=False, weights="imagenet")
base.trainable = False

inputs = tf.keras.Input(shape=(IMG, IMG, 3), name="image")
x = tf.keras.layers.Rescaling(1.0 / 127.5, offset=-1.0, name="rescale")(inputs)
x = base(x, training=False)
x = tf.keras.layers.GlobalAveragePooling2D(name="gap")(x)
x = tf.keras.layers.Dropout(0.2)(x)
outputs = tf.keras.layers.Dense(len(CLASS_NAMES), activation="softmax", name="pred")(x)
model = tf.keras.Model(inputs, outputs, name="trashnet_mobilenetv2")

CKPT = OUT / "best.keras"
callbacks = [
    tf.keras.callbacks.ModelCheckpoint(CKPT, monitor="val_accuracy",
                                       save_best_only=True, verbose=1),
    tf.keras.callbacks.EarlyStopping(monitor="val_accuracy", patience=6,
                                     restore_best_weights=True),
    tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                         patience=2, verbose=1),
]

# ── 3. 阶段 A：冻结骨干，只训分类头 ──────────────────────────────────
print("\n=== 阶段 A：冻结骨干 ===")
model.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
              loss="sparse_categorical_crossentropy", metrics=["accuracy"])
model.fit(train_ds, validation_data=val_ds, epochs=8, callbacks=callbacks)

# ── 4. 阶段 B：解冻最后 30 层，小学习率微调 ──────────────────────────
print("\n=== 阶段 B：微调最后 30 层 ===")
base.trainable = True
for layer in base.layers[:-30]:
    layer.trainable = False

model.compile(optimizer=tf.keras.optimizers.Adam(1e-5),
              loss="sparse_categorical_crossentropy", metrics=["accuracy"])
model.fit(train_ds, validation_data=val_ds, epochs=8, callbacks=callbacks)

# ── 5. 存盘 + 记元数据 ────────────────────────────────────────────────
model = tf.keras.models.load_model(CKPT)
loss, acc = model.evaluate(val_ds, verbose=0)
print(f"\n验证集：loss={loss:.4f}  acc={acc:.4f}")

meta = {"class_names": CLASS_NAMES, "img_size": IMG,
        "val_accuracy": float(acc), "val_loss": float(loss),
        "source": "garythung/trashnet (MIT)", "backbone": "MobileNetV2"}
(OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                              encoding="utf-8")
model.save(OUT / "trashnet_mobilenetv2.keras")
print(f"已保存: {OUT / 'trashnet_mobilenetv2.keras'}")
```

### 1.3.1 两个坑（都是实测踩出来的，不是理论）

**坑一：`validation_split` 不分层。**

`image_dataset_from_directory(validation_split=0.15)` 是对**排序后的文件总表**做一刀切，不按类别抽样；而且 `subset="validation"` 会强制 `shuffle=False`，于是那 15% 永远是文件表**末尾**的同一批类：

```
cardboard 403 + glass 501 + metal 410 + paper 594 + plastic 482 + trash 137 = 2527
前 85%（2148）→ 训练
后 15%（ 379）→ 验证   ← 实测正好 = plastic 的后 242 张 + trash 全部 137 张
```

**⇒ 验证集里 cardboard / glass / metal / paper 各是 0 张。** 这样测出来的准确率只能证明模型会分两类，**对另外四类的能力完全没被检验**。

修法：先跑 `00_split.py`，按类别各抽 15% 生成 `data/trashnet_split/{train,val}/<类>/`，再分别喂给 `image_dataset_from_directory`。实测切开后每类都有人：

| 类别 | train | val |
|---|---|---|
| cardboard | 343 | 60 |
| glass | 426 | 75 |
| metal | 348 | 62 |
| paper | 505 | 89 |
| plastic | 410 | 72 |
| trash | 116 | 21 |
| **合计** | **2148** | **379** |

**坑二：把数据增强放进模型图，会被一起导出成 TFLite。**

`RandomFlip` / `RandomRotation` / `RandomZoom` 如果写在 `inputs → … → outputs` 的图里，`TFLiteConverter.from_keras_model()` 会把它们编进 `.tflite`。**到了 Pi 上，每张图在推理前都会被随机翻转、随机旋转、随机缩放** —— 同一个物体每次预测都不一样，而且大概率是错的。

这个错误**不报错**，只表现为"Pi 上识别率莫名其妙地低"。修法：增强器做成**独立层**，只挂在训练用的 `tf.data` 管道上（`.map(lambda x, y: (augmenter(x, training=True), y))`），不进模型图。

> 量化脚本里加一条断言兜底：模型层名里出现 `random` / `augment` 就直接报错停下。

跑：

```powershell
& C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe src\trashnet_trial\00_split.py
& C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe src\trashnet_trial\02_train.py
```

### ⏱️ 大概多久（实测，不是估计）

- **实测这台机器**（8845HS / 32 GB / 无独显）：**每轮 16–20 秒**；阶段 A 8 轮 **141 s**、阶段 B 8 轮 **166 s**，**整轮 5 分钟**。
- **⚠️ 别照抄"1–3 分钟/轮"那类估计** —— 差一个数量级。你自己的 CPU 实测一遍再写进报告。
- **第一次跑可以先把轮数降下来**（环境变量 `TRASHNET_EPOCHS=2`），只验证管道通不通。通了再恢复 8 正式跑。

### 预期的准确率（实测）

| 项目 | 数值 |
|---|---|
| TrashNet 官方基线（ResNet50, 70/13/17） | 约 **75%** |
| **本机 float32 模型** | **81.53%**（384 张分层验证集） |
| **int8 tflite** | **78.89%**（量化损失 −2.64 点） |

- 官方基线 **约 75%**（ResNet50, 70/13/17）
- **⚠️ 别期待 95%+**。TrashNet 的 `trash` 类只有 137 张，天花板就在那里
- **⚠️ 这些是这台机器上的数，你要自己测一遍。** 报告里引用必须写清测量条件（哪台机器、多少张验证集、什么划分方式）

---

## 1.4 转成 int8 TFLite

新建 `src\trashnet_trial\03_quantize.py`：

```python
"""
03 量化：float32 keras → int8 tflite
体积大约降到 1/4，精度通常只掉 1-2 个点（要自己测，别信口说）
"""
import json
import pathlib

import tensorflow as tf

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS = ROOT / "src" / "trashnet_trial" / "models"
DATA = ROOT / "data" / "trashnet" / "dataset-resized"

meta = json.loads((MODELS / "meta.json").read_text(encoding="utf-8"))
IMG = meta["img_size"]

model = tf.keras.models.load_model(MODELS / "trashnet_mobilenetv2.keras")

# 代表性数据集：必须用真实图片，随机噪声会让量化精度崩掉
rep_ds = tf.keras.utils.image_dataset_from_directory(
    DATA, image_size=(IMG, IMG), batch_size=1, shuffle=True, seed=0,
)

def representative():
    for i, (images, _) in enumerate(rep_ds):
        if i >= 100:          # 100 张足够
            break
        yield [tf.cast(images, tf.float32)]

converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.uint8      # Pi 直接喂原始像素
# ⚠️ 不要设 inference_output_type = tf.uint8 —— softmax 概率只占 8 bit 会丢精度，
#    输出保持 float32（实测输出 quant=(0.0, 0)，即原样 float，不用反量化）

tflite = converter.convert()
out = MODELS / "trashnet_mobilenetv2_int8.tflite"
out.write_bytes(tflite)

f32_size = (MODELS / "trashnet_mobilenetv2.keras").stat().st_size
print(f"keras 体积 : {f32_size/1024/1024:8.2f} MB")
print(f"tflite 体积: {len(tflite)/1024/1024:8.2f} MB")
print(f"压缩比     : {f32_size/len(tflite):8.2f}×")
print(f"已保存     : {out}")
```

> ⚠️ **如果转换报错**，先把 `inference_input_type` 这一行注释掉（退回 float32 输入 —— 文件大 4 倍，但一定转得成），**先跑通再优化**。这是很常见的取舍，也是报告里可以写的一段。
>
> **实测体积（这台机器）**：keras float32 **20.93 MB** → int8 tflite **2.62 MB**，**压缩 8.00×**（不是"1/4"，注意 keras 文件里含优化器状态，所以倍数比纯权重比更大）。

## 1.5 在 PC 上验证 `.tflite`（送 Pi 之前必须做）

新建 `src\trashnet_trial\04_verify_tflite.py`：

```python
"""
04 验证：用 tflite 解释器跑一张图，打印类别、置信度、耗时
⚠️ 这一步在 PC 上做，确认 tflite 文件是好的，再送去树莓派
"""
import json
import pathlib
import time

import numpy as np
import tensorflow as tf

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS = ROOT / "src" / "trashnet_trial" / "models"
DATA = ROOT / "data" / "trashnet" / "dataset-resized"

meta = json.loads((MODELS / "meta.json").read_text(encoding="utf-8"))
CLASSES = meta["class_names"]
IMG = meta["img_size"]

interp = tf.lite.Interpreter(
    model_path=str(MODELS / "trashnet_mobilenetv2_int8.tflite"))
interp.allocate_tensors()
inp = interp.get_input_details()[0]
out = interp.get_output_details()[0]
print("输入:", inp["shape"], inp["dtype"], "| 输出:", out["shape"], out["dtype"])

def predict(path):
    # 读图 + resize 到 224×224 + 保持 uint8
    raw = tf.io.read_file(str(path))
    img = tf.io.decode_image(raw, channels=3, expand_animations=False)
    img = tf.image.resize(img, (IMG, IMG), method="bilinear")
    arr = tf.cast(img, tf.uint8).numpy()[None, ...]

    interp.set_tensor(inp["index"], arr)
    t0 = time.perf_counter()
    interp.invoke()
    ms = (time.perf_counter() - t0) * 1000

    probs = interp.get_tensor(out["index"])[0].astype(np.float32)
    # int8 输出需要反量化
    scale, zero = out["quantization"]
    if scale:
        probs = (probs - zero) * scale
    top = int(np.argmax(probs))
    return CLASSES[top], float(probs[top]), ms, probs

# 从每类各抽一张试
for cls_dir in sorted(DATA.iterdir()):
    if not cls_dir.is_dir():
        continue
    pic = next(cls_dir.glob("*.jpg"), None) or next(cls_dir.glob("*.png"), None)
    if pic is None:
        continue
    label, conf, ms, _ = predict(pic)
    flag = "✅" if label == cls_dir.name else "❌"
    print(f"{flag} 真值={cls_dir.name:<10} 预测={label:<10} 置信度={conf:6.2%}  {ms:7.2f} ms")

print("\n⚠️ 这个延迟是 PC 的，不是树莓派的 —— Pi 上会慢一个量级，到阶段 3 再实测")
```

跑：

```powershell
& C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe src\trashnet_trial\04_verify_tflite.py
```

**看到 6 行「✅ 真值=xxx 预测=xxx」⇒ 阶段 1 完成。** 那个 `.tflite` 文件就是你要送上树莓派的东西。

---

## 1.6 阶段 1 的「完成标准」（自己对照）

- [ ] `data/trashnet/dataset-resized/` 下有 6 个类文件夹、约 2,527 张图
- [ ] `01_inspect.py` 跑通，坏图已清理
- [ ] **`00_split.py` 跑通，验证集里 6 个类都有样本**（不是只有末尾两类）
- [ ] `02_train.py` 跑通，`models/meta.json` 里的 `val_accuracy` > 0.75（超过官方基线）
- [ ] `03_quantize.py` 跑通，体积明显变小，且**量化后的准确率也一起报出来**
- [ ] `04_verify_tflite.py` 六类全对（或有明确错在哪类）
- [ ] 把上面这些**数字记下来** —— 报告里要写：类别数、训练/验证张数（含每类分布）、准确率（float32 与 int8 各多少）、模型体积（float32 vs int8）、PC 上的单帧延迟、Pi 上的单帧延迟

**⚠️ 这些数字是你自己的实验结果，不是抄的。** 报告里引用时必须写清测量条件。

---

# 阶段 2 · 无头装系统 + SSH 登录（Pi 4 Model B / 8 GB）

> **前提已确认**：树莓派是 **Pi 4 Model B 8 GB**；有 microSD 卡 + 读卡器；**没有外接显示器和键盘 —— 全程 SSH**。
> **本阶段目标**：卡烧好、插进 Pi、通电，然后你的 Windows 上 `ssh` 就能进去。

### ⚠️ 2026 年起的新前提：Trixie / Python 3.13

- 现在的 `Raspberry Pi OS (64-bit)` = **Debian 13 Trixie + Python 3.13**（不是 Bookworm / 3.11）。
- `tflite-runtime` **没有 Python 3.13 的轮子**（`pip install` 直接 `from versions: none`）；这个包已改名为 **`ai-edge-litert`（LiteRT）**。
- 唯一正确的导入：`from ai_edge_litert.interpreter import Interpreter` —— `from ai_edge_litert import Interpreter` 会 `ImportError`。
- `python3-picamera2` **镜像里已预装**（`0.3.37-1`），不用自己装。
- ⚠️ `python3-libcamera` 是**按 CPython 3.13 编译的二进制扩展，ABI 只对 3.13 有效**：venv 必须用**系统自带的 Python 3.13** 建，建好后**绝不能换一个 Python 小版本重建** —— 否则 `picamera2` 立刻 import 不进去。

## 2.1 为什么要 64 位系统（不是随便选的）

8 GB 内存的板子**必须**装 64 位系统。32 位 ARM 进程寻址不到 4 GB 以上，你买的 8 GB 有一半用不上。而我们要装的 `ai-edge-litert` 发的正是 **`cp313` / `aarch64`（64 位 ARM）** 轮子 —— 64 位系统对它来说既**必须**、也**足够**。

**⇒ 系统选：`Raspberry Pi OS (64-bit)`，即 Debian 13 Trixie，Python 3.13。**

> ⚠️ **版本千万别记错**：64 位镜像就是 **Debian 13 Trixie + Python 3.13**。这件事要紧，因为 pip 的轮子是**按 Python 小版本发的**（`cp313` 的轮子装不进 3.11，`cp311` 的也装不进 3.13）—— 下面所有版本号都按 3.13 写。

## 2.2 用 Raspberry Pi Imager 烧卡（无头配置全在这里做完）

1. 打开 **Raspberry Pi Imager**
2. **Choose Device** → `Raspberry Pi 4`
3. **Choose OS** → `Raspberry Pi OS (64-bit)`（不要选 Lite/Full，选带桌面的标准版，反正不用）
4. **Choose Storage** → 你的 microSD 卡 ⚠️ **确认盘符，别烧错盘**
5. ⭐ **点右下角齿轮（或 `Ctrl+Shift+X`）打开 `Edit Settings`** —— 这一步是无头安装的全部关键：

| 设置项 | 填什么 | 说明 |
|---|---|---|
| **Set hostname** | `mp3000pi-niyoujia` | 之后可以用 `mp3000pi-niyoujia.local` 访问，不用记 IP |
| **Set username and password** | 用户名 `niyoujia`，密码自己定（**记下来**） | ⚠️ Debian 起不能再用默认密码 |
| **Configure wireless LAN** | 你家的 **SSID + 密码**，Country 选 `GB` | ⚠️ 只支持 **2.4 GHz / 5 GHz 都行，但不支持企业级认证**；如果你的 WiFi 是 WPA3-only 或需要网页登录，先用手机热点 |
| **Set locale** | Time zone `Europe/London`，Keyboard `gb` | |
| ⭐ **Enable SSH** | **勾上 → `Use password authentication`** | **不勾这一项，你就永远进不去** |

6. 点 **Save** → **Write** → 确认覆盖
7. 烧完 Imager 会提示可以拔出

> ⚠️ **别跳过齿轮设置。** 没填 WiFi 和 SSH 的话，一块无头板子通电后就是一块砖 —— 你没有任何办法进去，只能重新烧卡。

## 2.3 首次开机

1. 卡插进 Pi，接网线**不需要**，插电源（**Pi 4 要 5V/3A USB-C**，用手机充电器可能带不动会随机重启）
2. **等 90 秒** —— 首次启动会做分区扩容 + 自动重启一次，绿灯会乱闪，这是正常的
3. 看板子上的**绿灯**：常亮 = 正常；闪烁 = 在读写 SD 卡（正常）

## 2.4 从 Windows 找到它

按顺序试，哪个通就用哪个：

```powershell
# ① 最省事：mDNS（Win10 1803+ 支持）
ping mp3000pi-niyoujia.local

# ② 不行就 SSH 直连试（能连上就说明 DNS 只是没通）
ssh niyoujia@mp3000pi-niyoujia.local

# ③ 还不行：看路由器管理页面的 DHCP 客户端列表，找 hostname = mp3000pi-niyoujia

# ④ 或者扫本机 ARP 缓存
arp -a
```

⚠️ **如果 `ping .local` 不通但 `ssh` 能连上**，那只是 Windows 的 mDNS 解析问题，不影响使用 —— 直接用 IP。

**第一次 SSH 会问 `Are you sure you want to continue connecting (yes/no)?` → 输 `yes`。** 然后输密码（**输密码时屏幕不显示任何字符，这是正常的，别以为键盘坏了**）。

## 2.5 登录后第一件事：更新系统

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

（`full-upgrade` 可能要几分钟到十几分钟，Pi 4 上正常。）

## 2.6 建 Python 虚拟环境（⚠️ Trixie 强制要求）

Trixie（Debian 13）有 PEP 668 限制 —— 直接 `pip install` 到系统会报 `externally-managed-environment` 然后拒绝。**必须建 venv。**

⭐ **关键：venv 要带 `--system-site-packages`** —— 因为 `picamera2` 是 apt 装的系统包，不带这个参数的话 venv 里看不见它（阶段 4 会用到）。

```bash
# 装必要组件 + picamera2（提前装好，阶段 4 就不用再折腾）
sudo apt install -y python3-venv python3-pip python3-picamera2

# 建 venv（注意 --system-site-packages）
python3 -m venv --system-site-packages ~/trashnet-env

# 升级 pip 并装推理运行时
~/trashnet-env/bin/pip install --upgrade pip
~/trashnet-env/bin/pip install "ai-edge-litert==2.3.0" pillow
```

> ⚠️ **为什么不是 `tflite-runtime`**：它**没有 Python 3.13 的轮子**（Google 已把包改名为 `ai-edge-litert` / LiteRT）；`pillow` / `numpy` 不用另装 —— venv 用了 `--system-site-packages`，系统里已有 `pillow 11.1.0` / `numpy 2.2.4`（写上也无害）。

**验证：**

```bash
~/trashnet-env/bin/python -c "import sys; from ai_edge_litert.interpreter import Interpreter; print('Python', sys.version.split()[0]); print('OK: from ai_edge_litert.interpreter import Interpreter')"
```

（这一步**不需要模型文件** —— 只是证明运行时能被导入。真正的推理到阶段 3 才做。）

**看到 `Python 3.13.x` 和 `OK: ...` 两行 ⇒ 阶段 2 完成。**

## 2.7 阶段 2 的完成标准

- [ ] Windows 上 `ssh niyoujia@mp3000pi-niyoujia.local` 能进（或 `ssh niyoujia@<IP>`）
- [ ] `sudo apt update` 无报错
- [ ] `~/trashnet-env/bin/python` 里 `from ai_edge_litert.interpreter import Interpreter` 不报错、`Interpreter` 能导入
- [ ] 记下 **`uname -a`** 和 **`free -h`** 的输出（报告里要写硬件环境）

---

# 阶段 3 · L1：在 Pi 上认一张静态图（不需要摄像头）

> **这是「树莓派跑机器学习」真正成立的时刻。** 摄像头没到货也照样能做 —— 所以**周三的演示用这一步就够了**。

## 3.1 把文件传到 Pi

在你的 Windows 上（`mp3000-gesture-arm` 目录下）：

```powershell
cd C:\Users\<you>\Desktop\mp3000-gesture-arm
mkdir on_pi
copy src\trashnet_trial\models\trashnet_mobilenetv2_int8.tflite on_pi\
copy src\trashnet_trial\models\meta.json on_pi\
copy src\trashnet_trial\05_pi_predict.py on_pi\

scp -r on_pi niyoujia@mp3000pi-niyoujia.local:~/
```

> 如果 `mp3000pi-niyoujia.local` 解析不了，把它换成 `ssh` 通的那个 IP。

## 3.2 Pi 上的推理脚本（⚠️ 和 PC 版不一样）

**新建 `src\trashnet_trial\05_pi_predict.py`**（在 Windows 上建好再传上去）：

```python
"""
05 Pi 端推理：用 ai_edge_litert（LiteRT，不是 tensorflow！）
⚠️ 树莓派上不装 TensorFlow —— 太大。只用 ai_edge_litert + PIL + numpy。

用法：
    ~/trashnet-env/bin/python 05_pi_predict.py on_pi/某张图.jpg
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from ai_edge_litert.interpreter import Interpreter

HERE = Path(__file__).resolve().parent
META = json.loads((HERE / "meta.json").read_text(encoding="utf-8"))
CLASSES = META["class_names"]
IMG = META["img_size"]

interp = Interpreter(model_path=str(HERE / "trashnet_mobilenetv2_int8.tflite"))
interp.allocate_tensors()
inp = interp.get_input_details()[0]
out = interp.get_output_details()[0]
print(f"输入 {inp['shape']} {inp['dtype']} | 输出 {out['shape']} {out['dtype']}")
print(f"类别 {len(CLASSES)}: {CLASSES}\n")


def predict(path):
    """读图 → 224×224 → uint8 → 推理。返回 (类别, 置信度, 毫秒, 全部概率)"""
    img = Image.open(path).convert("RGB").resize((IMG, IMG), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.uint8)[None, ...]   # (1,224,224,3) uint8

    interp.set_tensor(inp["index"], arr)
    t0 = time.perf_counter()
    interp.invoke()
    ms = (time.perf_counter() - t0) * 1000

    raw = interp.get_tensor(out["index"])[0]
    scale, zero = out["quantization"]
    probs = (raw.astype(np.float32) - zero) * scale if scale else raw.astype(np.float32)
    if probs.sum() > 0 and not np.isclose(probs.sum(), 1.0, atol=1e-3):
        probs = probs / probs.sum()            # 归一化成概率
    top = int(np.argmax(probs))
    return CLASSES[top], float(probs[top]), ms, probs


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python 05_pi_predict.py <图片路径> [更多图片...]")
        sys.exit(1)

    for p in sys.argv[1:]:
        if not Path(p).exists():
            print(f"⚠️ 找不到: {p}")
            continue
        cls, conf, ms, probs = predict(p)
        print(f"{Path(p).name}")
        print(f"  预测: {cls}   置信度: {conf:.2%}   耗时: {ms:.1f} ms")
        order = np.argsort(probs)[::-1][:3]
        print(f"  前三: " + "  ".join(f"{CLASSES[i]}={probs[i]:.1%}" for i in order))

    # 连跑 20 次测稳定延迟
    if len(sys.argv) == 2:
        p = sys.argv[1]
        if Path(p).exists():
            predict(p)                                   # 预热
            ts = [predict(p)[2] for _ in range(20)]
            print(f"\n稳定延迟（20 次）: 中位 {np.median(ts):.1f} ms  "
                  f"最快 {min(ts):.1f} 最慢 {max(ts):.1f}  "
                  f"≈ {1000/np.median(ts):.1f} FPS")
```

## 3.3 跑起来

把一张 TrashNet 的测试图也传上去（随便从 `data/trashnet/dataset-resized/plastic/` 里挑一张），然后：

```bash
cd ~/trashnet_demo
source ~/trashnet-env/bin/activate
python 05_pi_predict.py --dir test_images
```

**你应该看到**：每张图的预测类别、置信度、单帧毫秒数。

**实测输出（2026-10-17，Pi 4B / 8 GB，Trixie / Python 3.13.5 / ai-edge-litert 2.3.0）：**

```
· cardboard113.jpg         → cardboard  97.66%    45.4 ms
· glass101.jpg             → glass      82.03%    45.1 ms
· plastic104.jpg           → glass      71.37%    45.0 ms
```

**三件事值得注意：**
1. **45 ms / 帧 ⇒ 约 22 fps** —— 对演示完全够用
2. **plastic 那张错了，和 PC 上错得一模一样** —— 说明**量化没有引入新错误**，这是模型本身的弱点（半透明 + 反光）
3. **置信度分布正常**（97% / 82% / 71%），不是瞎猜

## 3.4 ⭐ 这一步产出的数字，是你报告的核心

| 要记下的数字 | 为什么重要 |
|---|---|
| **Pi 上单帧推理延迟（中位数）** | 「边缘部署」这一章的主证据 |
| **PC 上同一模型的延迟**（阶段 1.5 跑出来的） | **两者相除 = 减速倍数**，这就是一个漂亮的对比实验 |
| **模型体积 float32 vs int8** | 量化收益 |
| **int8 精度 vs float32 精度** | 量化代价 |
| **Pi 的 `uname -a` / `free -h`** | 复现条件 |

**⇒ 这几个数字凑起来就是一段能直接写进报告的实验：**
> 「同一模型在 PC（x86，型号…）上中位延迟 X ms，在树莓派 4B 上 Y ms，减速 Z 倍；int8 量化把体积从 A MB 压到 B MB（−C%），验证集准确率从 D% 变为 E%（±F 点）。」

### 实测记录（2026-10-17，供你对表）

| 指标 | 实测值 |
|---|---|
| PC 单帧延迟（8845HS，无独显） | **3.86 ms**（20 次中位） |
| **Pi 4B 单帧延迟** | **45.0–45.4 ms** |
| **减速倍数** | **约 11.7×** |
| 模型体积 | 20.93 MB → **2.62 MB**（**8.00×**） |
| 验证集准确率 | 81.53% → **78.89%**（**−2.64 点**，n=379） |
| Pi 上抽检 3 张 | cardboard ✅ 97.66% / glass ✅ 82.03% / plastic ❌→glass 71.37% |

**⚠️ 这是这台机器 + 这个模型的结果。你自己的报告里要重测一遍，并写清测量条件。**

---

# 阶段 4 · L2：接摄像头做实时识别（等摄像头到货）

## 4.1 先确认摄像头被认出来

插上 CSI 排线（**蓝色面朝网口方向**，⚠️ 断电插，别热插拔），然后：

```bash
rpicam-hello --list-cameras
```

**应该列出 `imx219`（Module V2）并给出支持的分辨率。**
⚠️ **看不到就查排线方向和是否插到底** —— 常见错因就是这个。

## 4.2 ⭐ 两件必须做的物理调整（比升级摄像头有用得多）

| 调整 | 怎么做 | 为什么 |
|---|---|---|
| **① 手动对焦** | Module V2 的**镜头筒可以拧**。把相机固定在工作距离（30–50 cm），对着一个高对比目标拧到最清晰，**然后别动了** | 官方规格写它是 "Adjustable, about 10 cm to ∞"。**拧一次就永远清晰**，因为相机和桌子都不动 |
| **② 漫射光** | 把灯带/灯放在**侧面而非正上方**，盖一层烘焙纸漫射 | ⭐ **裸 LED 的镜面高光会直接毁掉颜色分类** —— 和上一节「表面要哑光」是同一个道理 |

## 4.3 实时识别脚本

**新建 `src\trashnet_trial\06_pi_live.py`**：

```python
"""
06 Pi 摄像头实时识别

用法：
    ~/trashnet-env/bin/python 06_pi_live.py          # 屏幕预览
    ~/trashnet-env/bin/python 06_pi_live.py --headless  # 无屏幕（只打印）

⚠️ 无头（SSH）环境下没有显示器，看画面要另外把 MJPEG 流转到浏览器 —— 见脚本后面的说明。
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image
from picamera2 import Picamera2
from ai_edge_litert.interpreter import Interpreter

HERE = Path(__file__).resolve().parent
META = json.loads((HERE / "meta.json").read_text(encoding="utf-8"))
CLASSES = META["class_names"]
IMG = META["img_size"]

interp = Interpreter(model_path=str(HERE / "trashnet_mobilenetv2_int8.tflite"))
interp.allocate_tensors()
inp = interp.get_input_details()[0]
out = interp.get_output_details()[0]


def classify(rgb):
    """rgb: numpy uint8 (H,W,3) → (类别, 置信度, 毫秒)"""
    img = Image.fromarray(rgb).resize((IMG, IMG), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.uint8)[None, ...]
    interp.set_tensor(inp["index"], arr)
    t0 = time.perf_counter()
    interp.invoke()
    ms = (time.perf_counter() - t0) * 1000
    raw = interp.get_tensor(out["index"])[0].astype(np.float32)
    scale, zero = out["quantization"]
    probs = (raw - zero) * scale if scale else raw
    if probs.sum() > 0:
        probs = probs / probs.sum()
    top = int(np.argmax(probs))
    return CLASSES[top], float(probs[top]), ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true", help="不显示画面，只打印到终端")
    ap.add_argument("--seconds", type=float, default=0, help="跑多少秒后自动停（0=一直跑）")
    args = ap.parse_args()

    cam = Picamera2()
    # 1080p 抓帧；格式用 RGB888 方便直接喂模型
    cfg = cam.create_preview_configuration(
        main={"size": (1280, 720), "format": "RGB888"})
    cam.configure(cfg)

    # ⭐ 锁死自动白平衡和自动曝光 —— 否则同一块色块在不同时刻读数会漂
    cam.set_controls({
        "AwbEnable": False,
        "AeEnable": False,
        # 下面两个值要按你的实际光照调；先用一个中等值，跑起来再微调
        # "ColourGains": (1.8, 1.5),
        # "ExposureTime": 20000,
    })
    cam.start()
    time.sleep(1.0)          # 让曝光/增益稳定

    print("类别:", CLASSES)
    print("开始识别（Ctrl+C 停止）\n")

    t_start = time.time()
    n = 0
    try:
        while True:
            rgb = cam.capture_array("main")          # (720,1280,3) uint8
            cls, conf, ms = classify(rgb)
            n += 1
            fps = n / max(time.time() - t_start, 1e-6)
            line = f"[{n:4d}] {cls:<10} {conf:6.1%}  {ms:6.1f} ms  平均 {fps:4.1f} FPS"
            print(line, end="\r" if not args.headless else "\n")

            if args.seconds and (time.time() - t_start) > args.seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cam.stop()
        print(f"\n共 {n} 帧，平均 {n/max(time.time()-t_start,1e-6):.1f} FPS")


if __name__ == "__main__":
    main()
```

## 4.4 SSH 里怎么看画面（你没有显示器）

三个办法，从简到繁：

| 办法 | 怎么做 | 适合 |
|---|---|---|
| **① 只看终端文字** | `--headless`，终端里滚动打印「类别 + 置信度 + 延迟」 | ⭐ **周三演示够用** —— 你笔记本开着 SSH，画面不用看，看字就行 |
| **② 抓一张图然后 `scp` 回笔记本看** | `rpicam-still -o test.jpg` → `scp niyoujia@mp3000pi-niyoujia.local:~/test.jpg .` | 检查对焦和光照 |
| **③ 跑 MJPEG 流，浏览器看** | 参考仓库 `garbage_app_sever/app_sever.py` 的 `/video_img_url` 写法 | 想实时看画面 |

**⚠️ 强调**：你说「输入和显示可以用我的笔记本」—— **① 完全符合这个约束，而且就是本周三该用的方案。**

---

# 附 · 到周三（2026-10-21）的时间表

| 日期 | 做什么 | 关键风险 |
|---|---|---|
| **今晚（周六 10-17）** | 下单摄像头（**只买 1 个**，见下方警告）+ 色块 + 灯 + 备用排线 | 摄像头 2–3 天到，**赶不上也不影响周三** |
| **今晚 / 明天** | **阶段 2**：烧卡 → SSH 进去 → 装好 venv | WiFi 若需网页登录会卡住，改用手机热点 |
| **周日–周一** | **阶段 1**：在 PC 上下数据 → 训 → 转 int8 TFLite → 本地验证 | 先 `epochs=2` 验证管道 |
| **周二** | **阶段 3**：把 `.tflite` 传上 Pi → 跑 L1 → **记下延迟数字** | 这一步不需要摄像头 |
| **周三** | 演示：**Pi + SSH 终端 + 笔记本显示**，展示 L1 识别 + 延迟数据 | 摄像头若到了，加上 L2 更好；没到也不影响 |

**⇒ 周三的演示不依赖摄像头。** 摄像头是「加分项」，不是「必须项」——这句话很重要，别把演示赌在快递上。

---

# ⚠️ 附 · 关于「买两个 Module V2」必须先纠正的事

**Pi 4 Model B 只有一个 CSI 摄像头接口。两个 CSI 摄像头不能同时插在 Pi 4 上。**

| 方案 | 可行？ | 说明 |
|---|---|---|
| 两个 CSI Module V2 同时用 | ❌ **不行** | Pi 4 只有 **1 个** 15-pin CSI 接口 |
| 一个 CSI + 一个 USB 摄像头 | ✅ **可以** | 这才是双视角的正确做法 |
| 两个 USB 摄像头 | ✅ 可以 | 但 Pi 4 的 USB 2.0 带宽要留意，用 MJPEG 别用原始 YUY2 |
| Arducam 多路 CSI 转接板 | ⚠️ 不行 | 它是**分时切换**，不是同时采集 —— 做不了立体视觉 |

**⇒ 正确买法：1 个 CSI Module V2（£12.49）+ 1 个 USB 摄像头（二手 C270 约 £6.64）。**
**⇒ 而周三之前，你连第二个都不需要。**

---

# 附 · 如果想换数据集（TrashNet 6 类 → RealWaste 9 类）

阶段 1 的所有代码**只依赖「文件夹名 = 类名」这个约定**，所以换数据集只改一个路径：

```powershell
# 下载 RealWaste（656.6 MB，CC BY 4.0，UCI，无需登录）
& C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe -c "import urllib.request; urllib.request.urlretrieve('https://archive.ics.uci.edu/static/public/908/realwaste.zip','data/realwaste.zip')"
Expand-Archive data\realwaste.zip -DestinationPath data\realwaste -Force
```

然后把 `02_train.py` 里的 `DATA` 指到 `data/realwaste/realwaste-main`，其余不动。

**为什么 RealWaste 更值得写进报告**：它有一篇正式论文给出了 **MobileNetV2 = 88.15%** 的基线（Single, Iranmanesh & Raad, *Information* 2023, 14(12):633, doi:10.3390/info14120633）—— **而 MobileNetV2 正是我们选给 Pi 的骨干**，所以你有直接可对标的已发表数字。

**⚠️ 关于「40 类」**：教程那个 40 类数据集（2020 华为云大赛，14,964 张）**只存在于百度网盘**，不在任何可直接下载的公开源上。所以 40 类**不是"花时间就能做到"，而是"拿不到数据"**。可选的是 6 类（TrashNet）或 9 类（RealWaste）。

---

# 附录 A · 常见错误

| 症状 | 原因 | 怎么办 |
|---|---|---|
| `No matching distribution found for tensorflow==1.13.1` | 你照教程抄了旧版本 | **不要装 TF1**，用你的 `mp3000-nn` venv（TF 2.21） |
| 下载数据集时长时间无响应/超时 | 用了 `Invoke-WebRequest` / `curl.exe`（本机 .NET 与 Schannel TLS 坏） | **改用 Python `urllib`**（见 1.1） |
| `image_dataset_from_directory` 抛异常 | 有坏图 / 有非图片文件混进类文件夹 | 先跑 `01_inspect.py` 清掉 |
| 训练准确率卡在 1/6 ≈ 16.7% | 学习率太大或数据标签错乱 | 用 Adam 1e-3 冻结阶段起步；检查文件夹名即类名 |
| 转换 TFLite 报 `representative_dataset` 相关错 | 代表集的 dtype/形状不匹配 | 先去掉 `inference_input_type`/`output_type` 两行退回 float32 |
| 量化后精度暴跌（掉 20 点以上） | 用随机噪声当代表集 | **必须用真实图片**（见 1.4） |
| `pip install` 报 `externally-managed-environment` | Trixie（Debian 13）的 PEP 668 | 建 venv（阶段 2 会写） |
| Pi 上 `cv2.VideoCapture(0)` 打不开 CSI 摄像头 | Trixie（Debian 13）换成了 libcamera/rpicam 栈 | 用 `picamera2`（阶段 4 会写） |

---

# 附录 B · 这份文档与那 4 个仓库的对应关系

| 本文档 | 参考仓库里的对应文件 | 关系 |
|---|---|---|
| `02_train.py` | `Classify_localtrain/train.py` | **思路同构**（两阶段：冻结→微调），实现换成 TF2 + MobileNetV2 |
| `02_train.py` 的数据管线 | `Classify_localtrain/tools/data_gen.py` | 他们用 `BaseSequence` + `fit_generator`；我们用 `image_dataset_from_directory` |
| `03_quantize.py` | **教程里没有** | ⭐ **这是我们加的，也是报告里最值钱的一环** |
| `04_verify_tflite.py` | `Classify_serverdeploy/prediction.py` | 他们的 `prediction.py` 做同样的事，但用 TF1 的 `tf.Session` |
| 阶段 4 | `garbage_app_sever/app_sever.py` | 他们的 Flask + cv2 骨架可参考；**舵机部分见 `motor.py`（PCA9685）** |
| （砍掉） | `garbage_website/` | 2018 年 Electron 2.0，今天构建不了 |

---

> **⚠️ 最后一句**：报告正文的每一个字必须你自己写。这份文档是**操作手册**，不是报告草稿 —— 里面的代码你可以用、可以改，但**结论和文字要你自己组织**。
