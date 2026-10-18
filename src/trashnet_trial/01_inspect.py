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
    except Exception as e:  # noqa: BLE001
        bad.append((str(p.relative_to(DATA)), str(e)))

total = sum(counts.values())
print(f"根目录: {DATA}")
print(f"存在: {DATA.is_dir()}")
print(f"总计 {total} 张，{len(counts)} 类\n")

for cls, n in counts.most_common():
    print(f"  {cls:<12} {n:>5}  {n / total:6.1%}")

print(f"\n图片尺寸分布（前 5）: {sizes.most_common(5)}")
print(f"坏图: {len(bad)}")
for name, err in bad[:10]:
    print(f"  {name}: {err}")

if bad:
    print("\n⚠️ 有坏图，训练时会报错 —— 手工删掉或移走它们")
else:
    print("\n✅ 没有坏图")
