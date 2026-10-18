"""
00 分层划分：把 dataset-resized 按【类别】各抽 15% 到 trashnet_split/val，
   其余放 trashnet_split/train。

⚠️ 为什么不用 image_dataset_from_directory(validation_split=...)
   它的 validation_split 是对「排序后的文件总表」做全局切片，不按类别分层；
   而且 subset="validation" 会强制 shuffle=False，于是那 15% 永远是文件表末尾的
   同一批类 —— 实测就拿不到 cardboard/glass/metal/paper 的验证样本。
   所以这里自己按类分层切，保证每一类都有验证样本。
"""
import collections
import pathlib
import random
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "trashnet" / "dataset-resized"
DST = ROOT / "data" / "trashnet_split"
VAL_RATIO = 0.15
SEED = 1337
EXT = {".jpg", ".jpeg", ".png"}

rng = random.Random(SEED)

if not SRC.is_dir():
    raise SystemExit(f"找不到源数据: {SRC}")

have = [d for d in (DST / "train", DST / "val") if d.is_dir()]
if len(have) == 2:
    print(f"划分目录已存在，跳过拷贝: {DST}")
else:
    print(f"源: {SRC}")
    print(f"目标: {DST}  (每类抽 {VAL_RATIO:.0%} 做验证)\n")
    for cls_dir in sorted(p for p in SRC.iterdir() if p.is_dir()):
        files = sorted((f for f in cls_dir.iterdir() if f.suffix.lower() in EXT),
                       key=lambda p: p.name)
        rng.shuffle(files)
        n_val = max(1, round(len(files) * VAL_RATIO))
        val_files, train_files = files[:n_val], files[n_val:]
        for split, subset in (("train", train_files), ("val", val_files)):
            out = DST / split / cls_dir.name
            out.mkdir(parents=True, exist_ok=True)
            for f in subset:
                shutil.copy2(f, out / f.name)
        print(f"  {cls_dir.name:<11} train={len(train_files):4d}  val={len(val_files):3d}")

print("\n=== 汇总 ===")
for split in ("train", "val"):
    total = 0
    per = collections.OrderedDict()
    for cls_dir in sorted(p for p in (DST / split).iterdir() if p.is_dir()):
        n = len([f for f in cls_dir.iterdir() if f.suffix.lower() in EXT])
        per[cls_dir.name] = n
        total += n
    print(f"  {split}: 合计 {total} 张")
    for k, v in per.items():
        print(f"    {k:<11} {v:4d}")
