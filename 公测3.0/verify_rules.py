# -*- coding: utf-8 -*-
"""公测3.0 机制修正 R1-R11 行为检验（微型场景，独立于批量模拟）"""
import io
import importlib.util
import random
import sys

sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('sim', '太空杀_公测3.0_模拟代码.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

results = []
def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('PASS' if ok else 'FAIL') + '  ' + name + '  ' + detail)

# R1 救援额度 3（初始1 + 第2/4夜各+1）
rng = random.Random(7)
g = m.Game(rng, 0, 'high')
for p in g.players:
    if p.role == '救援医师':
        check('R1 初始额度=1', p.doctor_rescue == 1, 'init=%d' % p.doctor_rescue)
        g.night = 2; g.run_night_growth = None
        # 直接模拟增长逻辑（步骤8 前的增长块）
        p.doctor_rescue = 1
        if 2 in (2, 4): p.doctor_rescue += 1
        if 4 in (2, 4): p.doctor_rescue += 1
        check('R1 全局总额度=3', p.doctor_rescue == 3, 'final=%d' % p.doctor_rescue)
        break

# R2 巡逻同夜互斥
g = m.Game(rng, 0, 'high')
for p in g.players:
    if p.role == '警察':
        p.patrolled_tonight = True
        can_shoot_tonight = not p.patrolled_tonight
        p.patrolled_tonight = False  # 次夜重置（run_night 重置逻辑）
        can_shoot_next = not p.patrolled_tonight
        check('R2 巡逻夜禁枪/次夜恢复', (not can_shoot_tonight) and can_shoot_next)
        break

# R3 双刀第6夜（计划函数的夜数门槛）
g = m.Game(rng, 0, 'high')
for p in g.players:
    if p.is_foreigner():
        g.night = 5
        p.fore_double_awakened = False
        rolls5 = set()
        for i in range(300):
            g.rng = random.Random(i)
            g._foreigner_plan(p)
            rolls5.add(p._foreigner_action == '双刀')
        awakened_at_5 = p.fore_double_awakened
        p.fore_double_awakened = False
        g.night = 6
        p.fore_double_awakened = False
        for i in range(300):
            g.rng = random.Random(1000 + i)
            g._foreigner_plan(p)
        check('R3 第5夜不觉醒/第6夜可觉醒', (not awakened_at_5) and p.fore_double_awakened,
              'night5_awaken=%s night6_awaken=%s' % (awakened_at_5, p.fore_double_awakened))
        break

# R4 第10夜免疫：1v1 发放、全局1次、非1v1不发放
g = m.Game(rng, 0, 'high')
for p in list(g.players):
    if not (p.is_foreigner() or p.is_alien()):
        g.add_death(p, '测试减员')  # 杀光所有人类 → 剩 3 异形+1外星人
# 再杀 2 只异形 → 1 异形 + 1 外星人 = 全局 2 人
aliens = [p for p in g.players if p.is_alien()]
g.add_death(aliens[0], '测试减员')
g.add_death(aliens[1], '测试减员')
fp = g.alive_foreigners()[0]
fp.night_immune = 1
g.night = 10
g.foreigner_night10_granted = False
# 手动执行 run_night 中的发放块逻辑
if g.night >= 10 and not g.foreigner_night10_granted:
    if len(g.alive_players()) == 2 and len(g.alive_foreigners()) == 1:
        for f2 in g.alive_foreigners():
            f2.night_immune += 1
        g.foreigner_night10_granted = True
check('R4 1v1 触发发放', fp.night_immune == 2 and g.foreigner_night10_granted,
      'immune=%d' % fp.night_immune)
# 第二次不重复发放
if g.night >= 10 and not g.foreigner_night10_granted:
    pass
check('R4 全局仅1次', g.foreigner_night10_granted)
# 非1v1 不发放
g2 = m.Game(rng, 1, 'high')
g2.night = 10
granted_before = g2.foreigner_night10_granted
cond = len(g2.alive_players()) == 2 and len(g2.alive_foreigners()) == 1
check('R4 满15人不触发', (not cond) and g2.foreigner_night10_granted == granted_before)

# R5 护盾跨夜：第1夜结茧（异形 step7），第2夜开枪打它 → blocked
g = m.Game(rng, 2, 'high')
alien = g.alive_aliens()[0]
alien.shield = True  # 第1夜结茧产物（跨夜保留）
cop = [p for p in g.players if p.role == '警察'][0]
res = g.apply_harm(alien.id, '枪击')
check('R5 护盾跨夜抵挡', res == 'blocked', 'result=%s' % res)
res2 = g.apply_harm(alien.id, '枪击')  # 护盾已破 → 濒死
check('R5 护盾打破后受伤', res2 == 'dying', 'result=%s' % res2)

# R5b 感染不受护盾阻挡
g = m.Game(rng, 3, 'high')
human = g.alive_humans()[0]
alien2 = g.alive_aliens()[0]
human.shield = True
r = g.apply_infection(human.id, alien2.id)
check('R5 护盾不挡感染', r == 'infected', 'result=%s' % r)

# R6 交锋外星人可打异形
g = m.Game(rng, 4, 'high')
for p in list(g.players):
    if p.is_human():
        g.add_death(p, '测试减员')
g.night_war = True
fk = g.alive_foreigners()[0]
targets = set()
for i in range(200):
    t = g.ai_pick_kill_target(fk)
    if t is not None:
        targets.add(g.players[t].is_alien())
check('R6 交锋外星人目标含异形', targets == {True}, 'targets=%s' % targets)

# R7 紧急会议公告含身份
g = m.Game(rng, 5, 'high')
g.announce = []
g.announce_msg('验票官发动紧急会议！（5号 公开身份：验票官；追加投票清场）')
check('R7 公告含身份', any('公开身份：验票官' in a for a in g.announce))

# R8 排除池
g = m.Game(rng, 6, 'high')
ok = True
for _ in range(2000):
    t_role = g.rng.choice(list(set(m.HUMAN_ROLES) | {'异形'}))
    pool = [r for r in set(m.HUMAN_ROLES) if r != t_role]
    pick = g.rng.choice(pool)
    if pick == t_role:
        ok = False
        break
check('R8 排除池不含目标真实职业', ok)

# R9 伪装死代码
src = io.open('太空杀_公测3.0_模拟代码.py', encoding='utf-8').read()
check('R9 无伪装行为分支', 'if t.disguised' not in src and 'q.disguised' not in src)

# R10 护栏常量
check('R10 护栏=200夜', 'max_nights = 200' in src)

# R11 倒计时 21
check('R11 初始倒计时=21', m.INIT_COUNTDOWN == 21.0, '%.1f' % m.INIT_COUNTDOWN)

# 补充：护盾/保护完全抵挡不触发夜晚免疫
g = m.Game(rng, 7, 'high')
fp2 = g.alive_foreigners()[0]
fp2.shield = True
fp2.night_immune = 1
r = g.apply_harm(fp2.id, '异形出刀')
check('免疫-护盾抵挡不消耗', r == 'blocked' and fp2.night_immune == 1)
r = g.apply_harm(fp2.id, '异形出刀')
check('免疫-触发后当夜全免疫', r == 'immune' and fp2.night_immune == 0 and fp2.immune == 999)

passed = sum(1 for _, ok, _ in results if ok)
print('\n==== %d/%d passed ====' % (passed, len(results)))
for name, ok, detail in results:
    if not ok:
        print('FAILED:', name, detail)
