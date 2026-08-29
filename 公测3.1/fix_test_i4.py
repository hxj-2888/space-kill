# -*- coding: utf-8 -*-
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = 'verify_infection.py'
s = io.open(f, encoding='utf-8').read()
i = s.find("check('I4")
j = s.find("'\n", i) if i >= 0 else -1
# 直接重写整个 I4 断言行块
lines = s.split('\n')
out = []
for line in lines:
    if line.startswith("check('I4"):
        out.append("check('I4 生化无救援能力→转治疗（每晚一记出手）',")
        out.append("      hu1.dying is True and hu2.infection == 0 and doc.doctor_treat == treat_before - 1,")
        out.append("      'hu1.dying=%s hu2.infection=%s treat=%s' % (hu1.dying, hu2.infection, doc.doctor_treat))")
    else:
        out.append(line)
io.open(f, 'w', encoding='utf-8', newline='').write('\n'.join(out))
print('test fixed')
