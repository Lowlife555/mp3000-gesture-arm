"""渲染 Cebek C-9895.2 英文手册的关键页（零件表 / 接线 / 供电）为 PNG。"""
import os
import fitz

SRC = r"C:\Users\<you>\Desktop\普雷斯顿生存指南\笔记库\2_课业笔记\MP3000_毕业设计\机械臂资料\CD_Driver\CD1\C-9895.2  Eng\C-9895.2-ing..pdf"
OUT = r"C:\Users\<you>\Desktop\普雷斯顿生存指南\_中间产物\MP3000\机械臂资料提取\C-9895.2-ing_pages"
os.makedirs(OUT, exist_ok=True)

PAGES = [1, 2, 3, 4, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 27, 28]

doc = fitz.open(SRC)
for pno in PAGES:
    if pno - 1 >= doc.page_count:
        continue
    pix = doc[pno - 1].get_pixmap(dpi=120)
    dest = os.path.join(OUT, f'p{pno:02d}.png')
    pix.save(dest)
    print('OK', dest)
doc.close()
