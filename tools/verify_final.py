# -*- coding: utf-8 -*-
import re, io
f = r'C:\Users\<you>\Desktop\普雷斯顿生存指南\笔记库\2_课业笔记\MP3000_毕业设计\2026-10-08_ProposalForm_逐栏填写草稿.md'
t = io.open(f, encoding='utf-8').read()
F = chr(96) * 3

print('=== 章节骨架（应为 8 栏 + 3 Part + 2 附录 + 2 收尾）===')
for ln, line in enumerate(t.split('\n'), 1):
    if re.match(r'^#{1,3} ', line):
        print('  {0:>4}  {1}'.format(ln, line[:70]))

print()
print('=== 词数实测 ===')
def wc(start, end):
    i = t.index(start)
    j = t.index(end, i)
    b = max(re.findall(F + r'(.*?)' + F, t[i:j], re.S), key=len)
    return len([w for w in b.split() if re.search(r'\w', w)])
ao = wc('## \u680f 6', '\U0001f1e8\U0001f1f3 \u4e2d\u6587\u5bf9\u7167**')
iw = wc('## \u680f 7', '\U0001f1e8\U0001f1f3 \u4e2d\u6587\u5bf9\u7167\uff08')
print('  Aims & Objectives :', ao, '(\u2264150)', 'OK' if ao <= 150 else 'OVER')
print('  Brief Introduction:', iw, '(100\u2013120)', 'OK' if 100 <= iw <= 120 else 'OUT')

print()
print('=== 关键标注行 ===')
keys = ['\u7bc7\u5e45\u5b9e\u6d4b', 'Q4 \u7814\u7a76\u63cf\u8ff0', 'Introduction **', '| \u6587\u732e |']
for k in keys:
    for line in t.split('\n'):
        if k in line:
            print('  ', line.strip()[:150]); break
    else:
        print('   [MISSING]', k)

print()
print('=== 旧内容残留检查（应全为 0）===')
stale = {
    'old EN "almost every laptop"': t.count('almost every laptop'),
    'old EN "Most previous work"': t.count('Most previous work'),
    'old CN "\u51e0\u4e4e\u5185\u7f6e\u5728\u6bcf\u53f0\u7b14\u8bb0\u672c"': t.count('\u51e0\u4e4e\u5185\u7f6e\u5728\u6bcf\u53f0\u7b14\u8bb0\u672c'),
    'old note "\u5fc5\u987b\u6362\u6210\u771f\u5b9e\u6587\u732e"': t.count('\u5fc5\u987b\u6362\u6210\u771f\u5b9e\u6587\u732e'),
    '{AOW}/{IWW}': t.count('{AOW}') + t.count('{IWW}'),
    '@N@': t.count('@N@'),
    'old "This project will"': t.count('This project will'),
}
for k, v in stale.items():
    print('  {0:<45} {1}  {2}'.format(k, v, 'OK' if v == 0 else '<-- CHECK'))

print()
print('=== 四个关键词（Introduction 内）===')
i = t.index('## \u680f 7'); j = t.index('\U0001f1e8\U0001f1f3 \u4e2d\u6587\u5bf9\u7167\uff08', i)
body = max(re.findall(F + r'(.*?)' + F, t[i:j], re.S), key=len)
for kw in ('webcam', 'gesture', 'neural network', 'robotic arm'):
    print('  {0:<15} {1}'.format(kw, 'YES' if kw in body.lower() else 'NO'))
print('  \u7b2c\u4e00\u4eba\u79f0 I/My:', 'YES' if re.search(r'\b(I|my)\b', body) else 'NO')
print('  \u53e5\u5b50\u6570(\u53e5\u53f7):', body.count('.'))
print('  \u6bb5\u843d\u6570:', len([p for p in body.split('\n\n') if p.strip()]))
print()
print('\u603b\u884c\u6570:', t.count('\n') + 1, '| \u5b57\u8282:', len(t.encode('utf-8')))
