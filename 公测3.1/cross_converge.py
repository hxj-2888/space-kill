# -*- coding: utf-8 -*-
"""策略交叉收敛：Phase A 阵营内横向对比(300局/格) → Phase B 前2名 2×2×2 精测(800局/格)
→ 稳定性排名 → 输出 sim_output/cross_convergence.md（定版推荐见文末）。
用法：python cross_converge.py （约 10000 局，8 分钟）"""
import importlib.util
import io
import os
import random
import statistics
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('m31', '太空杀_公测3.1_模拟代码.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sim_output')
os.makedirs(OUT, exist_ok=True)
N_A, N_B = 300, 800
TARGET = (40.0, 35.0, 25.0)

HUMANS = ['std', 'passive', 'aggro', 'skeptic', 'guardian']
ALIENS = ['kill', 'sab', 'infect']
FOREIGNS = ['std', 'hunter', 'kingmaker']


def run(h, a, x, n, seed):
    m.HUMAN_STYLE, m.ALIEN_STYLE, m.FOREIGNER_STYLE = h, a, x
    rng = random.Random(seed)
    wins = Counter()
    nights = 0
    for i in range(n):
        g = m.simulate_one31(rng, i, [], None)
        wins[g.winner] += 1
        nights += g.end_night
    return (100 * wins['human'] / n, 100 * wins['alien'] / n,
            100 * wins['foreigner'] / n, nights / n)


report = []
report.append('# 太空杀 公测3.1 策略交叉收敛报告\n')
report.append('目标均衡：人类 40 / 异形 35 / 外星人 25 ｜ Phase A=300局/格，Phase B=800局/格\n')

print('== Phase A 阵营内横向对比 ==')
report.append('\n## Phase A：阵营内横向对比（基准对手 std/aggro/std）\n')
report.append('| 阵营 | 策略 | 人类% | 异形% | 外星% | 平均夜数 |')
report.append('|---|---|---|---|---|---|')

results = {}
seed = 1000
for h in HUMANS:
    r = run(h, 'kill', 'std', N_A, seed); seed += 1
    results[('human', h)] = r
    report.append('| 人类 | %s | %.1f | %.1f | %.1f | %.1f |' % (h, r[0], r[1], r[2], r[3]))
    print('human %-9s %.1f/%.1f/%.1f' % (h, r[0], r[1], r[2]))
for a in ALIENS:
    r = run('std', a, 'std', N_A, seed); seed += 1
    results[('alien', a)] = r
    report.append('| 异形 | %s | %.1f | %.1f | %.1f | %.1f |' % (a, r[0], r[1], r[2], r[3]))
    print('alien %-9s %.1f/%.1f/%.1f' % (a, r[0], r[1], r[2]))
for x in FOREIGNS:
    r = run('std', 'kill', x, N_A, seed); seed += 1
    results[('foreigner', x)] = r
    report.append('| 外星人 | %s | %.1f | %.1f | %.1f | %.1f |' % (x, r[0], r[1], r[2], r[3]))
    print('foreign %-9s %.1f/%.1f/%.1f' % (x, r[0], r[1], r[2]))

top_human = sorted(HUMANS, key=lambda h: -results[('human', h)][0])[:2]
top_alien = sorted(ALIENS, key=lambda a: -results[('alien', a)][1])[:2]
top_foreign = sorted(FOREIGNS, key=lambda x: -results[('foreigner', x)][2])[:2]
report.append('\n各阵营前 2：人类 %s ｜ 异形 %s ｜ 外星人 %s\n' % (top_human, top_alien, top_foreign))

print('== Phase B 2x2x2 精测 ==')
report.append('\n## Phase B：前 2 名 2×2×2 精测（800 局/格）\n')
report.append('| 人类 | 异形 | 外星 | 人类% | 异形% | 外星% | 夜数 |')
report.append('|---|---|---|---|---|---|---|')
cells = {}
for h in top_human:
    for a in top_alien:
        for x in top_foreign:
            r = run(h, a, x, N_B, seed); seed += 1
            cells[(h, a, x)] = r
            report.append('| %s | %s | %s | %.1f | %.1f | %.1f | %.1f |' % (h, a, x, r[0], r[1], r[2], r[3]))
            print('B %-9s %-9s %-9s %.1f/%.1f/%.1f' % (h, a, x, r[0], r[1], r[2]))

report.append('\n## 稳定性（己方胜率跨 4 格标准差）\n')
report.append('| 阵营 | 策略 | 己方均值% | 标准差 |')
report.append('|---|---|---|---|')
stab = {}
for i, (camp, styles) in enumerate([(0, top_human), (1, top_alien), (2, top_foreign)]):
    for st in styles:
        vals = [v[i] for k, v in cells.items() if k[camp] == st]
        sd = statistics.pstdev(vals)
        stab[(camp, st)] = (sum(vals) / len(vals), sd)
        report.append('| %s | %s | %.1f | %.2f |' % (
            ['人类', '异形', '外星'][camp], st, sum(vals) / len(vals), sd))

# 定版：贴近目标优先（距目标欧氏距离最小的组合），附各阵营稳定性数据
best_dist, best = None, None
for k, v in cells.items():
    d = ((v[0] - TARGET[0]) ** 2 + (v[1] - TARGET[1]) ** 2 + (v[2] - TARGET[2]) ** 2) ** 0.5
    if best_dist is None or d < best_dist:
        best_dist, best = d, k
report.append('\n## 定版推荐（贴近目标 + 低波动）\n')
report.append('最接近目标 40/35/25 的组合：**%s**（%.1f / %.1f / %.1f，距离 %.1f pp）\n' % (
    ' ｜ '.join(best), cells[best][0], cells[best][1], cells[best][2], best_dist))
for (camp, st), (mean, sd) in stab.items():
    report.append('- %s %s：均值 %.1f%%，跨对手标准差 %.2f' % (
        ['人类', '异形', '外星'][camp], st, mean, sd))

with io.open(os.path.join(OUT, 'cross_convergence.md'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(report))
print('report written:', os.path.join(OUT, 'cross_convergence.md'))
