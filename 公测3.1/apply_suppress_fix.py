# -*- coding: utf-8 -*-
"""S1 抑制当晚无法行动——补齐 step2(查验/巡逻)/step3(保护) 的 suppressed 检查；
S2 生化医师不再天生免疫感染（治疗赋予的抗体仍有效）。"""
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = '太空杀_公测3.1_模拟代码.py'
s = io.open(f, encoding='utf-8').read()

# ---- S2 生化不免疫（Game31.__init__ I3 块内追加） ----
old = """        # I3 生化医师感染治疗初始 2 次（裁判层为 1；第2/3/4夜仍各+1 → 全局5）
        for p in self.players:
            if p.role == '生化医师':
                p.doctor_treat = 2"""
new = """        # I3 生化医师感染治疗初始 2 次（裁判层为 1；第2/3/4夜仍各+1 → 全局5）
        # S2 生化医师不再天生免疫感染（裁判层曾置 has_antibody=True；治疗赋予的抗体仍有效）
        for p in self.players:
            if p.role == '生化医师':
                p.doctor_treat = 2
                p.has_antibody = False"""
assert old in s, 'S2'
s = s.replace(old, new, 1)

# ---- S1 覆写 step2/step3（增加 suppressed 检查） ----
anchor = "    # ---------- 覆写：感染（I1 感染觉醒第2夜死 / I2 外星人第4晚起感染免疫） ----------"
overrides = """    # ---------- 覆写：步骤2 查验/巡逻（S1：感染抑制当晚无法行动，与沉默同等封锁） ----------
    def step2_check_patrol(self):
        det_checked = 0
        for p in self.alive_players():
            if p.role == '神探' and p.alive and not p.dying:
                if p.silent > 0 or p.suppressed:
                    continue  # 沉默/感染抑制：当晚无法执行夜间技能
                tgt = self.ai_pick_check_target(p)
                if tgt is not None:
                    t = self.players[tgt]
                    p.known[tgt] = {'camp': t.camp, 'role': t.role}
                    p.crew_checks[tgt] = p.crew_checks.get(tgt, 0) + 1
                    det_checked += 1
        crew_checked = 0
        for p in self.alive_players():
            if p.role == '普通船员' and p.alive and not p.dying:
                if p.silent > 0 or p.suppressed:
                    continue
                if self._crew_will_repair(p):
                    continue
                tgt = self.ai_pick_check_target(p)
                if tgt is not None:
                    t = self.players[tgt]
                    if not t.alive or getattr(t, 'role', None) != getattr(t, 'original_role', t.role):
                        p.crew_checks.pop(tgt, None)
                        p.exclude_info.pop(tgt, None)
                    if p.crew_checks.get(tgt, 0) == 0:
                        p.exclude_info[tgt] = p.exclude_info.get(tgt, set())
                        pool = [r for r in set(HUMAN_ROLES) if r != t.role]
                        if pool:
                            p.exclude_info[tgt].add(self.rng.choice(pool))
                    p.crew_checks[tgt] = p.crew_checks.get(tgt, 0) + 1
                    if p.crew_checks[tgt] >= 2:
                        p.known[tgt] = {'camp': t.camp, 'role': t.role}
                    crew_checked += 1
                    self.crew_check_count += 1
        for p in self.alive_players():
            if p.role == '警察' and p.alive and not p.dying and not p.police_patrol_used:
                if p.silent > 0 or p.suppressed:
                    continue
                if self.night <= 3 and self._police_will_patrol(p):
                    targets = self.ai_pick_patrol(p)
                    for t in targets:
                        self.players[t].immune += 1
                        self._protect_count[t] += 1
                    p.police_patrol_used = True
                    p.patrolled_tonight = True
                    self.announce_msg("有玩家发动了巡逻，%d名玩家获得保护。" % len(targets))
        self.announce_msg("当夜神探/外星人定向查验 %d 次；普通船员查验 %d 次。" % (det_checked, crew_checked))

    # ---------- 覆写：步骤3 保镖保护（S1：抑制当晚无法行动） ----------
    def step3_bodyguard(self):
        for p in self.alive_players():
            if p.role == '保镖' and p.alive and not p.dying:
                if p.silent > 0 or p.suppressed:
                    continue
                tgt = self.ai_pick_protect(p)
                if tgt is not None:
                    self.players[tgt].immune += 1
                    self._protect_count[tgt] += 1

    # ---------- 覆写：感染（I1 感染觉醒第2夜死 / I2 外星人第4晚起感染免疫） ----------"""
assert anchor in s, 'anchor'
s = s.replace(anchor, overrides, 1)

io.open(f, 'w', encoding='utf-8', newline='').write(s)
print('S1/S2 OK')
