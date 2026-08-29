# -*- coding: utf-8 -*-
"""补刀规则 v2（实际文本版）：
- 补刀起始夜 第5夜 → 第4夜（异形出刀造成的濒死）
- 外星人攻击造成的人类濒死：异形第 1 夜起即可补刀（不计入 avoid）
- 异形之间同夜不重复指定同一健康目标（协调）不变
"""
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = '太空杀_公测3.1_模拟代码.py'
s = io.open(f, encoding='utf-8').read()

# 1) __init__ 增加外星人本夜目标集
old = "        self._alien_scapegoat = None"
new = """        self._alien_scapegoat = None
        self._foreigner_targets_night = set()  # 本夜外星人攻击过的目标（濒死原因=外星人）"""
assert old in s, 'init'
s = s.replace(old, new, 1)

# 2) plan_night_actions 重置
old = "        self._alien_targets_this_night = set()"
new = "        self._alien_targets_this_night = set()\n        self._foreigner_targets_night = set()"
assert old in s, 'plan reset'
s = s.replace(old, new, 1)

# 3) apply_harm 覆写：记录濒死原因阵营
old = """    def apply_harm(self, target_id, cause):
        res = super().apply_harm(target_id, cause)
        if res == 'dying' and ANNOUNCE_INJURY:
            self.announce_msg("%d号 濒死。" % target_id)
        return res"""
new = """    def apply_harm(self, target_id, cause):
        res = super().apply_harm(target_id, cause)
        if res == 'dying':
            # 记录濒死原因阵营：外星人造成的濒死可被异形第 1 夜起补刀（消歧13 v2）
            self.players[target_id].dying_cause_camp = \\
                'foreigner' if cause == '外星人伤害' else 'alien'
            if ANNOUNCE_INJURY:
                self.announce_msg("%d号 濒死。" % target_id)
        return res"""
assert old in s, 'apply_harm'
s = s.replace(old, new, 1)

# 4) ai_pick_kill_target：avoid 规则 v2
old = """        # 补刀规则（公测3.0 消歧13）：异形协调行动、同夜不重复指定同一目标；
        # 第 5 夜起可自由选择补刀——对已濒死目标再次出刀直接致死
        avoid = set()
        if self.night < 5:
            avoid = {x for x in getattr(self, '_alien_targets_this_night', set())
                     if self.players[x].alive and not self.players[x].is_alien()}
        t = decide_kill(obs, mem, self.rng, self.skills[p.id], avoid=avoid)
        if t is not None and p.is_alien():
            self._alien_targets_this_night.add(t)"""
new = """        # 补刀规则（消歧13 v2）：异形协调行动、同夜不重复指定同一健康目标；
        # 异形出刀造成的濒死：第 4 夜起可补刀；外星人攻击造成的濒死：第 1 夜起即可补刀
        avoid = set()
        if self.night < 4:
            avoid = {x for x in getattr(self, '_alien_targets_this_night', set())
                     if self.players[x].alive and not self.players[x].is_alien()
                     and getattr(self.players[x], 'dying_cause_camp', '') != 'foreigner'}
        t = decide_kill(obs, mem, self.rng, self.skills[p.id], avoid=avoid)
        if t is not None:
            if p.is_alien():
                self._alien_targets_this_night.add(t)
            else:
                self._foreigner_targets_night.add(t)"""
assert old in s, 'kill override'
s = s.replace(old, new, 1)

# 5) Player.dying_cause_camp 默认值（Player 在 3.0 引擎，动态赋值即可，无需改）
io.open(f, 'w', encoding='utf-8', newline='').write(s)
print('focus v2 OK')
