# -*- coding: utf-8 -*-
"""公测3.1 对齐修正行为检验：F1/F2/F3。"""
import importlib.util
import random
import sys

sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('m31', '太空杀_公测3.1_模拟代码.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
rng = random.Random(3)

# F3 医生零额度无法自救
g = m.Game31(rng, 0, 'high')
doc = [p for p in g.players if p.role in ('生化医师', '救援医师')][0]
doc.dying = True
doc.doctor_rescue = 0
g._doctor_act(doc)
print('F3 零额度自救被拒:', doc.dying is True)
doc.doctor_rescue = 1
g._doctor_act(doc)
print('F3 有额度自救成功:', doc.dying is False and doc.doctor_rescue == 0)

# F2 武装船员不再规划保护
g = m.Game31(rng, 1, 'high')
g.plan_night_actions()
armed = [p for p in g.players if p.role == '武装船员']
print('F2 武装船员不再有 _armed_protect 属性:',
      all(not hasattr(p, '_armed_protect') or p._armed_protect is None for p in armed) if armed else '本局无武装船员(转职才出现)')

# F1 外星人人类尚存时不以异形为击杀目标
g = m.Game31(rng, 2, 'high')
fk = g.alive_foreigners()[0]
targets = set()
for i in range(200):
    t = g.ai_pick_kill_target(fk)
    if t is not None:
        targets.add(g.players[t].is_alien())
print('F1 人类尚存时外星人目标不含异形:', targets == {False})
