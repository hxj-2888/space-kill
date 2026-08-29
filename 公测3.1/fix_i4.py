# -*- coding: utf-8 -*-
"""I4 修正：无救援能力的医生（生化）遇濒死者可转而治疗——互斥=每晚一记出手，不是"禁止治疗"。"""
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = '太空杀_公测3.1_模拟代码.py'
s = io.open(f, encoding='utf-8').read()

old = """    def _doctor_act(self, p):
        # I4 消歧：每名医生每晚仅一记出手——救援(濒死)与治疗(感染)互斥；
        # 救援后立即返回，无救援额度时不重复出手（本方法单次调用只执行一项）。
        if p.dying:
            if p.doctor_rescue > 0:
                p.doctor_rescue -= 1
                p.dying = False
                if p.infection > 0:
                    p.infection = 0
            return
        dying_targets = [q for q in self.alive_players() if q.dying]
        if dying_targets and p.doctor_rescue > 0:
            if p.role == '救援医师' or p.role == '临时医生':
                tgt = self.ai_pick_rescue(p, dying_targets)
                if tgt is not None and p.doctor_rescue > 0:
                    self.players[tgt].dying = False
                    p.doctor_rescue -= 1
                    if self.players[tgt].infection > 0 and p.role == '生化医师':
                        self.players[tgt].infection = 0
                        self.players[tgt].has_antibody = True
            return
        inf_targets = [q for q in self.alive_players() if q.infection >= 1]
        if inf_targets and p.doctor_treat > 0:
            tgt = self.ai_pick_infect_treat(p, inf_targets)
            if tgt is not None and p.doctor_treat > 0:
                self.players[tgt].infection = 0
                p.doctor_treat -= 1
                if p.role == '生化医师':
                    self.players[tgt].has_antibody = True"""
new = """    def _doctor_act(self, p):
        # I4 消歧：每名医生每晚仅一记出手——救援(濒死)与治疗(感染)互斥，出手后当晚结束。
        # 无救援出手（无濒死 / 无额度 / 该医生无救援他人能力如生化）→ 落入治疗分支。
        if p.dying:
            if p.doctor_rescue > 0:
                p.doctor_rescue -= 1
                p.dying = False
                if p.infection > 0:
                    p.infection = 0
            return
        dying_targets = [q for q in self.alive_players() if q.dying]
        if dying_targets and p.doctor_rescue > 0 and p.role in ('救援医师', '临时医生'):
            tgt = self.ai_pick_rescue(p, dying_targets)
            if tgt is not None and p.doctor_rescue > 0:
                self.players[tgt].dying = False
                p.doctor_rescue -= 1
                if self.players[tgt].infection > 0 and p.role == '生化医师':
                    self.players[tgt].infection = 0
                    self.players[tgt].has_antibody = True
            return  # 救援出手 → 当晚结束（互斥）
        inf_targets = [q for q in self.alive_players() if q.infection >= 1]
        if inf_targets and p.doctor_treat > 0:
            tgt = self.ai_pick_infect_treat(p, inf_targets)
            if tgt is not None and p.doctor_treat > 0:
                self.players[tgt].infection = 0
                p.doctor_treat -= 1
                if p.role == '生化医师':
                    self.players[tgt].has_antibody = True"""
assert old in s, 'doctor act'
s = s.replace(old, new, 1)
io.open(f, 'w', encoding='utf-8', newline='').write(s)
print('I4 fixed')
