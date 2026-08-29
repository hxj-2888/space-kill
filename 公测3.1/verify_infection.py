# -*- coding: utf-8 -*-
"""感染体系 v3 行为检验。"""
import importlib.util
import random
import sys

sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('m31', '太空杀_公测3.1_模拟代码.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
rng = random.Random(5)

results = []
def check(name, ok, detail=''):
    results.append((name, ok))
    print(('PASS' if ok else 'FAIL') + '  ' + name + '  ' + detail)

def fresh():
    g = m.Game31(rng, random.randrange(1000), 'high')
    g._alien_targets_this_night = set()
    g._foreigner_targets_night = set()
    return g

# I1a 感染觉醒异形：第2夜死亡
g = fresh(); g.night = 1
al = [p for p in g.alive_aliens() if not p.awakened][0]
al.awakened = True; al.awak_dir = '感染'; al.awak_night = 1
h = g.alive_humans()[0]
r = g.apply_infection(h.id, al.id)
check('I1a 感染觉醒→死亡夜=当夜+1', r == 'infected' and h.infection_death_night == 2,
      'death_night=%s' % h.infection_death_night)

# I1b 未觉醒异形：第3夜死亡
g = fresh(); g.night = 1
al = g.alive_aliens()[0]
h = g.alive_humans()[0]
r = g.apply_infection(h.id, al.id)
check('I1b 未觉醒→死亡夜=当夜+2', r == 'infected' and h.infection_death_night == 3,
      'death_night=%s' % h.infection_death_night)

# I2 外星人：第3夜可感染、第4夜免疫
g = fresh(); g.night = 3
al = g.alive_aliens()[0]
fk = g.alive_foreigners()[0]
r3 = g.apply_infection(fk.id, al.id)
g.night = 4
fk.infection = 0  # 清掉第3夜的感染，测试第4夜新感染
r4 = g.apply_infection(fk.id, al.id)
check('I2 外星人第3夜可感染/第4夜免疫', r3 == 'infected' and r4 == 'immune',
      'n3=%s n4=%s' % (r3, r4))

# I3 生化医师治疗初始 2
g = fresh()
doc = [p for p in g.players if p.role == '生化医师'][0]
check('I3 生化初始治疗=1(平衡削弱)', doc.doctor_treat == 1, 'init=%d' % doc.doctor_treat)

# I4 医生互斥：濒死+感染同场，医生只救援不治疗
g = fresh(); g.night = 2
doc = [p for p in g.players if p.role == '生化医师'][0]
hu1 = [q for q in g.alive_humans() if q.id != doc.id][0]
hu2 = [q for q in g.alive_humans() if q.id not in (doc.id, hu1.id)][0]
hu1.dying = True          # 濒死者
hu2.infection = 1         # 感染者
treat_before = doc.doctor_treat
g._doctor_act(doc)
check('I4 生化无救援能力→转治疗（每晚一记出手）',
      hu1.dying is True and hu2.infection == 0 and doc.doctor_treat == treat_before - 1,
      'hu1.dying=%s hu2.infection=%s treat=%s' % (hu1.dying, hu2.infection, doc.doctor_treat))

print('\n==== 感染v3: %d/%d passed ====' % (sum(1 for _, o in results if o), len(results)))
