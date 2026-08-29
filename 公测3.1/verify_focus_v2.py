# -*- coding: utf-8 -*-
"""补刀规则 v2 行为检验。"""
import importlib.util
import random
import sys

sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('m31', '太空杀_公测3.1_模拟代码.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
rng = random.Random(9)

results = []
def check(name, ok, detail=''):
    results.append((name, ok))
    print(('PASS' if ok else 'FAIL') + '  ' + name + '  ' + detail)

def fresh():
    g = m.Game31(rng, random.randrange(1000), 'high')
    g._alien_targets_this_night = set()
    g._foreigner_targets_night = set()
    return g

# A：第1夜，外星人造成人类濒死 → 异形可补刀
g = fresh(); g.night = 1
alien = g.alive_aliens()[0]
fk = g.alive_foreigners()[0]
h1 = g.alive_humans()[0]
g.apply_harm(h1.id, '外星人伤害')
g._foreigner_targets_night.add(h1.id)
t = g.ai_pick_kill_target(alien)
check('A 第1夜异形补刀外星濒死', t == h1.id, 'target=%s' % t)

# B：第1夜，异形出刀致濒死 → 不可自补（avoid）
g = fresh(); g.night = 1
al = g.alive_aliens()[0]
hu = g.alive_humans()[0]
g.apply_harm(hu.id, '异形出刀')
g._alien_targets_this_night.add(hu.id)
t = g.ai_pick_kill_target(al)
check('B 第1夜不可补刀异形濒死', t != hu.id, 'target=%s' % t)

# C：第4夜，异形濒死可补刀
g = fresh(); g.night = 4
al = g.alive_aliens()[0]
hu = g.alive_humans()[0]
g.apply_harm(hu.id, '异形出刀')
g._alien_targets_this_night.add(hu.id)
t = g.ai_pick_kill_target(al)
check('C 第4夜可补刀异形濒死', t == hu.id, 'target=%s' % t)

# D：第1夜不重复指定健康目标
g = fresh(); g.night = 1
al = g.alive_aliens()[0]
hu = g.alive_humans()[0]
g._alien_targets_this_night.add(hu.id)
t = g.ai_pick_kill_target(al)
check('D 不重复指定健康目标', t != hu.id, 'target=%s' % t)

# E：第1夜，外星人濒死优先于健康目标（FINISH_DYING）
g = fresh(); g.night = 1
al = g.alive_aliens()[0]
# 选一个非工程师人类（工程师第1夜被动全能免疫，出刀会免疫而非濒死）
hu_dying = [q for q in g.alive_humans() if q.role != '工程师'][0]
hu_healthy = [q for q in g.alive_humans() if q.id != hu_dying.id][0]
res = g.apply_harm(hu_dying.id, '外星人伤害')
check('E0 外星攻击致濒死(非免疫目标)', res == 'dying', 'res=%s role=%s' % (res, hu_dying.role))
from collections import Counter
picks = Counter(g.ai_pick_kill_target(al) for _ in range(40))
check('E 外星濒死补刀优先于健康目标', picks.most_common(1)[0][0] == hu_dying.id,
      'picks=%s (噪声机制下允许少量随机)' % dict(picks))

print('\n==== 补刀v2: %d/%d passed ====' % (sum(1 for _, o in results if o), len(results)))
