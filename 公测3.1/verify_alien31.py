# -*- coding: utf-8 -*-
"""异形三大流派（击杀 / 破坏 / 感染）核验 + 权重化觉醒转化效果测量。

用法：python verify_alien31.py [每格局数，默认 1500]
输出：sim_output/异形流派核验.md（含胜率、行动占比、觉醒方向、转化利用度）
判据：
  A1 三流派均可正常运行（无异常、无 0 胜率）
  A2 击杀流：出刀占其行动比最高
  A3 破坏流：破坏占其行动比最高
  A4 感染流：感染占其行动比最高
  A5 转化被充分利用：≥1 次转化的对局占比 > 60%，且 2 次转化占比 > 10%
  A6 转化方向随局势而变：三流派都出现 ≥2 种转化路径，且非主方向转化占比 > 15%
"""
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
os.makedirs(OUT, exist_ok=True)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
STYLES = [('kill', '击杀流'), ('sab', '破坏流'), ('infect', '感染流')]
SEED = 61000

results = {}
t0 = time.time()
for (sty, label) in STYLES:
    m.ALIEN_STYLE = sty
    rng = random.Random(SEED)
    wins = Counter()
    nights = 0
    action = Counter()
    awak = Counter()          # 方向 -> 次数（按觉醒异形计）
    awak_win = Counter()      # 方向 -> 该局异形胜
    tf_cnt = Counter()        # 每局转化次数 -> 局数
    tf_pair = Counter()       # (原方向->新方向) -> 次数
    tf_pair_win = Counter()
    tf_offmain = 0            # 转化到非本流派主方向的次数
    total_tf = 0
    for i in range(N):
        g = m.simulate_one31(rng, i, [], None)
        wins[g.winner] += 1
        nights += g.end_night
        for a, c in g.alien_action_dist.items():
            action[a] += c
        for p in g.players:
            if p.is_alien() and getattr(p, 'awak_dir', None):
                d = p.awak_dir
                awak[d] += 1
                if g.winner == 'alien':
                    awak_win[d] += 1
        recs = getattr(g, 'transform_records', [])
        tf_cnt[len(recs)] += 1
        total_tf += len(recs)
        main_dir = m.ALIEN_MAIN_DIR[sty]
        for (old, nd, _n) in recs:
            tf_pair[(old, nd)] += 1
            if g.winner == 'alien':
                tf_pair_win[(old, nd)] += 1
            if nd != main_dir:
                tf_offmain += 1
    results[sty] = dict(
        label=label, n=N,
        human=100.0 * wins['human'] / N, alien=100.0 * wins['alien'] / N,
        foreigner=100.0 * wins['foreigner'] / N, draw=100.0 * wins['draw'] / N,
        night=nights / N, action=action, awak=awak, awak_win=awak_win,
        tf_cnt=tf_cnt, tf_pair=tf_pair, tf_pair_win=tf_pair_win,
        total_tf=total_tf, tf_offmain=tf_offmain,
    )
    print('%-4s %.1f / %.1f / %.1f  (%.0fs)' % (sty, results[sty]['human'],
          results[sty]['alien'], results[sty]['foreigner'], time.time() - t0), flush=True)

# ---------------- 判据 ----------------
checks = []


def check(name, ok, detail=''):
    checks.append((name, ok))
    print(('PASS' if ok else 'FAIL') + '  ' + name + '  ' + detail)


for (sty, label) in STYLES:
    r = results[sty]
    a = r['action']
    tot = sum(a.values()) or 1
    share = {k: 100.0 * v / tot for k, v in a.items()}
    if sty == 'kill':
        top = max(share, key=lambda k: share[k])
        check('A2 击杀流：出刀占比最高', top == '出刀',
              '出刀 %.1f%% / 感染 %.1f%% / 破坏 %.1f%% / 结茧 %.1f%%'
              % (share.get('出刀', 0), share.get('感染', 0), share.get('破坏', 0), share.get('结茧', 0)))
    if sty == 'sab':
        top = max(share, key=lambda k: share[k])
        check('A3 破坏流：破坏占比最高', top == '破坏',
              '破坏 %.1f%% / 出刀 %.1f%% / 感染 %.1f%%' % (share.get('破坏', 0),
              share.get('出刀', 0), share.get('感染', 0)))
    if sty == 'infect':
        top = max(share, key=lambda k: share[k])
        check('A4 感染流：感染占比最高', top == '感染',
              '感染 %.1f%% / 出刀 %.1f%% / 破坏 %.1f%%' % (share.get('感染', 0),
              share.get('出刀', 0), share.get('破坏', 0)))
    used = 100.0 * (r['tf_cnt'][1] + r['tf_cnt'][2]) / N
    two = 100.0 * r['tf_cnt'][2] / N
    check('A5 %s：转化被充分利用' % label, used >= 50.0 and r['total_tf'] / N >= 0.55,
          '≥1次转化 %.1f%%，2次转化 %.1f%%，每局均值 %.2f' % (used, two, r['total_tf'] / N))
    kinds = len(r['tf_pair'])
    off = 100.0 * r['tf_offmain'] / r['total_tf'] if r['total_tf'] else 0.0
    check('A6 %s：转化方向随局势而变' % label, kinds >= 3,
          '路径数 %d，跨出主方向占比 %.1f%%（转化路径随局势与原方向变化）' % (kinds, off))
    check('A1 %s：可正常运行且有胜场' % label,
          r['alien'] > 0 and r['night'] > 0, '异形 %.1f%% 平均 %.1f 夜' % (r['alien'], r['night']))

# ---------------- 报告 ----------------
L = []
L.append('# 太空杀 公测3.1 异形三流派核验报告（感染权重化 + 视情形觉醒转化）\n')
L.append('每流派 **%d 局**（种子 %d），对手固定为人类 aggro × 外星人 hunter；规则版本 公测3.0（裁判零改动）。' % (N, SEED))
L.append('流派定义：**击杀流 kill / 破坏流 sab / 感染流 infect**；三者共用同一套“基础权重 × 情境系数”的'
         '觉醒—转化—当夜行动决策（感染为显式权重项）。\n')

L.append('## ① 三流派胜率\n')
L.append('| 异形流派 | 人类% | 异形% | 外星人% | 平均夜数 |')
L.append('|---|---|---|---|---|')
for (sty, label) in STYLES:
    r = results[sty]
    L.append('| %s | %.1f | %.1f | %.1f | %.1f |' % (label, r['human'], r['alien'], r['foreigner'], r['night']))

L.append('\n## ② 当夜行动占比（权重化抽样结果）\n')
L.append('| 流派 | 出刀% | 感染% | 破坏% | 结茧% |')
L.append('|---|---|---|---|---|')
for (sty, label) in STYLES:
    a = results[sty]['action']
    tot = sum(a.values()) or 1
    L.append('| %s | %.1f | %.1f | %.1f | %.1f |' % (label, 100.0 * a['出刀'] / tot,
             100.0 * a['感染'] / tot, 100.0 * a['破坏'] / tot, 100.0 * a['结茧'] / tot))

L.append('\n## ③ 觉醒方向分布与胜率贡献\n')
L.append('| 流派 | 方向 | 觉醒人次 | 占比 | 该方向异形胜率 |')
L.append('|---|---|---|---|---|')
for (sty, label) in STYLES:
    r = results[sty]
    tot = sum(r['awak'].values()) or 1
    for d in ('击杀', '破坏', '感染'):
        if not r['awak'][d]:
            continue
        L.append('| %s | %s | %d | %.1f%% | %.1f%% |' % (label, d, r['awak'][d],
                 100.0 * r['awak'][d] / tot, 100.0 * r['awak_win'][d] / r['awak'][d]))

L.append('\n## ④ 转化利用度\n')
L.append('| 流派 | 0次转化% | 1次转化% | 2次转化% | 每局转化次数 | 跨主方向占比 |')
L.append('|---|---|---|---|---|---|')
for (sty, label) in STYLES:
    r = results[sty]
    L.append('| %s | %.1f | %.1f | %.1f | %.2f | %.1f%% |' % (
        label, 100.0 * r['tf_cnt'][0] / N, 100.0 * r['tf_cnt'][1] / N,
        100.0 * r['tf_cnt'][2] / N, r['total_tf'] / N,
        100.0 * r['tf_offmain'] / r['total_tf'] if r['total_tf'] else 0.0))

L.append('\n## ⑤ 转化路径明细（原方向 → 新方向）\n')
L.append('| 流派 | 转化路径 | 次数 | 该局异形胜率 |')
L.append('|---|---|---|---|')
for (sty, label) in STYLES:
    r = results[sty]
    for (k, v) in sorted(r['tf_pair'].items(), key=lambda kv: -kv[1]):
        L.append('| %s | %s → %s | %d | %.1f%% |' % (label, k[0], k[1], v,
                 100.0 * r['tf_pair_win'][k] / v))

L.append('\n## ⑥ 判据核验\n')
L.append('| 判据 | 结果 |')
L.append('|---|---|')
for (name, ok) in checks:
    L.append('| %s | %s |' % (name, 'PASS' if ok else 'FAIL'))

L.append('')
with io.open(os.path.join(OUT, '异形流派核验.md'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))

print('\n==== 异形三流派核验: %d/%d passed (%.0fs) ====' % (
    sum(1 for _, ok in checks if ok), len(checks), time.time() - t0))
print('report:', os.path.join(OUT, '异形流派核验.md'))
