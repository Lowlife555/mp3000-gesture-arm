"""从机械臂资料 PDF 提取文本；若疑似扫描件（文字量过少）则渲染页面 PNG 供视觉阅读。"""
import os
import fitz

SRC = r"C:\Users\<you>\Desktop\普雷斯顿生存指南\笔记库\2_课业笔记\MP3000_毕业设计\机械臂资料"
OUT = r"C:\Users\<you>\Desktop\普雷斯顿生存指南\_中间产物\MP3000\机械臂资料提取"
os.makedirs(OUT, exist_ok=True)

pdfs = []
for dp, dn, fn in os.walk(SRC):
    for f in fn:
        if f.lower().endswith('.pdf'):
            pdfs.append(os.path.join(dp, f))

print('found', len(pdfs), 'pdfs')
for p in pdfs:
    name = os.path.splitext(os.path.basename(p))[0]
    try:
        doc = fitz.open(p)
    except Exception as e:
        print('ERR open', name, e)
        continue
    parts = []
    for i, page in enumerate(doc):
        parts.append(f'\n===== page {i+1} =====\n' + page.get_text())
    text = ''.join(parts)
    real = len(text.replace('=', '').replace('page', '').strip())
    dest = os.path.join(OUT, name + '.txt')
    with open(dest, 'w', encoding='utf-8') as f:
        f.write(f'来源: {p}\n页数: {doc.page_count}\n' + '-' * 60 + '\n' + text)
    print(f'OK   {name}  pages={doc.page_count}  chars={len(text)}  real~{real}')
    if real < 600:
        print('     -> 疑似扫描件，渲染页面 PNG')
        imgdir = os.path.join(OUT, name + '_pages')
        os.makedirs(imgdir, exist_ok=True)
        n = min(doc.page_count, 30)
        for i in range(n):
            pix = doc[i].get_pixmap(dpi=110)
            pix.save(os.path.join(imgdir, f'p{i+1:02d}.png'))
        print(f'     -> 已渲染 {n} 页到 {imgdir}')
    doc.close()
