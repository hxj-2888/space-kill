# -*- coding: utf-8 -*-
"""公测3.1 策略矩阵：人类{std,passive,aggro} × 异形{mix,aggro,sab,mimic} × 外星人{std,hunter}
= 24 组合 × 2000 局 → sim_output/策略矩阵报告.md"""
import importlib.util
import io
import os
import random
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('m31', '太空杀_公测3.1_模拟代码.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sim_output')
N = 2000
HUMANS = [('std', '标准广播'), ('passive', '信息沉淀·神探不跳'), ('aggro', '激进广播·神探必跳')]
ALIENS = [('mix', '破坏混合分工'), ('aggro', '极限击杀流'), ('sab', '破坏停摆流'), ('mimic', '拟态渗透流')]
FOREIGNS = [('std', '标准渔翁'), ('hunter', '猎手双刀')]

t0 = time.time()
results = {}
seed = 90000
for (hk, hl) in HUMANS:
    for (ak, al) in ALIENS:
        for (xk, xl) in FOREIGNS:
            m.HUMAN_STYLE, m.ALIEN_STYLE, m.FOREIGNER_STYLE = hk, ak, xk
            rng = random.Random(seed); seed += 1
            wins = Counter()
            nights = 0
            for i in range(N):
                g = m.simulate_one31(rng, i, [], None)
                wins[g.winner] += 1
                nights += g.end_night
            results[(hk, ak, xk)] = (100 * wins['human'] / N, 100 * wins['alien'] / N,
                                     100 * wins['foreigner'] / N, nights / N)
            print('%-8s %-8s %-8s %.1f/%.1f/%.1f (%.0fs)' % (hk, ak, xk,
                  results[(hk, ak, xk)][0], results[(hk, ak, xk)][1],
                  results[(hk, ak, xk)][2], time.time() - t0), flush=True)

L = []
L.append('# 太空杀 公测3.1 策略矩阵报告（三方风格交叉对战）\n')
L.append('模拟：**24 组合 × %d 局**高水平对战（种子 %d）。规则版本：公测3.0（R1~R11 + 感染体系v3 + 倒计时24 + 补刀第4夜）。' % (N, 90000))
L.append('默认参数：TRUSTED_LR=5.0 / ORDINARY_LR=1.12 / 记忆衰减0.97 / 情绪+追责+质询+引述全开。**规则数值未改动**，仅切换策略风格钩子。\n')
L.append('## 策略含义\n')
L.append('| 阵营 | 风格 | 行为要点 |')
L.append('|---|---|---|')
L.append('| 人类 | std 标准广播 | 神探第2夜起有情报跳身份；船员双查锁定 70% 指认 |')
L.append('| 人类 | passive 信息沉淀 | 神探永不跳；情报走私聊 |')
L.append('| 人类 | aggro 激进广播 | 有情报必跳必指认 |')
L.append('| 异形 | mix 破坏混合分工 | 首只觉醒占破坏，其余感染→击杀（第3夜 90% 转化）；团结/混淆协同投票 |')
L.append('| 异形 | aggro 极限击杀 | 全员出刀为主，感染<40%，不结茧 |')
L.append('| 异形 | sab 破坏停摆 | 觉醒/转化全优先破坏，推停摆阈值 |')
L.append('| 异形 | mimic 拟态渗透 | 投票指控完全混入人类票型，私聊不撒谎 |')
L.append('| 外星 | std 标准渔翁 | 建图→第6夜双刀→高价值收割 |')
L.append('| 外星 | hunter 猎手双刀 | 第6夜 98% 觉醒，尽早双刀 |\n')

L.append('## ① 全组合胜率矩阵\n')
L.append('| 人类 | 异形 | 外星 | 人类% | 异形% | 外星% | 极差pp | 平均夜 |')
L.append('|---|---|---|---|---|---|---|---|')
for (hk, hl) in HUMANS:
    for (ak, al) in ALIENS:
        for (xk, xl) in FOREIGNS:
            h, a, x, nights = results[(hk, ak, xk)]
            spread = max(h, a, x) - min(h, a, x)
            L.append('| %s | %s | %s | %.1f | %.1f | %.1f | %.1f | %.1f |' % (hl, al, xl, h, a, x, spread, nights))

L.append('\n## ② 人类风格稳健性（跨异形×外星均值）\n')
L.append('| 人类风格 | 人类% | 异形% | 外星% |')
L.append('|---|---|---|---|')
for (hk, hl) in HUMANS:
    vals = [results[(hk, ak, xk)] for (ak, al) in ALIENS for (xk, xl) in FOREIGNS]
    L.append('| %s | %.1f | %.1f | %.1f |' % (hl,
        sum(v[0] for v in vals) / len(vals), sum(v[1] for v in vals) / len(vals),
        sum(v[2] for v in vals) / len(vals)))

L.append('\n## ③ 异形风格稳健性（跨人类×外星均值）\n')
L.append('| 异形风格 | 人类% | 异形% | 外星% |')
L.append('|---|---|---|---|')
for (ak, al) in ALIENS:
    vals = [results[(hk, ak, xk)] for (hk, hl) in HUMANS for (xk, xl) in FOREIGNS]
    L.append('| %s | %.1f | %.1f | %.1f |' % (al,
        sum(v[0] for v in vals) / len(vals), sum(v[1] for v in vals) / len(vals),
        sum(v[2] for v in vals) / len(vals)))

L.append('\n## ④ 外星人风格稳健性（跨人类×异形均值）\n')
L.append('| 外星风格 | 人类% | 异形% | 外星% |')
L.append('|---|---|---|---|')
for (xk, xl) in FOREIGNS:
    vals = [results[(hk, ak, xk)] for (hk, hl) in HUMANS for (ak, al) in ALIENS]
    L.append('| %s | %.1f | %.1f | %.1f |' % (xl,
        sum(v[0] for v in vals) / len(vals), sum(v[1] for v in vals) / len(vals),
        sum(v[2] for v in vals) / len(vals)))

L.append('\n## ⑤ 关键观察\n')
best_cell = max(results.items(), key=lambda kv: -((kv[1][0]-40)**2 + (kv[1][1]-35)**2 + (kv[1][2]-25)**2))
bk = best_cell[0]
b = best_cell[1]
L.append('- 最贴近目标 40/35/25 的组合：人类 %s / 异形 %s / 外星 %s → %.1f / %.1f / %.1f' % (
    dict(HUMANS)[bk[0]], dict(ALIENS)[bk[1]], dict(FOREIGNS)[bk[2]], b[0], b[1], b[2]))
L.append('- 目标由规则层继续平衡（候选旋钮见 策略参数说明.md）；本矩阵仅切换 AI 策略，不动规则数值。')

with io.open(os.path.join(OUT, '策略矩阵报告.md'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('DONE matrix report in %.0fs' % (time.time() - t0))
