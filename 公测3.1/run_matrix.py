# -*- coding: utf-8 -*-
"""公测3.1 策略矩阵：人类{std,passive,aggro} × 异形{kill,sab,infect} × 外星人{std,hunter}
= 18 组合 × 2000 局 → sim_output/策略矩阵报告.md"""
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
ALIENS = [('kill', '击杀流·极限出刀'), ('sab', '破坏流·停摆推进'), ('infect', '感染流·寄生压制')]
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
L.append('模拟：**18 组合 × %d 局**高水平对战（种子 %d）。规则版本：公测3.0（R1~R11 + 感染体系v3 + 倒计时24 + 补刀第4夜）。' % (N, 90000))
L.append('异形流派已收敛为 **击杀流 kill / 破坏流 sab / 感染流 infect**（原 mix 混合分工、balanced 均衡、mimic 拟态渗透已移除）；'
         '**感染是行动权重表中的显式权重项**，三大流派共用"视情形而定"的权重化觉醒与转化。')
L.append('默认参数：TRUSTED_LR=5.0 / ORDINARY_LR=1.12 / 记忆衰减0.97 / 情绪+追责+质询+引述全开。**规则数值未改动**，仅切换策略权重。\n')
L.append('## 策略含义\n')
L.append('| 阵营 | 风格 | 行为要点 |')
L.append('|---|---|---|')
L.append('| 人类 | std 标准广播 | 神探第2夜起有情报跳身份；船员双查锁定 70% 指认 |')
L.append('| 人类 | passive 信息沉淀 | 神探永不跳；情报走私聊 |')
L.append('| 人类 | aggro 激进广播 | 有情报必跳必指认 |')
L.append('| 异形 | kill 击杀流 | 行动权重出刀最高；觉醒偏击杀（偶数夜双刀）；视情形转化为收割 |')
L.append('| 异形 | sab 破坏流 | 行动权重破坏最高；觉醒偏破坏推停摆；净破坏封顶/残局时转化出击杀 |')
L.append('| 异形 | infect 感染流 | 行动权重感染最高（感染为显式权重项）；觉醒偏感染，感染打满目标数 |')
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

L.append('\n## ⑤ 目标贴合度（目标 人类40 / 异形35 / 外星人25）\n')
L.append('| 人类 | 异形 | 外星 | 人类% | 异形% | 外星% | 距目标(pp) |')
L.append('|---|---|---|---|---|---|---|')
ranked = sorted(results.items(),
                key=lambda kv: ((kv[1][0] - 40) ** 2 + (kv[1][1] - 35) ** 2 + (kv[1][2] - 25) ** 2) ** 0.5)
for k, v in ranked:
    d = ((v[0] - 40) ** 2 + (v[1] - 35) ** 2 + (v[2] - 25) ** 2) ** 0.5
    L.append('| %s | %s | %s | %.1f | %.1f | %.1f | %.1f |' % (
        dict(HUMANS)[k[0]], dict(ALIENS)[k[1]], dict(FOREIGNS)[k[2]], v[0], v[1], v[2], d))

bk, b = ranked[0]
L.append('\n- 最贴近目标 40/35/25 的组合：**人类 %s / 异形 %s / 外星 %s → %.1f / %.1f / %.1f**' % (
    dict(HUMANS)[bk[0]], dict(ALIENS)[bk[1]], dict(FOREIGNS)[bk[2]], b[0], b[1], b[2]))

# ---- 最优应对（best response）与均衡解 ----
HK = [h for h, _ in HUMANS]
AK = [a for a, _ in ALIENS]
XK = [x for x, _ in FOREIGNS]


def best_response(camp, h, a, x):
    """给定另外两方的策略，返回本方胜率最高的风格。"""
    if camp == 0:
        return max(HK, key=lambda s: results[(s, a, x)][0])
    if camp == 1:
        return max(AK, key=lambda s: results[(h, s, x)][1])
    return max(XK, key=lambda s: results[(h, a, s)][2])


L.append('\n## ⑥ 最优应对与均衡解（最佳响应迭代）\n')
cur = (HK[0], AK[0], XK[0])
path = [cur]
for _ in range(8):
    nxt = (best_response(0, *cur), best_response(1, *cur), best_response(2, *cur))
    if nxt == cur:
        break
    cur = nxt
    path.append(cur)
L.append('迭代路径：%s\n' % ' → '.join('(%s,%s,%s)' % p for p in path))
v = results[cur]
eq_d = ((v[0] - 40) ** 2 + (v[1] - 35) ** 2 + (v[2] - 25) ** 2) ** 0.5
L.append('| 解 | 人类 | 异形 | 外星 | 人类% | 异形% | 外星% | 距目标(pp) |')
L.append('|---|---|---|---|---|---|---|---|')
L.append('| 均衡解（各方均为最优应对） | %s | %s | %s | %.1f | %.1f | %.1f | %.1f |' % (
    dict(HUMANS)[cur[0]], dict(ALIENS)[cur[1]], dict(FOREIGNS)[cur[2]], v[0], v[1], v[2], eq_d))
L.append('| 目标贴合解（欧氏距离最小） | %s | %s | %s | %.1f | %.1f | %.1f | %.1f |' % (
    dict(HUMANS)[bk[0]], dict(ALIENS)[bk[1]], dict(FOREIGNS)[bk[2]], b[0], b[1], b[2],
    ((b[0] - 40) ** 2 + (b[1] - 35) ** 2 + (b[2] - 25) ** 2) ** 0.5))
L.append('\n> 说明：本矩阵仅切换 AI 策略权重，不改规则数值。若均衡解与目标仍有缺口，'
         '差额只能由规则层旋钮（感染死亡夜 / 救援额度 / 停摆奖励 / 神探查验频率等）补齐。')

L.append('\n## ⑦ 关键观察\n')
L.append('- 异形三大流派中 **%s** 的异形胜率最高（跨人类×外星均值 %.1f%%）。' % (
    max(AK, key=lambda a: sum(results[(h, a, x)][1] for h, _ in HUMANS for x, _ in FOREIGNS)
        / (len(HUMANS) * len(FOREIGNS))),
    max(sum(results[(h, a, x)][1] for h, _ in HUMANS for x, _ in FOREIGNS)
        / (len(HUMANS) * len(FOREIGNS)) for a in AK)))
L.append('- 三大流派的行动占比、觉醒方向分布与转化利用度见 `异形流派核验.md`（verify_alien31.py）。')
L.append('- 目标 40/35/25 的缺口由规则层旋钮补齐；本次按约定**保留策略层改动，不施加规则数值削弱**。')

with io.open(os.path.join(OUT, '策略矩阵报告.md'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('DONE matrix report in %.0fs' % (time.time() - t0))
