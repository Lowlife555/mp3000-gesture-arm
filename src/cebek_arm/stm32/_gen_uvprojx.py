#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 CebekArm.uvprojx
=====================
不从零手写 Keil 工程 XML（FlashDriverDll、IROM/IRAM、Cpu 串这些极易写错），
而是**复用已在本机编译成功的 wellspan `new.uvprojx` 的骨架**，只替换：
  · <Groups>        ← 本脚本的源文件清单
  · <Define>        ← STM32L476xx（去掉 USE_HAL_DRIVER）
  · <IncludePath>   ← .\\cmsis;.
  · <OutputName>    ← CebekArm
  · <TargetName>    ← CebekArm
  · <RTE>           ← 清空（不使用 RTE 组件，头文件全部在 cmsis/ 里）
这样 <TargetCommonOption>、<TargetArmAds>、<LDads> 等关键段原样保留。

用法：  python _gen_uvprojx.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Keil 工程骨架的来源。
# 不从零手写 uvprojx（FlashDriverDll、IROM/IRAM、Cpu 串这些极易写错），
# 而是复用一个"已经在本机编译成功"的同型号 MDK5 工程，只替换文件清单与选项。
# 为避免把个人目录写进仓库，这里从环境变量读；没有就找同目录下的 template/。
#     Windows:  set CEBEK_UVPROJX_TEMPLATE=D:\path\to\any_working.uvprojx
#     Linux  :  export CEBEK_UVPROJX_TEMPLATE=/path/to/any_working.uvprojx
TEMPLATE = os.environ.get(
    "CEBEK_UVPROJX_TEMPLATE",
    os.path.join(HERE, "template", "uvprojx_skeleton.xml"),
)
OUT = os.path.join(HERE, "CebekArm.uvprojx")
TARGET = "CebekArm"

# ── 源文件清单 ──────────────────────────────────────────────
# (组名, [(显示名, FileType, 相对路径)])
#   FileType: 1=C, 2=ASM, 5=其他
GROUPS = [
    ("Startup", [
        ("startup_stm32l476xx.s", 2, "startup_stm32l476xx.s"),
    ]),
    ("Core", [
        ("system.c", 1, "system.c"),
        ("main.c", 1, "main.c"),
        ("clock.c", 1, "clock.c"),
        ("delay.c", 1, "delay.c"),
        ("uart2.c", 1, "uart2.c"),
    ]),
    ("Drivers", [
        ("lcd.c", 1, "lcd.c"),
        ("keys.c", 1, "keys.c"),
        ("ui.c", 1, "ui.c"),
        ("arm.c", 1, "arm.c"),
    ]),
    ("Headers", [
        ("board_pins.h", 5, "board_pins.h"),
        ("font_data.h", 5, "font_data.h"),
    ]),
]

# 只生成存在的文件，避免 Keil 报"找不到源文件"
def existing_groups():
    out = []
    for name, files in GROUPS:
        keep = []
        for disp, ftype, path in files:
            if os.path.exists(os.path.join(HERE, path.replace("\\", os.sep))):
                keep.append((disp, ftype, path))
            else:
                print("  跳过（文件尚未创建）：%s" % path)
        if keep:
            out.append((name, keep))
    return out


def build_groups_xml(groups):
    parts = ["      <Groups>"]
    for name, files in groups:
        parts.append("        <Group>")
        parts.append("          <GroupName>%s</GroupName>" % name)
        parts.append("          <Files>")
        for disp, ftype, path in files:
            parts.append("            <File>")
            parts.append("              <FileName>%s</FileName>" % disp)
            parts.append("              <FileType>%d</FileType>" % ftype)
            parts.append("              <FilePath>%s</FilePath>" % path)
            parts.append("            </File>")
        parts.append("          </Files>")
        parts.append("        </Group>")
    parts.append("      </Groups>")
    return "\n".join(parts)


def main():
    if not os.path.exists(TEMPLATE):
        print("找不到工程骨架：%s" % TEMPLATE)
        print()
        print("这个脚本是可选的 —— 仓库里已经有一份能直接编译的 CebekArm.uvprojx。")
        print("只有需要重新生成文件清单时才用得到它。用法：")
        print("    设置环境变量 CEBEK_UVPROJX_TEMPLATE 指向任意一个")
        print("    能在本机编译成功的 Keil MDK5 工程 (.uvprojx)，然后重跑。")
        return 1
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        txt = f.read()

    groups = existing_groups()
    if not groups:
        print("没有任何源文件存在，先创建源文件。")
        return 1

    n_before = len(txt)

    # 1) Groups：贪婪替换整个 blocks（文档里只有一个 <Groups>）
    txt, n1 = re.subn(r"[ \t]*<Groups>.*?</Groups>", build_groups_xml(groups),
                      txt, count=1, flags=re.S)
    # 2) Define
    txt, n2 = re.subn(r"<Define>[^<]*</Define>", "<Define>STM32L476xx</Define>", txt)
    # 3) IncludePath（注意：替换串里必须用 \\ 转义反斜杠，否则 re 会把 \c 当坏转义）
    txt, n3 = re.subn(r"<IncludePath>[^<]*</IncludePath>",
                      r"<IncludePath>.\\cmsis;.</IncludePath>", txt)
    # 4) 输出名
    txt, n4 = re.subn(r"<OutputName>[^<]*</OutputName>",
                      "<OutputName>%s</OutputName>" % TARGET, txt)
    # 5) 目标名
    txt, n5 = re.subn(r"<TargetName>[^<]*</TargetName>",
                      "<TargetName>%s</TargetName>" % TARGET, txt)
    txt, n5b = re.subn(r'<targetInfo name="[^"]*"\s*/>',
                       '<targetInfo name="%s"/>' % TARGET, txt)
    # 6) 清空 RTE（不用 pack 里的组件）
    txt, n6 = re.subn(r"<RTE>.*?</RTE>",
                      "<RTE>\n        <apis/>\n        <components/>\n        <files/>\n      </RTE>",
                      txt, count=1, flags=re.S)

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)

    print("已生成 %s" % OUT)
    print("  Groups 替换 %d 处，共 %d 个组 / %d 个文件"
          % (n1, len(groups), sum(len(g[1]) for g in groups)))
    print("  Define=%d  IncludePath=%d  OutputName=%d  TargetName=%d+%d  RTE=%d"
          % (n2, n3, n4, n5, n5b, n6))
    print("  长度 %d → %d 字符" % (n_before, len(txt)))

    # 自检：XML 能否解析
    try:
        import xml.etree.ElementTree as ET
        ET.parse(OUT)
        print("  XML 解析：通过 ✓")
    except Exception as e:
        print("  XML 解析失败 ✗ %r" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
