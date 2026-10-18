import re, io

d = r'C:\Users\<you>\Desktop\普雷斯顿生存指南\笔记库\2_课业笔记\MP3000_毕业设计\2026-10-08_ProposalForm_逐栏填写草稿.md'
t = io.open(d, encoding='utf-8').read()
FENCE = chr(96) * 3

i = t.index('## 栏 7')
j = t.index('**\U0001f1e8\U0001f1f3 \u4e2d\u6587\u5bf9\u7167', i)
seg = t[i:j]
blocks = re.findall(FENCE + r'(.*?)' + FENCE, seg, re.S)
body = max(blocks, key=len).replace('[\u5f15\u7528]', 'REF')
n = len([w for w in body.split() if re.search(r'\w', w)])

# 把注释里写错的 112 统一改成实测值
fixed = t.replace('112 \u8bcd', '%d \u8bcd' % n)
io.open(d, 'w', encoding='utf-8', newline='\n').write(fixed)

print('=== Brief Introduction 实测 ===')
print('词数:', n, '(你要求 <=120) ->', 'OK' if n <= 120 else 'OVER')
for k in ('webcam', 'gesture', 'neural network', 'robotic arm'):
    print('  关键词 {0:<15} {1}'.format(k, 'YES' if k in body.lower() else 'NO'))
print()
print('=== 数字一致性 ===')
for line in fixed.split('\n'):
    if '\u8bcd' in line and ('\u7bc7\u5e45\u5b9e\u6d4b' in line or 'Q4' in line or line.startswith('- [ ] Introduction') or line.startswith('## \u680f 7')):
        print(' ', line.strip())
print()
print('残留 "112 \u8bcd":', fixed.count('112 \u8bcd'))
print('残留 "295 \u8bcd":', fixed.count('295 \u8bcd'))
print('残留占位符 {AOW}/{IWW}:', fixed.count('{AOW}') + fixed.count('{IWW}'))
print('总行数:', fixed.count('\n') + 1)
