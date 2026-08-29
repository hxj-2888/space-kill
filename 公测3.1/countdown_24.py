# -*- coding: utf-8 -*-
"""倒计时 21→24（公测3.1 平衡调整）+ 规则文本同步。"""
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')

# ---- 3.1 引擎 ----
f = '太空杀_公测3.1_模拟代码.py'
s = io.open(f, encoding='utf-8').read()
old = "ANNOUNCE_INJURY = False        # 濒死公告开关（False=濒死不公告，公告最小信息原则）"
new = old + "\nINIT_COUNTDOWN = 24.0          # 公测3.1 平衡：初始倒计时 21→24 昼夜"
assert old in s, 'knob'
s = s.replace(old, new, 1)
old = "        super().__init__(rng, game_id, strategy)"
new = """        super().__init__(rng, game_id, strategy)
        self.countdown = INIT_COUNTDOWN  # 公测3.1 平衡：覆盖裁判层 21 昼夜为 24"""
assert old in s, 'init countdown'
s = s.replace(old, new, 1)
io.open(f, 'w', encoding='utf-8', newline='').write(s)
print('engine: countdown 24')

# ---- 规则文本 ----
f2 = '../公测3.0/太空杀_公测3.0_规则.md'
r = io.open(f2, encoding='utf-8').read()
pairs = [
    ('| 初始倒计时 | 21 昼夜 |', '| 初始倒计时 | 24 昼夜（公测3.1 平衡调整） |'),
    ('初始倒计时 21 昼夜。每夜步骤11 自然 -1', '初始倒计时 24 昼夜。每夜步骤11 自然 -1'),
    ('倒计时可以高于初始值 21', '倒计时可以高于初始值 24'),
    ('**21 昼夜（R11）**', '**21→24 昼夜（R11 + 公测3.1 平衡）**'),
]
cnt = 0
for old, new in pairs:
    if old in r:
        r = r.replace(old, new)
        cnt += 1
io.open(f2, 'w', encoding='utf-8', newline='').write(r)
print('rules text: %d 处同步' % cnt)
