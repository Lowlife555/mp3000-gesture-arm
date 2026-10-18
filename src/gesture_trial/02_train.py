# -*- coding: utf-8 -*-
"""
MP3000 / YZ3 试跑 · 训练小卷积神经网络（CNN）
============================================
【这个文件是整个项目的核心 —— 你问"怎么训练的"，答案就在这里】

读 data/<类别>/*.jpg → 训练一个小 CNN → 保存模型 + 训练曲线 + 混淆矩阵。


────────────────────────────────────────────────────────────────
一、先建立一张全局图：数据在这个文件里怎么流动
────────────────────────────────────────────────────────────────

    data/fist/*.jpg        ┐
    data/palm/*.jpg        ├─→ ① load_dataset()   读成一个大数组 X，形状 (N, 64, 64, 1)
    data/scissors/*.jpg    ┘                      再配一个答案数组 y，形状 (N,)

                            ↓

                       ② stratified_split()     按类别分层，切出 80% 训练 / 20% 验证

                            ↓
              ┌─────────────┴─────────────┐
         Xtr/ytr（训练，模型看得见）   Xva/yva（验证，模型绝不看）

                            ↓
                       ③ build_model()          搭网络：卷积→池化→卷积→池化→卷积→池化→全连接→softmax

                            ↓
                       ④ model.fit()            【真正"学习"发生的地方】反复前向→算错→反向→调旋钮

                            ↓
                       ⑤ evaluate/predict       在验证集上算准确率、混淆矩阵、precision/recall

                            ↓
                       ⑥ 保存                   models/gesture_cnn.keras + reports/ 里的图和指标


────────────────────────────────────────────────────────────────
二、网络长什么样（每一层在干什么）
────────────────────────────────────────────────────────────────

为了让"你能讲清楚每一层在干什么"，这个网络故意做得极小：

    输入 64x64 灰度图
      → 卷积 16 个 3x3 滤波器 + ReLU → 2x2 最大池化      （找边缘、局部笔画）
      → 卷积 32 个 3x3 滤波器 + ReLU → 2x2 最大池化      （把局部笔画拼成"手指的排布"）
      → 卷积 48 个 3x3 滤波器 + ReLU → 2x2 最大池化      （更抽象的部件）
      → 展平 → 全连接 64 + ReLU → Dropout 0.3           （组合成判据）
      → 全连接 3 + Softmax                              （输出三个类别的概率）

【特别提醒一个反直觉的事实】
这个网络一共约 21.5 万个可调参数，其中 **91% 都堆在那个 Dense(64) 全连接层里**，
三层卷积加起来只占 8.7%。跑完你会看到 model.summary() 打印出来 —— 值得记住。


────────────────────────────────────────────────────────────────
三、三个必须讲清楚的概念（老师大概率会问）
────────────────────────────────────────────────────────────────

1. 卷积核 = 一个小窗口在图上滑，学的是"局部模板"。浅层学边缘，深层学组合。
2. 池化   = 每 2x2 取最大 → 图变小、位置稍微移动也不影响判断（这叫平移不变性）。
3. Softmax = 把三个分数压成加起来等于 1 的概率，训练目标是让正确类别的概率尽量大。


────────────────────────────────────────────────────────────────
四、数据划分诚实性（这是评分表里的一条）
────────────────────────────────────────────────────────────────

  - 按类别分层抽样，20% 拿出来当验证集，且**训练时绝不看验证集**；
  - 报告里给出混淆矩阵和逐类 precision/recall —— 不藏错误，这是"评估诚实性"那一条。

  ⚠️ 但验证集只保护"同一批数据内部的泛化"，**不保护捷径学习**。
     2026-10-07 那次失败就是证据：验证集 99%，现场全错。
     原因见 08_零基础教程_原理与技术栈.md 第 5 节。


────────────────────────────────────────────────────────────────
五、用法
────────────────────────────────────────────────────────────────

    python 02_train.py

    前置条件：data/ 里已经有图（先跑 01_capture.py）
    产物：models/gesture_cnn.keras
          reports/training_curves.png（准确率/损失曲线）
          reports/confusion_matrix.png（混淆矩阵）
          reports/metrics.json / metrics.txt（报告要引用的数字）
"""

# ────────────────────────────────────────────────────────────────
# 导入区：这个文件要用到的"工具"
# ────────────────────────────────────────────────────────────────
import os       # 拼路径、建文件夹
import glob     # 按通配符找文件（比如 data/fist/*.jpg）
import json     # 把指标写成 .json，报告里好引用

import numpy as np   # 数组运算。图片在内存里就是一个 numpy 数组
import cv2           # OpenCV：这里只用它读图和缩放

# matplotlib 是画图库。用 "Agg" 后端 = 只把图存成文件，不弹窗口。
# 这一行很关键：如果不设，在没显示器的环境下会报错。
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import tensorflow as tf   # 深度学习框架本体
import keras              # Keras 3：TensorFlow 官方的高层 API，搭网络用它
from keras import layers  # 各种"层"（卷积层、池化层、全连接层……）都在这里


# ────────────────────────────────────────────────────────────────
# 配置区：想改东西，基本只改这一段
# ────────────────────────────────────────────────────────────────
CLASSES = ["fist", "palm", "scissors"]                        # 三个类别，顺序就是标签 0/1/2
CLASS_HINT = {"fist": "握拳", "palm": "手掌", "scissors": "剪刀手"}  # 中文名，只用于显示
IMG_SIZE = 64        # 每张图缩到 64x64。改大→更清楚但更慢、参数更多
VAL_RATIO = 0.20     # 20% 当验证集
SEED = 42            # 随机种子。固定它，每次运行结果可复现（报告里必须固定）
EPOCHS = 40          # 最多训练 40 轮（通常会被 EarlyStopping 提前叫停）
BATCH = 32           # 每批 32 张图。梯度是"看完 32 张才调一次旋钮"

# __file__ 是本文件的路径；取它的目录，保证无论从哪儿运行都能找对 data/models/reports
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MODEL_DIR = os.path.join(HERE, "models")
REPORT_DIR = os.path.join(HERE, "reports")


# ────────────────────────────────────────────────────────────────
# ① 读数据
# ────────────────────────────────────────────────────────────────
def load_dataset():
    """把 data/ 下的图片读成 numpy 数组。返回 (X, y, 每类文件数)。

    这是"把磁盘上的 jpg 变成网络能吃的数字"的那一步。

    出来的 X 形状是 (N, 64, 64, 1)，四个维度分别是：
        N        —— 一共多少张图
        64, 64   —— 高、宽
        1        —— 通道数。1 = 灰度（黑白）。如果是彩色就是 3（RGB）

    出来的 y 形状是 (N,)，每个元素是 0/1/2，对应 CLASSES 里的第几个。
    y 就是"标准答案"，术语叫 label（标签）。
    """
    X, y = [], []
    per_class = {}

    # ── 安全检查：合成数据不能混进真实训练 ──────────────────────
    # 00_selftest.py 会在 data/<类别>/ 下生成一批 fake_*.jpg（合成的圆/条/V 形噪音）。
    # 那是用来验证"代码能跑"的，训出来的模型**不能拿去演示**。
    # 它自己有一道防护（真实图存在时拒绝运行），但它**管不到这里** ——
    # 如果你跑完自检忘了清理、又采了真实数据，两种图就会混在一起训练。
    # 所以这里再挡一道。
    fakes = []
    for c in CLASSES:
        fakes.extend(glob.glob(os.path.join(DATA_DIR, c, "fake_*.jpg")))
    if fakes:
        raise SystemExit(
            "[拒绝训练] data/ 里还有 %d 张合成图片（fake_*.jpg），它们来自 00_selftest.py。\n"
            "           拿合成数据训出来的模型不能用于演示。请先执行：\n"
            "               python 00_selftest.py --clean\n"
            "           确认 data/ 清空后，再跑 01_capture.py 采集真实数据。"
            % len(fakes)
        )

    # enumerate 让它同时给出序号和值：idx=0 时 c="fist"，idx=1 时 c="palm"……
    # 这个 idx 就是这张图的标签。注意：**类别的顺序决定了标签的编号**，
    # 所以 02_train.py 和 03_live_demo.py 里的 CLASSES 顺序必须完全一致。
    for idx, c in enumerate(CLASSES):
        # 找出这一类文件夹下的所有 jpg。sorted 保证每次读的顺序一样（可复现）
        files = sorted(glob.glob(os.path.join(DATA_DIR, c, "*.jpg")))
        per_class[c] = len(files)
        for f in files:
            # IMREAD_GRAYSCALE：直接按灰度读，丢掉颜色信息。
            # 为什么丢颜色？因为手势的形状才是判据，颜色只会带来光照干扰。
            img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue      # 文件坏了就跳过，不让一张坏图搞崩整个训练
            if img.shape != (IMG_SIZE, IMG_SIZE):
                # 尺寸不对就缩一下。正常情况下 01_capture.py 存出来就是 64x64，
                # 这一步是防御性的：万一你手动换了图，也不会崩。
                img = cv2.resize(img, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
            X.append(img)
            y.append(idx)

    if not X:
        # 一张图都没有 → 直接停下，并告诉你怎么做。
        # （这是"报错要能指导下一步"的写法，比抛一个看不懂的异常好）
        raise SystemExit(
            "[错误] data/ 里一张图片都没有。先跑 python 01_capture.py 采集数据。"
        )

    # astype(np.float32) → 转成小数。
    # 除以 255.0 → 归一化：像素原本是 0~255 的整数，现在变成 0.0~1.0 的小数。
    # 【为什么要归一化？】神经网络里全是乘法和加法，输入是 0~255 这种大数时，
    # 数值容易越滚越大、训练不稳定。压到 0~1 是业界默认做法。
    X = np.asarray(X, dtype=np.float32) / 255.0
    y = np.asarray(y, dtype=np.int64)      # 标签必须是整数

    # X[..., None] 是"增加一个维度"：把 (N, 64, 64) 变成 (N, 64, 64, 1)。
    # 【为什么？】Conv2D 要的是"带通道"的四维输入。灰度图的通道数是 1。
    return X[..., None], y, per_class


# ────────────────────────────────────────────────────────────────
# ② 切分训练集 / 验证集
# ────────────────────────────────────────────────────────────────
def stratified_split(y, val_ratio, seed):
    """按类别分层抽样，保证验证集里每个类别都有。

    【为什么要留验证集？】——这是上一轮 grill 你答不出的那题，重点看这里。

    训练集是模型"做过的题"，验证集是"没做过的题"。
    如果只用训练集算准确率，模型完全可以靠死记硬背拿满分，
    但你根本不知道它遇到新图片会不会崩。**验证集就是那个"没做过的题"。**

    【为什么要分层（stratified）？】如果随便抽 20%，可能运气不好，
    验证集里 90% 都是 fist，那这个验证集就测不出 palm/scissors 的好坏。
    分层 = 每个类别内部各自按比例抽，保证三类在验证集里比例均衡。

    【关键操作】下面 rng.shuffle 之后，前 n_val 个给了验证集，剩下的给训练集。
    被分到验证集的那些图，**在 fit() 里绝对不会参与调参**（见 ④ 处）。
    """
    rng = np.random.default_rng(seed)   # 带种子的随机数发生器 → 结果可复现
    tr_idx, va_idx = [], []

    # np.unique(y) 得到 [0, 1, 2]，逐个类别处理
    for cls in np.unique(y):
        # np.where(y == cls)[0] → 找出所有标签等于 cls 的位置（下标）
        idx = np.where(y == cls)[0]
        rng.shuffle(idx)                                     # 打乱这个类别内部的顺序
        n_val = max(1, int(round(len(idx) * val_ratio)))     # 这一类该抽多少张当验证
        va_idx.extend(idx[:n_val].tolist())                  # 前 n_val 个 → 验证集
        tr_idx.extend(idx[n_val:].tolist())                  # 剩下的   → 训练集

    rng.shuffle(tr_idx)   # 再打乱一次，避免同类图片扎堆（对批训练有好处）
    rng.shuffle(va_idx)
    return np.array(tr_idx), np.array(va_idx)


# ────────────────────────────────────────────────────────────────
# ③ 搭网络
# ────────────────────────────────────────────────────────────────
def build_model(n_classes):
    """故意做小的 CNN —— 参数量小到能背下来，纯 CPU 也能很快训完。

    Keras 的写法是"把层按顺序摞成一个列表"，这叫 Sequential（顺序模型）。
    数据从第一层依次流到最后一层，所以叫"前向传播"。
    """

    # ── 数据增强（augmentation）──────────────────────────────
    # 【这是什么？】在训练时，把每张图**随机**做点小改动（转一点、缩一点、挪一点），
    # 再喂给网络。目的是让网络别死记硬背"这张图长这样"，
    # 而是学"这类手势大致长什么样"。
    # ⚠️ 注意：这些改动只在【训练时】发生，验证集和实际使用时都是原图。
    augment = keras.Sequential(
        [
            layers.RandomRotation(0.12),                 # 随机旋转 ±约 43°
            layers.RandomZoom(0.12),                     # 随机缩放
            layers.RandomTranslation(0.08, 0.08),        # 随机平移
        ],
        name="augment",
    )

    model = keras.Sequential(
        [
            # 输入层：声明"我吃的是一张 64x64、1 个通道的图"
            layers.Input(shape=(IMG_SIZE, IMG_SIZE, 1), name="image"),
            augment,

            # ── 第 1 组：卷积 + 池化 ──────────────────────────
            # Conv2D(16, 3) 的两个参数：
            #   16 = 用 16 个不同的卷积核（= 16 种要寻找的局部图案）
            #    3 = 每个卷积核是 3x3 的小窗口
            # padding="same" = 用 0 补边，让输出的宽高跟输入一样（保持 64x64）
            # activation="relu" = 负数归零、正数保留。
            #   【为什么需要它？】如果没有这种非线性，一摞卷积层在数学上
            #   等价于"一个卷积层"，再深也没用。ReLU 是让深度变得有意义的关键。
            layers.Conv2D(16, 3, padding="same", activation="relu", name="conv1"),
            # MaxPooling2D(2)：每 2x2 个格子只留最大的那个 → 图从 64x64 变 32x32。
            # 【为什么取最大而不是平均？】最大 = "这个区域里有没有出现我要找的图案"。
            #   取最大还有个好处：图案稍微挪个位置，最大值几乎不变 → 平移不变性。
            layers.MaxPooling2D(2, name="pool1"),

            # ── 第 2 组：通道数从 16 加到 32 ───────────────────
            # 【为什么越往深层通道越多？】浅层找的是边缘这种简单图案（不需要很多种）；
            # 深层要找的是"几根手指这样排"这种复杂组合，可能性多得多，所以要更多通道。
            layers.Conv2D(32, 3, padding="same", activation="relu", name="conv2"),
            layers.MaxPooling2D(2, name="pool2"),            # 32x32 → 16x16

            # ── 第 3 组：48 个通道 ─────────────────────────────
            layers.Conv2D(48, 3, padding="same", activation="relu", name="conv3"),
            layers.MaxPooling2D(2, name="pool3"),            # 16x16 → 8x8

            # ── 从"图"变成"一串数" ────────────────────────────
            # Flatten：把 8x8x48 的三维块拉直成 8*8*48 = 3072 个数的一维向量。
            # 因为全连接层只认一维向量，不认二维特征图。
            layers.Flatten(name="flatten"),

            # ── 全连接层：把"看到的部件"组合成判据 ─────────────
            # Dense(64) = 64 个神经元，每个都跟上面 3072 个数全部相连。
            # 【这就是参数爆炸的地方】3072 x 64 + 64 = 196,672 个参数，
            # 占整个网络的 91%。跑完看 summary 就知道了。
            layers.Dense(64, activation="relu", name="fc1"),

            # Dropout(0.3)：训练时**随机**把 30% 的神经元临时关掉。
            # 【为什么？】防止网络过度依赖某几个神经元的组合（过拟合）。
            #   每次都随机关掉一些，逼它学出更鲁棒的特征。
            #   同样只在训练时生效，用的时候全部打开。
            layers.Dropout(0.3, name="dropout"),

            # ── 输出层：3 个类别 ──────────────────────────────
            # Dense(n_classes) 输出 3 个分数，Softmax 把它们压成"加起来等于 1"的概率。
            # 比如 [0.05, 0.90, 0.05] = "90% 是手掌"。
            layers.Dense(n_classes, activation="softmax", name="prob"),
        ],
        name="gesture_cnn",
    )

    # compile = 告诉 Keras"用什么规则学"。这一步还不会开始学，只是配置。
    model.compile(
        # 优化器 Adam：决定"每个旋钮具体怎么挪"的算法。
        # learning_rate=1e-3 = 0.001，就是"每次挪多大一步"。
        #   太大 → 一步迈过头，来回震荡甚至发散；
        #   太小 → 走得太慢，训练半天没进展。1e-3 是常用起点。
        optimizer=keras.optimizers.Adam(learning_rate=1e-3),

        # 损失函数：衡量"预测和正确答案差多远"的那把尺子。
        # sparse_categorical_crossentropy 专门用于"标签是整数 0/1/2 的多分类"。
        # 【交叉熵的直觉】正确答案那一类的预测概率越低，惩罚越大。
        #   预测 [0.9, 0.05, 0.05] 而正确答案是第 0 类 → 损失小；
        #   预测 [0.1, 0.8, 0.1] 而正确答案是第 0 类 → 损失大。
        loss="sparse_categorical_crossentropy",

        # 训练过程中额外想看的指标。accuracy = 猜对的比例。
        metrics=["accuracy"],
    )
    return model


# ────────────────────────────────────────────────────────────────
# ④ 评估用的两个小工具
# ────────────────────────────────────────────────────────────────
def confusion_matrix(y_true, y_pred, n):
    """手工算混淆矩阵。cm[真实][预测] 记个数。

    【混淆矩阵在说什么？】它是 n x n 的表：
        行 = 这张图的**真实**类别
        列 = 模型**预测**的类别
    对角线上的数 = 猜对的次数；对角线以外的数 = 猜错，而且能看出"错成了什么"。

    例：cm[2][0] = 5 表示"有 5 张真实的剪刀手，被误判成了拳头"。
    这张表比一个"准确率 99%"有用得多 —— 准确率会骗人，混淆矩阵不会。
    """
    cm = np.zeros((n, n), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    return cm


def per_class_report(cm):
    """从混淆矩阵算出每个类别的 precision / recall / F1。

    【三个指标的中文意思】
      precision（精确率）= 我判为"拳头"的那些里，有多少真的是拳头？
                          → 衡量"我报出来的准不准"
      recall（召回率）   = 真实是"拳头"的那些里，我抓出来多少？
                          → 衡量"我漏没漏"

    这两个指标经常互相矛盾，所以有个综合分：
      F1 = 两者的调和平均。F1 高说明两者都还不错。

    【为什么要逐类看？】总体准确率 90% 可能是"fist 全对、另两类各错一半"。
    逐类看才知道弱点在哪 —— 这也是报告里"评估诚实性"的体现。
    """
    lines = []
    n = cm.shape[0]
    for i in range(n):
        tp = cm[i, i]                  # 真阳性：真的是 i，也判成了 i（对角线上）
        fp = cm[:, i].sum() - tp       # 假阳性：不是 i，却被判成 i（这一列除了对角线）
        fn = cm[i, :].sum() - tp       # 假阴性：真的是 i，却没判成 i（这一行除了对角线）
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        lines.append((CLASSES[i], int(cm[i].sum()), prec, rec, f1))
    return lines


# ────────────────────────────────────────────────────────────────
# ⑤ 主流程：按顺序把上面这些串起来
# ────────────────────────────────────────────────────────────────
def main():
    # exist_ok=True = 文件夹已存在也不报错
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    # 把所有随机源（初始化权重、打乱顺序、数据增强）都固定到同一个种子。
    # 【为什么重要？】报告里说"准确率 98%"，别人要能复现。不固定种子就做不到。
    keras.utils.set_random_seed(SEED)

    print("=" * 66)
    print("MP3000 / YZ3 试跑 · 训练手势 CNN")
    print("=" * 66)

    # ── 读数据 ──
    X, y, per_class = load_dataset()
    print("数据加载完成：")
    for c in CLASSES:
        print("  %-9s %4d 张" % (c, per_class[c]))
    print("  合计      %4d 张，图像尺寸 %dx%d 灰度" % (len(y), IMG_SIZE, IMG_SIZE))

    # ── 切分 ──
    tr, va = stratified_split(y, VAL_RATIO, SEED)
    print("划分：训练 %d 张 / 验证 %d 张（验证集训练时完全不看）" % (len(tr), len(va)))

    # 用下标数组去"切片"，得到真正的两组数据
    Xtr, ytr = X[tr], y[tr]     # 训练用
    Xva, yva = X[va], y[va]     # 验证用（下面 fit 时只用于"考试"，不参与调参）

    # ── 搭网络 ──
    model = build_model(len(CLASSES))
    model.summary()      # 打印每一层的输出形状和参数量 —— 【值得你逐行看一遍】
    n_params = int(model.count_params())
    print("模型参数量：%d 个（这就是这个「大脑」的全部可调旋钮）" % n_params)

    # ── 早停（EarlyStopping）──
    # 【它解决什么问题？】训练轮数设了 40，但可能第 12 轮就到最好成绩，
    # 后面全是白跑，而且会开始过拟合（训练集越来越准、验证集反而变差）。
    #   monitor="val_accuracy"      → 盯着验证集准确率
    #   patience=8                  → 连续 8 轮没进步就停
    #   restore_best_weights=True   → 【关键】不保留最后一轮的权重，
    #                                 而是回滚到历史上验证准确率最高的那一轮
    callbacks = [
        keras.callbacks.EarlyStopping(
            monitor="val_accuracy", patience=8, restore_best_weights=True, verbose=1
        )
    ]

    # ══════════════════════════════════════════════════════════════
    # ★★★ 这一行就是"训练"本身 ★★★
    # ══════════════════════════════════════════════════════════════
    # fit 内部在反复做四件事（一轮 = 把所有训练图过一遍）：
    #   ① 取一个 batch（32 张图）
    #   ② 前向：算出 32 组预测概率
    #   ③ 算损失：跟正确答案比，得到一个"有多错"的数
    #   ④ 反向：算出 215,539 个参数各自的梯度，每个朝下坡方向挪一小步
    # 重复直到所有训练图走完 = 1 个 epoch。
    #
    #   参数说明：
    #     validation_data=(Xva, yva) → 每轮结束后在验证集上"考一次"，只看分数，不调参
    #     verbose=2                  → 每轮打印一行进度
    # ══════════════════════════════════════════════════════════════
    history = model.fit(
        Xtr, ytr,
        validation_data=(Xva, yva),
        epochs=EPOCHS,
        batch_size=BATCH,
        verbose=2,
        callbacks=callbacks,
    )

    # ---------------- 评估（用模型没见过的验证集） ----------------
    val_loss, val_acc = model.evaluate(Xva, yva, verbose=0)

    # predict 返回的是每张图的三类概率，形状 (N, 3)，比如 [[0.05, 0.90, 0.05], ...]
    probs = model.predict(Xva, verbose=0)
    # argmax(axis=1) = 每一行里"最大的那个在哪一列" → 就是预测的类别编号
    y_pred = probs.argmax(axis=1)

    cm = confusion_matrix(yva, y_pred, len(CLASSES))
    rows = per_class_report(cm)

    print("-" * 66)
    print("验证集结果：")
    print("  总体准确率 accuracy = %.4f  （%d / %d）" % (val_acc, (y_pred == yva).sum(), len(yva)))
    print("  逐类表现：")
    for name, support, p, r, f in rows:
        print("    %-9s 样本%4d  precision=%.3f  recall=%.3f  F1=%.3f" % (name, support, p, r, f))
    print("  混淆矩阵（行=真实，列=预测）：")
    print("            " + "".join("%10s" % c for c in CLASSES))
    for i, c in enumerate(CLASSES):
        print("    %-9s" % c + "".join("%10d" % v for v in cm[i]))
    print("-" * 66)

    # ---------------- 保存模型 ----------------
    # .keras 是 Keras 3 的原生格式，一个文件里含结构 + 权重。
    # 03_live_demo.py 会把这个文件读回来做实时识别。
    model_path = os.path.join(MODEL_DIR, "gesture_cnn.keras")
    model.save(model_path)
    print("模型已保存：%s" % model_path)

    # ---------------- 画图（报告里直接用这两张） ----------------
    # 图 1：准确率曲线 + 损失曲线（左、右两个子图）
    # 【这两张图怎么看？】
    #   两条线都往上（准确率）/ 往下（损失）→ 正常在学习
    #   训练线一直涨、验证线走平或下降   → 过拟合了，模型开始死记硬背
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(history.history["accuracy"], label="train")
    axes[0].plot(history.history["val_accuracy"], label="val")
    axes[0].set_title("Accuracy per epoch")
    axes[0].set_xlabel("epoch")
    axes[0].set_ylabel("accuracy")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    axes[1].plot(history.history["loss"], label="train")
    axes[1].plot(history.history["val_loss"], label="val")
    axes[1].set_title("Loss per epoch")
    axes[1].set_xlabel("epoch")
    axes[1].set_ylabel("loss")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    curves_path = os.path.join(REPORT_DIR, "training_curves.png")
    fig.savefig(curves_path, dpi=140)
    plt.close(fig)

    # 图 2：混淆矩阵热力图
    # 【怎么看？】理想情况是"对角线上又深又大，其他地方全是 0"。
    #   如果某个格子数很大，就说明这两类被混淆了 —— 这才是要分析的地方。
    fig2, ax2 = plt.subplots(figsize=(5.2, 4.4))
    im = ax2.imshow(cm, cmap="Blues")
    ax2.set_xticks(range(len(CLASSES)))
    ax2.set_xticklabels(CLASSES, rotation=20)
    ax2.set_yticks(range(len(CLASSES)))
    ax2.set_yticklabels(CLASSES)
    ax2.set_xlabel("predicted")
    ax2.set_ylabel("true")
    ax2.set_title("Confusion matrix (validation set)")
    # 在每个格子里写上数字，并按背景深浅自动选黑字/白字，保证看得清
    for i in range(len(CLASSES)):
        for j in range(len(CLASSES)):
            ax2.text(j, i, str(cm[i, j]), ha="center", va="center",
                     color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig2.colorbar(im, ax=ax2)
    fig2.tight_layout()
    cm_path = os.path.join(REPORT_DIR, "confusion_matrix.png")
    fig2.savefig(cm_path, dpi=140)
    plt.close(fig2)
    print("图已保存：%s / %s" % (curves_path, cm_path))

    # ---------------- 落盘指标 ----------------
    # 把这些数字写成 json/txt，是为了报告里引用时"有据可查"，
    # 而不是靠回忆或手抄（手抄很容易抄错，而且不可复现）。
    metrics = {
        "classes": CLASSES,
        "images_per_class": per_class,
        "train_size": int(len(tr)),
        "val_size": int(len(va)),
        "img_size": IMG_SIZE,
        "params": n_params,
        "epochs_run": len(history.history["loss"]),   # 实际跑了几轮（可能早停了）
        "val_accuracy": float(val_acc),
        "val_loss": float(val_loss),
        "per_class": [
            {"class": n, "support": s, "precision": p, "recall": r, "f1": f}
            for (n, s, p, r, f) in rows
        ],
        "confusion_matrix": cm.tolist(),
    }
    with open(os.path.join(REPORT_DIR, "metrics.json"), "w", encoding="utf-8") as fp:
        json.dump(metrics, fp, ensure_ascii=False, indent=2)

    # 同内容的给人读版本（纯文本，方便直接抄进报告）
    with open(os.path.join(REPORT_DIR, "metrics.txt"), "w", encoding="utf-8") as fp:
        fp.write("MP3000 / YZ3 试跑 · 手势 CNN 训练结果\n")
        fp.write("=" * 50 + "\n")
        fp.write("数据：%s\n" % ", ".join("%s=%d" % (c, per_class[c]) for c in CLASSES))
        fp.write("训练/验证：%d / %d\n" % (len(tr), len(va)))
        fp.write("模型参数量：%d\n" % n_params)
        fp.write("训练轮数：%d\n" % len(history.history["loss"]))
        fp.write("验证集准确率：%.4f\n" % val_acc)
        fp.write("\n逐类表现：\n")
        for name, support, p, r, f in rows:
            fp.write("  %-9s n=%4d  P=%.3f  R=%.3f  F1=%.3f\n" % (name, support, p, r, f))
        fp.write("\n混淆矩阵（行=真实，列=预测）：\n")
        fp.write("           " + "".join("%10s" % c for c in CLASSES) + "\n")
        for i, c in enumerate(CLASSES):
            fp.write("  %-9s" % c + "".join("%10d" % v for v in cm[i]) + "\n")
    print("指标已保存：%s" % os.path.join(REPORT_DIR, "metrics.txt"))
    print("\n下一步：python 03_live_demo.py   （打开摄像头做实时识别）")
    return 0


# 这个写法是 Python 的惯例：只有"直接运行这个文件"时才执行 main()，
# 被别人 import 时不执行。所以 00_selftest.py 可以安全地 import 它来复用函数。
if __name__ == "__main__":
    raise SystemExit(main())
