# -*- coding: utf-8 -*-
"""全面规则漏洞排查：规则文本 ↔ 代码常量一致性 + 消歧编号唯一性 + 关键交互点。"""
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

# 1) 数值一致性
check('倒计时 24（规则）', '24 昼夜' in rules)
check('倒计时 24（3.1 代码）', 'INIT_COUNTDOWN = 24.0' in code31)
check('倒计时 24（3.0 裁判被覆写）', 'self.countdown = INIT_COUNTDOWN' in code31)
check('救援医师 3 次（规则）', '全局 3 次（初始 1 + 第2/4 夜各 +1）' in rules)
check('救援医师 3 次（3.0 代码 init=1）', "p.doctor_rescue = 1  # 公测3.0" in code30 or "doctor_rescue = 1" in code30)
check('生化治疗 4 次=初始1+3（规则）', '治疗额度 **4 次（初始 1 + 第2/3/4 夜各 +1）**' in rules)
check('生化治疗初始 1（3.1 代码）', 'p.doctor_treat = 1' in code31)
check('生化无天生抗体（3.1 代码）', 'p.has_antibody = False' in code31)
check('生化不免疫（规则）', '自身不免疫感染' in rules)
check('双刀第6夜（规则）', '第 6 夜起' in rules)
check('双刀第6夜（3.1 代码 night>=6）', 'self.night >= 6' in code31)
check('第10夜免疫（规则）', '第 10 夜额外 1 次' in rules)
check('第10夜免疫（3.1 代码 night>=10）', 'self.night >= 10' in code31)
check('补刀第4夜/外星第1夜（规则）', ('第 4 夜起方可补刀' in rules and '第 1 夜起' in rules))
check('补刀 night<4 avoid（3.1 代码）', 'if self.night < 4:' in code31)
check("dying_cause_camp='foreigner' 判定（3.1 代码）", "dying_cause_camp', '') != 'foreigner'" in code31)
check('感染觉醒第2夜死（规则）', '提前至第 2 夜死亡' in rules or '提前至第 2 夜死亡（公测3.1）' in rules)
check('感染觉醒 +1（3.1 代码）', 'infection_death_night = self.night + 1' in code31)
check('外星人第4晚感染免疫（规则）', '第 4 晚起免疫异形感染' in rules)
check('外星人第4晚免疫（3.1 代码）', 't.is_foreigner() and self.night >= 4' in code31)
check('抑制封锁全技能（规则）', '含查验、巡逻、保护等所有夜间技能' in rules)
check('抑制封锁 step2/step3（3.1 代码）', 'or p.suppressed:' in code31)
check('生化不免疫感染（规则文本已移除天生抗体）', '自身免疫异形感染' not in rules)

# 2) 消歧编号唯一性
nums = re.findall(r'^(\d+)\. \*\*', rules, re.M)
check('消歧编号无重复', len(nums) == len(set(nums)), str(nums))

# 3) 关键交互点（代码层面）
check('抑制延后1夜（3.0 代码 +1）', 'infection_death_night += 1' in code30)
check('夜晚免疫不挡感染（3.0 apply_infection 无 night_immune 检查）',
      'night_immune' not in code30[code30.find('def apply_infection'):code30.find('def check_win')])
check('护盾不挡感染（3.0 apply_infection 无 shield 检查）',
      'shield' not in code30[code30.find('def apply_infection'):code30.find('def check_win')])
check('医生互斥（3.1 救援后 return）', 'return  # 救援出手 → 当晚结束（互斥）' in code31)
check('异形团结/混淆投票（3.1）', "herd_top in mates" in code31)
check('无票型公示（公告不含票型）', '票型公示' not in code30 and '票型' not in code31)

fails = [n for n, o in checks if not o]
print('\n==== 排查: %d/%d 通过 ====' % (len(checks) - len(fails), len(checks)))
for n in fails:
    print('未通过:', n)
