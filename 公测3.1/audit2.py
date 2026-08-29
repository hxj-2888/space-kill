# -*- coding: utf-8 -*-
import io
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
rules = io.open('../公测3.0/太空杀_公测3.0_规则.md', encoding='utf-8').read()
code30 = io.open('../公测3.0/太空杀_公测3.0_模拟代码.py', encoding='utf-8').read()
code31 = io.open('太空杀_公测3.1_模拟代码.py', encoding='utf-8').read()

checks = []
def check(name, ok, detail=''):
    checks.append((name, ok))
    print(('PASS' if ok else 'FAIL') + '  ' + name + ('  ' + detail if detail else ''))

check('第10夜免疫（3.0 裁判 night>=10）', 'self.night >= 10' in code30)
check('第10夜免疫全局1次（3.0 foreigner_night10_granted）', 'foreigner_night10_granted' in code30)
check('补刀第4夜（规则粗体）', '第 **4** 夜起方可补刀' in rules)
check('外星濒死第1夜补刀（规则）', '第 1 夜起' in rules and '外星人攻击' in rules)
# 消歧编号唯一性：仅查 第九章 消歧汇总 小节
i9 = rules.find('## 第九章')
i10 = rules.find('## 第十章')
nums = re.findall(r'^(\d+)\. ', rules[i9:i10], re.M)
check('消歧编号 1-15 唯一', nums == [str(i) for i in range(1, 16)], str(nums))
check('无票型公示公告（代码 announce）', '票型公示' not in code31 and '票型公示' not in code30)

fails = [n for n, o in checks if not o]
print('\n==== 补充排查: %d/%d 通过 ====' % (len(checks) - len(fails), len(checks)))
for n in fails:
    print('未通过:', n)
