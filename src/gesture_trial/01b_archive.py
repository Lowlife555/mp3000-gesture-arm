# -*- coding: utf-8 -*-
"""
把上一轮采集的数据 / 模型 / 报告改名存档 —— 重新开始前的第一步。
====================================================================
为什么必须存档，而不是直接删掉重采：
  1. 新旧数据混在同一个 data/ 里，重训时会把脏数据一起学进去，等于白采；
  2. 这批坏数据是很好的"反面教材" —— 验证集 99% 而现场全错，
     讲给老师听比讲 Softmax 有价值得多（见 07 文档第 5 节）。

用法：
    python 01b_archive.py            # 真的存档
    python 01b_archive.py --dry-run  # 只看会做什么，不动文件

每运行一次生成一个带时间戳的新存档目录，绝不会覆盖上一次的存档。
"""

import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# (要存档的目录, 存档名前缀)
TARGETS = [
    ("data", "data_badrun"),
    ("models", "models_badrun"),
    ("reports", "reports_badrun"),
]


def count_files(path):
    n = 0
    for _, _, files in os.walk(path):
        n += len(files)
    return n


def main():
    dry = "--dry-run" in sys.argv
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 60)
    print("存档上一轮产物" + ("（演练模式，不会真的动文件）" if dry else ""))
    print("时间戳：%s" % stamp)
    print("-" * 60)

    moved = 0
    for src, prefix in TARGETS:
        s = os.path.join(HERE, src)
        if not os.path.isdir(s):
            print("  [跳过] %-8s 不存在" % src)
            continue
        n = count_files(s)
        if n == 0:
            print("  [跳过] %-8s 是空的（没什么可存档）" % src)
            continue
        dst_name = "%s_%s" % (prefix, stamp)
        dst = os.path.join(HERE, dst_name)
        if os.path.exists(dst):
            print("  [跳过] %-8s 目标 %s 已存在" % (src, dst_name))
            continue
        if dry:
            print("  [将存档] %-8s -> %s  (%d 个文件)" % (src, dst_name, n))
        else:
            os.rename(s, dst)
            print("  [已存档] %-8s -> %s  (%d 个文件)" % (src, dst_name, n))
        moved += 1

    print("-" * 60)
    if moved == 0:
        print("没有任何目录被存档。直接开始采集即可（data/ 会是全新的）。")
    else:
        print("完成 %d 个目录。" % moved)
        print("下一步：启动 01_capture.py 采集新数据。")
        print("牢记三条：① 手要占满右下角小图 ② 三类交错采 ③ std<20 就停手调整")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
