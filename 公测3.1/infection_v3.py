# -*- coding: utf-8 -*-
"""感染体系 v3（覆写方式）：I1 觉醒第二夜死 / I2 外星第4晚免疫 / I3 生化治疗2 / I4 医生互斥显式化。"""
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = '太空杀_公测3.1_模拟代码.py'
s = io.open(f, encoding='utf-8').read()

# ---- I1/I2: Game31.apply_infection 覆写（插在 apply_harm 覆写前） ----
anchor = "    def apply_harm(self, target_id, cause):"
override = """    # ---------- 覆写：感染（I1 感染觉醒第2夜死 / I2 外星人第4晚起感染免疫） ----------
    def apply_infection(self, target_id, src_id):
        t = self.players[target_id]
        # I2 外星人削弱：第 4 晚起感染免疫（此前已感染的仍按原死亡夜结算）
        if t.is_foreigner() and self.night >= 4:
            return 'immune'
        res = super().apply_infection(target_id, src_id)
        if res == 'infected':
            # I1 感染觉醒增强：感染觉醒异形施加的感染 → 第2夜死亡（基础为第3夜）
            src = self.players[src_id]
            if src.is_alien() and src.awakened and src.awak_dir == '感染':
                t.infection_death_night = self.night + 1
        return res

    def apply_harm(self, target_id, cause):"""
assert anchor in s, 'harm anchor'
s = s.replace(anchor, override, 1)

# ---- I3: 生化医师治疗初始 2 次 ----
old = """        super().__init__(rng, game_id, strategy)
        self.countdown = INIT_COUNTDOWN  # 公测3.1 平衡：覆盖裁判层 21 昼夜为 24"""
new = """        super().__init__(rng, game_id, strategy)
        self.countdown = INIT_COUNTDOWN  # 公测3.1 平衡：覆盖裁判层 21 昼夜为 24
        # I3 生化医师感染治疗初始 2 次（裁判层为 1；第2/3/4夜仍各+1 → 全局5）
        for p in self.players:
            if p.role == '生化医师':
                p.doctor_treat = 2"""
assert old in s, 'doctor init'
s = s.replace(old, new, 1)

# ---- I4: 医生互斥显式化注释 ----
old = """    def _doctor_act(self, p):
        if p.dying:"""
new = """    def _doctor_act(self, p):
        # I4 消歧：每名医生每晚仅一记出手——救援(濒死)与治疗(感染)互斥；
        # 救援后立即返回，无救援额度时不重复出手（本方法单次调用只执行一项）。
        if p.dying:"""
assert old in s, 'doctor act'
s = s.replace(old, new, 1)

# ---- config 快照 ----
old = "        'focus_fire': '异形协调行动：同夜不重复指定目标；第5夜起可自由选择补刀（濒死再受击直接死亡）',"
new = """        'focus_fire': '异形协调行动：同夜不重复指定目标；第5夜起可自由选择补刀（濒死再受击直接死亡）',
        'infection_v3': '感染觉醒→第2夜死亡；外星人第4晚起感染免疫；生化治疗初始2(全局5)；医生救援/治疗每晚一人互斥',"""
assert old in s, 'config'
s = s.replace(old, new, 1)

io.open(f, 'w', encoding='utf-8', newline='').write(s)
print('infection v3 OK (override style)')
