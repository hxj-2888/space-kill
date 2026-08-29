# -*- coding: utf-8 -*-
"""抑制封锁 + 生化不免疫 行为检验。"""
import importlib.util
import random
import sys

sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('m31', '太空杀_公测3.1_模拟代码.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
rng = random.Random(4)

results = []
def check(name, ok, detail=''):
    results.append((name, ok))
    print(('PASS' if ok else 'FAIL') + '  ' + name + '  ' + detail)

g = m.Game31(rng, 0, 'high')
det = [p for p in g.players if p.role == '神探'][0]
g.night = 3
det.suppressed = True
checks_before = sum(det.crew_checks.values())
# 神探在 step2 走 ai_pick_check_target（role 神探），用静默/抑制分支——直接调用 step2
g.step2_check_patrol()
# 神探查验计入 crew_checks 吗？神探分支只加 det_checked——用 known 数量判断
# 更直接：被抑制的普通船员当夜无法查验
g2 = m.Game31(rng, 1, 'high')
g2.night = 3
crew = [p for p in g2.players if p.role == '普通船员' and not p.dying][0]
crew.suppressed = True
before = dict(crew.crew_checks)
g2.step2_check_patrol()
check('S1b 被抑制船员当夜无法查验', crew.crew_checks == before)

# S1c 被抑制的保镖当夜无法保护
g3 = m.Game31(rng, 2, 'high')
g3.night = 3
bg = [p for p in g3.players if p.role == '保镖'][0]
bg.suppressed = True
immune_before = sum(q.immune for q in g3.players)
g3.step3_bodyguard()
immune_after = sum(q.immune for q in g3.players)
check('S1c 被抑制保镖当夜无法保护', immune_after == immune_before)

# S1d 被抑制的警察当夜无法巡逻
g4 = m.Game31(rng, 3, 'high')
g4.night = 3
cop = [p for p in g4.players if p.role == '警察'][0]
cop.suppressed = True
g4.step2_check_patrol()
check('S1d 被抑制警察当夜无法巡逻', not cop.police_patrol_used)

# S2 生化医师可被感染（无天生抗体）
g5 = m.Game31(rng, 4, 'high')
g5.night = 2
doc = [p for p in g5.players if p.role == '生化医师'][0]
al = [p for p in g5.alive_aliens() if not p.awakened][0]
r = g5.apply_infection(doc.id, al.id)
check('S2 生化医师可被感染', r == 'infected' and doc.infection == 1 and not doc.has_antibody,
      'r=%s' % r)

# S2b 治疗赋予的抗体仍有效
doc.has_antibody = True
doc.infection = 0
r = g5.apply_infection(doc.id, al.id)
check('S2b 治疗赋予的抗体仍有效', r == 'blocked')

print('\n==== 抑制/生化: %d/%d passed ====' % (sum(1 for _, o in results if o), len(results)))
