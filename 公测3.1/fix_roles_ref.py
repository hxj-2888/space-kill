# -*- coding: utf-8 -*-
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = '太空杀_公测3.1_模拟代码.py'
s = io.open(f, encoding='utf-8').read()
old = "_spec.loader.exec_module(sim30)"
new = "_spec.loader.exec_module(sim30)\nHUMAN_ROLES = sim30.HUMAN_ROLES  # 裁判层角色表（覆写方法引用）"
assert old in s
s = s.replace(old, new, 1)
io.open(f, 'w', encoding='utf-8', newline='').write(s)
print('HUMAN_ROLES exported')
