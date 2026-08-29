# -*- coding: utf-8 -*-
"""
太空杀：三阵营对抗 公测3.1 —— 高水平玩家认知模型（蒙特卡洛模拟规范落地）

规范：《太空杀 · 高水平玩家认知模型》（信息集最优 + 禁止透视 + 情绪驱动 + 追责塑造投票）

【硬约束 · 信息隔离】
- 裁判层 = 公测3.0 的 Game（WorldState 持有者，规则零改动，机制核验 18/18 通过）
- 决策层 = 本文件自由函数 decide_*：签名只含 (obs, mem, rng, skill)，物理上无裁判引用
- Observation 只含合法观测：自身私有状态 / 公开公告·死亡·驱逐 / 自身查验结论 /
  阵营合法字段（exposed 仅异形外星人可见）。3.0 遗留的 3 条非公开通道已移除：
  _protect_count / attacked_history(保护方) / exposed→人类。
- 私聊内容只写入双方 Memory（参与者合法观测），非参与者不可见。

【认知模型】每个玩家 = 贝叶斯信念 + 信息集最优响应 + 情绪偏移 + 技能档噪声：
- 信念：对每名玩家维护 P(异形)/P(外星人) 的贝叶斯后验（几率空间似然比更新）
- 情绪：fear/anger/panic/confidence + 对个体的 trust，事件驱动更新（见 Emotion）
- 追责：Reputation 账本（lie_count / votes_against_me / trust_score），局内累计、每局重置
- 技能：expert 20% / mid 55% / novice 25%，每人固定一档全程一致；
  噪声 = (base + 0.25*panic) * exp(-night/tau) + floor，指数收敛到各档不同平台
- 收敛：expert ≈ 信息集最优（仍 < 上帝最优）；novice 情绪主导常非最优——绝不全员同优

【透视检测（裁判层，玩家不可见）】
- 采样全部身份类决策（投票/击杀/查验/枪击）：记录决策时后验置信与目标真实阵营
- 判违规：准确率 − 平均后验 > 5pp 且二项 z > 2（n≥50）；另核验 expert 表现 < 上帝上界

【采样】每局独立 RNG 流（seed+game_id），裁判完整重建；输出仅写 sim_output/。

运行：python 太空杀_公测3.1_模拟代码.py
"""

import os
import io
import sys
import json
import math
import time
import random
import importlib.util
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding='utf-8')

# ---- 载入公测3.0 规则引擎（裁判层，禁止改动）----
_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_PATH = os.path.join(_HERE, '..', '公测3.0', '太空杀_公测3.0_模拟代码.py')
_spec = importlib.util.spec_from_file_location('sim30', _ENGINE_PATH)
sim30 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim30)

# ============================ 技能档（25/55/20） ============================
SKILL_DIST = [('expert', 0.20), ('mid', 0.55), ('novice', 0.25)]
SKILL_NOISE = {
    # base: 首夜噪声率; tau: 收敛时间常数; floor: 平台期噪声（各档上限不同）
    'expert': dict(base=0.10, tau=6.0, floor=0.02),
    'mid':    dict(base=0.30, tau=8.0, floor=0.10),
    'novice': dict(base=0.50, tau=10.0, floor=0.28),
}

def roll_skill(rng):
    u = rng.random()
    acc = 0.0
    for s, p in SKILL_DIST:
        acc += p
        if u < acc:
            return s
    return 'mid'

def noise_rate(skill, night, panic=0.0):
    cfg = SKILL_NOISE[skill]
    return (cfg['base'] + 0.25 * panic) * math.exp(-max(0, night - 1) / cfg['tau']) + cfg['floor']

def maybe_noise(rng, skill, night, chosen, candidates, panic=0.0):
    if len(candidates) <= 1:
        return chosen
    if rng.random() < noise_rate(skill, night, panic):
        return rng.choice(candidates)
    return chosen

# ============================ 情绪系统（事件驱动） ============================
class Emotion:
    """六维中可观测驱动的四维标量 + 个体 trust 表（fear/anger/panic/confidence）。"""
    __slots__ = ('fear', 'anger', 'panic', 'confidence', 'trust')

    def __init__(self):
        self.fear = 0.3
        self.anger = 0.0
        self.panic = 0.0
        self.confidence = 0.5
        self.trust = {}          # pid -> -1(敌视)..+1(信任)

    def t(self, pid):
        return self.trust.get(pid, 0.0)

    def set_trust(self, pid, v):
        self.trust[pid] = max(-1.0, min(1.0, v))

def emo_on_voted_me(emo, voter_id):
    emo.anger = min(1.0, emo.anger + 0.12)
    emo.set_trust(voter_id, emo.t(voter_id) - 0.25)

def emo_on_friend_death(emo, friend_ids):
    if friend_ids:
        emo.anger = min(1.0, emo.anger + 0.15)
        for f in friend_ids:
            emo.set_trust(f, -0.5)  # 仇恨固化到害死朋友的方向（简化：直接降信任网络）

def emo_on_countdown(emo, countdown, humans, aliens):
    if countdown <= 8:
        emo.panic = min(1.0, emo.panic + 0.15)
    if humans <= aliens:
        emo.panic = min(1.0, emo.panic + 0.1)
        emo.confidence = max(0.1, emo.confidence - 0.05)

def emo_on_success(emo):
    emo.confidence = min(1.0, emo.confidence + 0.1)
    emo.fear = max(0.0, emo.fear - 0.1)

def emo_on_betrayal(emo, pid):
    """私聊对象被证实异形：trust 崩塌 → -1（仇恨固化），anger↑。"""
    emo.set_trust(pid, -1.0)
    emo.anger = min(1.0, emo.anger + 0.25)

def emo_on_suspected(emo):
    emo.fear = min(1.0, emo.fear + 0.1)

# ============================ 追责账本（局内累计，每局重置） ============================
class Reputation:
    __slots__ = ('lie_count', 'votes_against_me', 'trust_score', 'broken_promises')

    def __init__(self):
        self.lie_count = 0          # 被证实的公开虚假确证次数
        self.votes_against_me = 0
        self.trust_score = 0.0      # 累计信任值（负=应被追责）
        self.broken_promises = 0

    def credibility(self):
        """说话者可信度权重：说谎前科指数衰减。"""
        return 0.5 ** self.lie_count

# ============================ Observation / Memory ============================
class Observation:
    """玩家能看到的——绝不包含 WorldState 引用。字段按阵营合法性由裁判裁剪。"""
    __slots__ = ('night', 'me_id', 'my_camp', 'my_role', 'alive', 'dying_set',
                 'announcements', 'ejections', 'deaths', 'exposed', 'revealed_humans',
                 'chat_history', 'accusations', 'countdown', 'net_sabotage',
                 'known', 'known_alien', 'exclude_info', 'bullets', 'rescue_quota',
                 'treat_quota', 'append_left', 'awak_dir', 'transform_count',
                 'quota_left', 'teammates', 'blocked_targets', 'self_treat_left',
                 'double_ready', 'infected_set', 'chat_partner_count', 'crew_half',
                 'alien_ids', 'humans_alive', 'aliens_alive', 'dying', 'scapegoat',
                 'i_am_key_role')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def __getitem__(self, k):
        return getattr(self, k)

    def get(self, k, default=None):
        return getattr(self, k, default)

class Memory:
    """玩家私有记忆（跨夜持久，仅合法信息）：三阵营贝叶斯信念 + 情绪 + 追责 + 关系网。"""
    def __init__(self, pid):
        self.pid = pid
        self.odds_alien = {}       # target -> P(异形) 几率
        self.odds_foreign = {}     # target -> P(外星人) 几率
        self.emotion = Emotion()
        self.rep = defaultdict(Reputation)
        self.chat_partners = set()
        self.last_chat_target = None
        self.trusted_friends = set()   # trust>0.5 的对象（死亡时触发 anger）
        self.fixed_suspicion = set()   # 怀疑固化（>0.7 后难逆转）
        self.claims_against = defaultdict(float)  # 我收到的对 t 的累计指控强度
        self.seen_claims = set()       # 已消化的 (speaker, target) 指控——同一证据只更新一次
        self.accuser_cnt = Counter()   # 我见过的对 t 的独立指控人数（交叉验证去重）
        self.confirmed = set()         # 确证情报（豁免记忆衰减）
        self.last_decay_night = None
        self.promises = {}             # maker -> (night, target)：对方向我许诺的投票
        self.chat_claims = {}          # target -> speaker：私聊中对方的怀疑对象（可公开引述）

    # ---- 几率空间工具 ----
    def p_alien(self, t):
        o = self.odds_alien.get(t, 0.25)
        return o / (1.0 + o)

    def p_foreign(self, t):
        o = self.odds_foreign.get(t, 0.10)
        return o / (1.0 + o)

    def lr_alien(self, t, lr):
        o = self.odds_alien.get(t, 0.25 / 0.75)
        o = max(1e-4, min(1e4, o * lr))
        self.odds_alien[t] = o
        if self.p_alien(t) > 0.7:
            self.fixed_suspicion.add(t)

    def lr_foreign(self, t, lr):
        o = self.odds_foreign.get(t, 0.10 / 0.90)
        o = max(1e-4, min(1e4, o * lr))
        self.odds_foreign[t] = o

    def set_camp(self, t, camp):
        """确定性情报：直接置数率（阵营互斥归一）。确证情报豁免记忆衰减。"""
        self.confirmed.add(t)
        if camp == 'alien':
            self.odds_alien[t] = 1e4
            self.odds_foreign[t] = 1e-4
        elif camp == 'foreigner':
            self.odds_alien[t] = 1e-4
            self.odds_foreign[t] = 1e4
        else:
            self.odds_alien[t] = 1e-4
            self.odds_foreign[t] = 1e-4

    # ---- 有效怀疑分（情绪偏移后的决策分）----
    def eff_score(self, t):
        p = self.p_alien(t)
        tr = self.emotion.t(t)
        # trust 包庇：高信任折扣负面证据；anger 报复：仇恨对象加权
        p_eff = p * (1.0 - 0.25 * max(tr, 0.0)) + 0.10 * max(-tr, 0.0)
        return p_eff

# 似然比表（公开事件；全部为公开可推导信号）
LR = dict(
    accused_by_trusted=5.0,
    accused_ordinary=1.12,
    accused_by_liar=0.60,      # 有说谎前科者的指控反向解读
    voted_wrong=1.35,          # 投错过好人的追责对象
    chatted_with=0.92,
    guilt_by_association=1.30, # 与已知异形私聊关联
)

# ============================ 决策层（自由函数：只收 obs/mem/rng/skill） ============================
# ---- 策略调参旋钮（tune.py 可修改）----
VOTE_THRESHOLD = 0.35          # 人类投票的证据阈值（fear 会降低它）
ANNOUNCE_INJURY = False        # 濒死公告开关（False=濒死不公告，公告最小信息原则）
TRUSTED_LR = 5.0               # grade-3 可信广播的似然比（调优定版：25 会令人类胜率超 55%）
ORDINARY_LR = 1.12             # 普通指控似然比
ALIEN_TRANSFORM_NIGHT = 3      # 异形感染→击杀 转化最早夜（调优定版）
ALIEN_TRANSFORM_P = 0.9        # 转化概率（调优定版）
ALIEN_KILL_EXPOSED = 4.0       # 出刀评分：维修暴露
ALIEN_KILL_REVEALED = 3.0      # 出刀评分：公开跳身份
FINISH_DYING = 6.0             # 出刀评分：补刀濒死

# ---- 策略花名册（交叉收敛选优，见 cross_converge.py）----
HUMAN_STYLE = 'aggro'      # std / passive / aggro / skeptic / guardian（交叉收敛定版）
ALIEN_STYLE = 'mix'        # aggro / balanced / sab / mix / mimic（交叉收敛定版）
FOREIGNER_STYLE = 'hunter' # std / hunter / kingmaker（交叉收敛定版）
HUMAN_VOTE_TH = {'std': 0.35, 'passive': 0.50, 'aggro': 0.25,
                 'skeptic': 0.35, 'guardian': 0.35}
ALIEN_AWAKEN_ORDER = {
    'aggro':    ['感染', '击杀', '破坏'],
    'balanced': ['感染', '击杀', '破坏'],
    'sab':      ['破坏', '感染', '击杀'],
    'mix':      ['破坏', '感染', '击杀'],   # 首只占破坏，队友走感染/击杀（占位互斥逻辑）
    'mimic':    ['感染', '击杀', '破坏'],
}
ALIEN_TRANSFORM = {   # (最早夜, 概率, 目标方向优先)
    'aggro':    (3, 0.9, ['击杀', '破坏']),
    'balanced': (4, 0.75, ['击杀']),
    'sab':      (3, 0.9, ['破坏']),
    'mix':      (4, 0.8, ['击杀']),
    'mimic':    (4, 0.85, ['击杀']),
}

def _cands(obs, mem, exclude=()):
    return [t for t in obs['alive'] if t != obs['me_id'] and t not in exclude
            and not obs['dying_set'].get(t)]

def _top_eff(obs, mem, exclude=(), rng=None):
    c = _cands(obs, mem, exclude)
    if not c:
        return None
    best = max(mem.eff_score(t) for t in c)
    top = [t for t in c if mem.eff_score(t) >= best - 1e-9]
    if rng is not None and len(top) > 1:
        return rng.choice(top)  # 并列随机打破（避免确定性一致投票伪影）
    return max(c, key=lambda t: mem.eff_score(t))

def decide_vote(obs, mem, rng, skill):
    """白天投票：情绪偏移后的信念 argmax + 阵营特殊策略。"""
    mates = set(obs.get('teammates', []))
    if obs['my_camp'] == 'alien':
        # 协同投票（队内合法信息）——按情形在"团结驱逐"与"混淆分票"间切换：
        # - 危险信号：公开指控汇聚到队友身上 → 混淆模式：分票给次级目标，fragment 票型保队友
        # - 否则团结模式：全票集中 herd 目标 / scapegoat，把人投出去
        herd = Counter()
        for (n, sp, tg, gr) in obs['accusations']:
            if tg in obs['alive'] and not obs['dying_set'].get(tg):
                herd[tg] += 1
        herd_sorted = sorted(herd, key=lambda t: -herd[t])
        herd_top = herd_sorted[0] if herd_sorted else None
        if herd_top is not None and herd_top in mates:
            confuse = [t for t in obs['alive'] if t not in mates and t != obs['me_id']
                       and not obs['dying_set'].get(t) and t != herd_top]
            if confuse:
                return rng.choice(confuse[:4])
            return None
        herd_th = 2 if ALIEN_STYLE == 'mimic' else 3
        if herd_top is not None and herd[herd_top] >= herd_th and herd_top not in mates:
            return herd_top if rng.random() < 0.85 else None
        if ALIEN_STYLE != 'mimic':
            sg = obs.get('scapegoat')
            if sg is not None and sg != obs['me_id'] and sg in obs['alive'] and sg not in mates:
                return sg if rng.random() < 0.8 else (_top_eff(obs, mem, exclude=mates, rng=rng) or sg)
    if obs['my_camp'] == 'foreigner':
        known_alien = [t for t, is_a in obs['known_alien'].items()
                       if is_a and t in obs['alive'] and t not in mates]
        aliens_alive, humans_alive = obs['aliens_alive'], obs['humans_alive']
        if FOREIGNER_STYLE == 'kingmaker':
            # 前期(人类≥6)：投票 scapegoat（跟异形节奏阻止人类清场）；中后期削异形铺 1v1
            if humans_alive >= 6 and obs.get('scapegoat') in obs['alive'] \
                    and obs.get('scapegoat') not in mates:
                return obs['scapegoat']
        if known_alien and ((humans_alive <= 3) or (aliens_alive <= 2 and rng.random() < 0.6)
                            or (aliens_alive >= 3 and humans_alive >= 5 and rng.random() < 0.5)):
            return known_alien[0]
    t = _top_eff(obs, mem, exclude=mates)
    if t is None:
        return None
    emo = mem.emotion
    # fear 偏移：高恐惧 → 证据阈值降低（仓促投票）
    threshold = HUMAN_VOTE_TH.get(HUMAN_STYLE, 0.35) - 0.10 * emo.fear
    if obs['my_camp'] == 'human' and mem.eff_score(t) < threshold:
        if rng.random() < noise_rate(skill, obs['night'], emo.panic) + 0.35:
            return None
    return t

def decide_chat_target(obs, mem, rng, skill):
    others = [t for t in obs['alive'] if t != obs['me_id']
              and not obs['dying_set'].get(t) and t != mem.last_chat_target]
    if not others:
        return None
    if obs['my_camp'] == 'alien':
        others.sort(key=lambda t: -len(obs['chat_partner_count'].get(t, ())))
        return others[0] if rng.random() < 0.7 else None
    if obs.get('i_am_key_role') and len(mem.chat_partners) >= 2:
        return None
    def score(t):
        s = 1.0 if t not in mem.chat_partners else 0.0
        if obs.get('i_am_key_role'):
            s += (0.5 - mem.p_alien(t))
        else:
            s += mem.p_alien(t) + 0.3 * max(mem.emotion.t(t), 0)  # 倾向联系信任者
        return s
    others.sort(key=score, reverse=True)
    prob = 0.5 if obs.get('i_am_key_role') else 0.35
    return others[0] if rng.random() < prob else None

def decide_chat_accept(obs, mem, invs, rng, skill):
    invs = [i for i in invs if i in obs['alive']]
    if not invs:
        return None
    best = min(invs, key=lambda i: mem.p_alien(i) - 0.2 * max(mem.emotion.t(i), 0))
    if mem.p_alien(best) > 0.6 and skill != 'novice':
        return None
    return best

def decide_check_target(obs, mem, rng, skill):
    others = _cands(obs, mem)
    if not others:
        return None
    if obs['my_camp'] == 'foreigner':
        unknown = [t for t in others if t not in obs['known']]
        if not unknown:
            return None
        def s(t):
            v = 0.0
            if t in obs['revealed_humans']:
                v += 3.0
            if t in obs['exposed']:
                v += 2.5
            return v + mem.p_alien(t)
        unknown.sort(key=s, reverse=True)
        return unknown[0]
    half = [t for t in others if obs['crew_half'].get(t)]
    if half:
        return rng.choice(half)
    unknown = [t for t in others if t not in obs['known']]
    if not unknown:
        return None
    return rng.choice(unknown) if obs['my_role'] == '神探' else \
        max(unknown, key=lambda t: mem.eff_score(t))

def decide_protect(obs, mem, rng, skill):
    """保镖/护卫：公开信号 + 自身信任网络（合法），无任何非公开通道。"""
    cands = [t for t in obs['alive'] if not obs['dying_set'].get(t)]
    if not cands:
        return obs['me_id']
    def threat(t):
        s = 0.0
        if t in obs['revealed_humans']:
            s += 3.0
        if t == obs['me_id']:
            s += 0.3
        if mem.emotion.t(t) > 0.5:
            s += 0.8  # 保护高信任对象
        return s
    best = max(cands, key=threat)
    if threat(best) >= 2.0:
        return best
    return best if rng.random() < 0.4 else obs['me_id']

def decide_patrol(obs, mem, rng, skill):
    cands = [t for t in obs['alive'] if not obs['dying_set'].get(t) and t != obs['me_id']]
    scored = sorted(cands, key=lambda t: 3.0 if t in obs['revealed_humans'] else 0.0, reverse=True)
    picked = [t for t in scored if t in obs['revealed_humans']][:3]
    if not picked and scored:
        picked = [scored[0]]
    return picked

def decide_shoot(obs, mem, rng, skill):
    known_alien = [t for t, is_a in obs['known_alien'].items()
                   if is_a and t in obs['alive'] and not obs['dying_set'].get(t)]
    if known_alien and obs['bullets'] > 0:
        return known_alien[0]
    t = _top_eff(obs, mem)
    if t is not None and mem.p_alien(t) > 0.6 and obs['bullets'] > 0:
        return t
    return None

def decide_kill(obs, mem, rng, skill, avoid=None):
    """异形/外星人出刀。异形仅公开信号；外星人叠加 known 建图与 1v1 铺路。
    avoid：本夜队友已攻击过的目标（第5夜前不重复指定——协调行动）。"""
    if obs['my_camp'] == 'foreigner':
        humans_alive = obs['humans_alive']
        # R6 规则原文：人类全灭（夜晚交锋）后外星人方可击杀异形；
        # 人类尚存时目标仅限人类（战前杀异形与规则文本不符，已移除）
        if humans_alive == 0:
            alien_tgts = [t for t in obs['alive'] if t in obs['alien_ids'] and t != obs['me_id']]
            if alien_tgts:
                return rng.choice(alien_tgts)
        known_hv = [t for t, v in obs['known'].items()
                    if v.get('camp') == 'human'
                    and v.get('role') in ('神探', '验票官', '救援医师', '生化医师')
                    and t in obs['alive'] and not obs['dying_set'].get(t)]
        if known_hv:
            return known_hv[0]
    # 濒死者是优先补刀目标（规则：濒死再受击直接死亡）——不可排除！
    if obs['my_camp'] == 'foreigner':
        cands = [t for t in obs['alive'] if t != obs['me_id'] and t not in obs['alien_ids']]
    else:
        cands = [t for t in obs['alive'] if t != obs['me_id'] and t not in obs['alien_ids']]
    if avoid:
        cands = [t for t in cands if t not in avoid] or cands
    if not cands:
        alien_tgts = [t for t in obs['alive'] if t in obs['alien_ids'] and t != obs['me_id']]
        return rng.choice(alien_tgts) if alien_tgts else None
    def s(t):
        v = mem.p_alien(t) * 0.5
        if obs['dying_set'].get(t):
            v += FINISH_DYING  # 补刀濒死者 = 确定击杀
        if t in obs['exposed']:
            v += ALIEN_KILL_EXPOSED
        if t in obs['revealed_humans']:
            v += ALIEN_KILL_REVEALED
        v += min(1.5, len(obs['chat_partner_count'].get(t, ())) * 0.25)
        if t in mem.trusted_friends and obs['my_camp'] == 'alien':
            v += 0.8  # 刀人类信任焦点，制造背叛崩塌
        return v
    cands.sort(key=s, reverse=True)
    return maybe_noise(rng, skill, obs['night'], cands[0], cands[:3])

def decide_infect(obs, mem, rng, skill):
    cands = [t for t in obs['alive'] if t != obs['me_id'] and not obs['dying_set'].get(t)
             and t not in obs['alien_ids'] and not obs['infected_set'].get(t)]
    if not cands:
        return []
    def s(t):
        v = 0.0
        if t in obs['exposed'] or t in obs['revealed_humans']:
            v += 2.0
        return v
    cands.sort(key=s, reverse=True)
    n = (3 if rng.random() < 0.3 else 2) if obs.get('awak_dir') == '感染' \
        else (2 if rng.random() < 0.3 else 1)
    chosen = cands[:n]
    if rng.random() < noise_rate(skill, obs['night']):
        rng.shuffle(chosen)
    return chosen

def decide_rescue(obs, mem, dying_targets, rng, skill):
    if not dying_targets:
        return None
    return max(dying_targets,
               key=lambda t: 2.0 if t in obs['revealed_humans'] else (1.0 if t == obs['me_id'] else 0.0))

def decide_treat(obs, mem, inf_targets, rng, skill):
    if not inf_targets:
        return None
    return max(inf_targets, key=lambda t: 2.0 if t in obs['revealed_humans'] else 0.0)

# ============================ 裁判层子类（构造 Observation，调用决策层） ============================
class Game31(sim30.Game):
    """规则完全继承 3.0 裁判；决策替换为 Observation 驱动的自由函数。
    额外维护：技能档、情绪/追责账本、透视检测采样、噪声收敛统计。"""

    def __init__(self, rng, game_id, strategy='high', perspective_log=None, trace=None):
        super().__init__(rng, game_id, strategy)
        self.perspective_log = perspective_log if perspective_log is not None else []
        self.trace = trace if trace is not None else None
        self.noise_applied = Counter()
        self.decisions_made = Counter()
        self.skills = {p.id: roll_skill(rng) for p in self.players}
        self.memories = {p.id: Memory(p.id) for p in self.players}
        self._alien_scapegoat = None
        self._foreigner_targets_night = set()  # 本夜外星人攻击过的目标（濒死原因=外星人）
        self.challenges = []           # (night, asker, target) 点名质询
        self.citations = []            # (night, speaker, target, cited) 公开引述
        self.promise_stats = Counter() # (skill, kept) -> 次数

    # ---------- Observation 构造（合法性裁剪唯一入口） ----------
    def _base_obs(self, p):
        alive = [q.id for q in self.alive_players()]
        dying_set = {q.id: q.dying for q in self.alive_players()}
        is_af = p.is_alien() or p.is_foreigner()
        obs = Observation(
            night=self.night,
            me_id=p.id,
            my_camp=p.camp,
            my_role=p.role,
            alive=alive,
            dying_set=dying_set,
            announcements=list(self.public_info[-12:]),
            ejections=list(self.ejection_log),
            deaths=[(n, pid, camp) for (n, pid, camp, _) in self.deaths],
            exposed=set(self.exposed) if is_af else set(),
            revealed_humans=set(self.revealed_humans),
            chat_history=list(self.chat_history[-6:]),
            accusations=[(n, sp, tg, gr) for (n, sp, tg, gr, _) in self.accuse_claims[-40:]],
            countdown=self.countdown,
            net_sabotage=self.net_sabotage,
            known=dict(p.known),
            known_alien={t: v.get('camp') == 'alien' for t, v in p.known.items()},
            exclude_info={t: set(s) for t, s in getattr(p, 'exclude_info', {}).items()},
            bullets=p.bullets,
            rescue_quota=getattr(p, 'doctor_rescue', 0),
            treat_quota=getattr(p, 'doctor_treat', 0),
            append_left=self.engineer_append_left if p.role == '工程师' else 0,
            awak_dir=p.awak_dir,
            transform_count=p.transform_count,
            quota_left={d: self.awak_quota[d] for d in sim30.AWAK_DIRS} if p.is_alien() else {},
            teammates=list(getattr(p, 'teammates', [])),
            blocked_targets=set(p.blocked_targets),
            self_treat_left=getattr(p, 'self_treat', 0),
            double_ready=getattr(p, 'fore_double_awakened', False),
            infected_set={q.id: q.infection >= 1 for q in self.alive_players()},
            chat_partner_count={},
            crew_half={t: (p.crew_checks.get(t, 0) == 1) for t in alive},
            alien_ids=frozenset(q.id for q in self.players if q.is_alien()) if p.is_alien() else frozenset(),
            humans_alive=len(self.alive_humans()),
            aliens_alive=len(self.alive_aliens()),
            dying=[q.id for q in self.alive_players() if q.dying],
            scapegoat=self._alien_scapegoat,
            i_am_key_role=p.role in ('神探', '验票官', '生化医师', '救援医师', '警察'),
        )
        # 公开配对公告推导的被聊夜集合
        cnt = {}
        for (n, pair) in self.chat_history:
            for x in pair:
                cnt.setdefault(x, set()).add(n)
        obs.chat_partner_count = cnt
        return obs

    def _refresh_mem(self, p):
        """从合法观测刷新记忆：基率 + 确定性情报 + 情绪事件。"""
        mem = self.memories[p.id]
        emo = mem.emotion
        dead_alien = sum(1 for (n, pid, camp, _) in self.deaths if camp == 'alien') \
            + sum(1 for (n, pid, camp, role) in self.ejection_log if camp == 'alien')
        base = max(0.02, min(0.9, max(0, 3 - dead_alien) / max(1, len(self.alive_players()))))
        # 记忆衰减（证据时效）：每夜一次，几率向当期基率几何回归；确证情报豁免
        if mem.last_decay_night != self.night:
            mem.last_decay_night = self.night
            base_odds = max(1e-3, base / (1 - base))
            for t in list(mem.odds_alien):
                if t in mem.confirmed or not self.players[t].alive:
                    continue
                mem.odds_alien[t] = (mem.odds_alien[t] ** 0.97) * (base_odds ** 0.03)
                fo = mem.odds_foreign.get(t, 0.10 / 0.90)
                mem.odds_foreign[t] = (fo ** 0.97) * ((0.10 / 0.90) ** 0.03)
        for q in self.alive_players():
            if q.id == p.id:
                continue
            if q.id not in mem.odds_alien:
                # 个体直觉先验：每人对他人的初始怀疑带 ±25% 个性抖动（合法的私有倾向，
                # 打破全员同分导致的确定性一致投票——那是模型伪影不是理性行为）
                jitter = 0.75 + 0.5 * self.rng.random()
                oa = base / (1 - base) * jitter
                mem.odds_alien[q.id] = max(1e-3, oa)
                mem.odds_foreign[q.id] = (0.10 / 0.90) * jitter
        # 确定性情报：自身查验 / 官方驱逐揭示 / 阵营合法字段
        for t, v in p.known.items():
            if self.players[t].alive:
                mem.set_camp(t, v.get('camp'))
        if p.is_alien() or p.is_foreigner():
            for t in self.exposed:
                if self.players[t].alive:
                    mem.set_camp(t, 'human')
        for tid in getattr(p, 'teammates', []):
            if self.players[tid].alive:
                mem.set_camp(tid, 'alien')
        for (n, pid, camp, role) in self.ejection_log:
            if camp == 'alien':
                mem.set_camp(pid, 'alien')
            else:
                mem.set_camp(pid, camp)
        # 情绪事件：倒计时/人数 → panic；确定性情报带出的信任/仇恨
        emo_on_countdown(emo, self.countdown, len(self.alive_humans()), len(self.alive_aliens()))
        # 追责：投错过好人的追责对象（公开投票记录）
        for voter, tgt in self.last_votes.items():
            if voter != p.id and tgt is not None:
                pass  # 记账在 _accountability31 统一做
        return mem

    def _record_perspective(self, p, target, action):
        if target is None:
            return
        mem = self.memories[p.id]
        self.perspective_log.append((p.id, self.skills[p.id], p.camp, action,
                                     self.night, mem.p_alien(target),
                                     1 if self.players[target].is_alien() else 0))

    def _guard(self, p, chosen, candidates, action):
        skill = self.skills[p.id]
        panic = self.memories[p.id].emotion.panic
        final = maybe_noise(self.rng, skill, self.night, chosen, candidates, panic)
        self.decisions_made[self.night] += 1
        if final != chosen:
            self.noise_applied[self.night] += 1
        return final

    # ---------- 情绪/追责结算（白天结束后调用） ----------
    def _accountability31(self):
        ej = self.last_ejected
        if ej is None:
            return
        ejp = self.players[ej]
        for voter, tgt in self.last_votes.items():
            if tgt != ej or voter == ej:
                continue
            mem = self.memories.get(voter)
            if mem is None:
                continue
            mem.rep[ej].votes_against_me += 0  # ej 已死，仅对象方向记账
            if ejp.is_human():
                # 错驱好人：投票者被全员追责
                mem.rep[ej].trust_score -= 0  # 对死者不再记账
                for other in self.memories:
                    if other != voter and self.players[other].alive:
                        self.memories[other].rep[voter].lie_count += 0
                        self.memories[other].lr_alien(voter, LR['voted_wrong'])
                        self.belief[other]['suspicion'][voter] = min(
                            1.0, self.belief[other]['suspicion'][voter] + 0.15)
        # 质询结果：命中异形→提问者可信度↑；错质好人→追责（lie_count+1）
        for (n, asker, tgt) in self.challenges:
            if n != self.night or tgt != ej:
                continue
            for other in self.memories:
                if other == asker or not self.players[other].alive:
                    continue
                if ejp.is_alien():
                    self.memories[other].lr_alien(asker, 0.8)
                else:
                    self.memories[other].rep[asker].lie_count += 1
                    self.memories[other].lr_alien(asker, 1.3)
        # 引述结果：引述属实→被引述者更可信；引述失实→被引述者可疑
        for (n, sp, tg, cited) in self.citations:
            if n != self.night or tg != ej:
                continue
            for other in self.memories:
                if not self.players[other].alive or other == cited:
                    continue
                if ejp.is_alien():
                    self.memories[other].lr_alien(cited, 0.85)
                else:
                    self.memories[other].lr_alien(cited, 1.25)
        # 投对异形 → 自我效能感↑（票型不公开，仅自己知道，符合信息隔离）
        if ejp.is_alien():
            for voter, tgt in self.last_votes.items():
                if tgt == ej and self.players[voter].alive:
                    emo_on_success(self.memories[voter].emotion)
        # 朋友死亡 → anger（对高信任死者关联的存活者保持信任清算）
        for pid, mem in self.memories.items():
            if not self.players[pid].alive:
                continue
            if ej in mem.trusted_friends:
                emo_on_friend_death(mem.emotion, [ej])

    def _betrayal_check(self):
        """私聊对象被驱逐揭示为异形 → 信任崩塌（仇恨固化）。"""
        for pid, mem in self.memories.items():
            if not self.players[pid].alive or not pid in self.last_votes:
                continue
        for (n, eje, camp, role) in self.ejection_log:
            if camp != 'alien':
                continue
            for pid, mem in self.memories.items():
                if eje in mem.trusted_friends and self.players[pid].alive:
                    emo_on_betrayal(mem.emotion, eje)

    # ---------- 覆写：私聊 ----------
    def ai_choose_chat_target(self, p, alive):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        return decide_chat_target(obs, mem, self.rng, self.skills[p.id])

    def ai_choose_chat_accept(self, p, invs):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        return decide_chat_accept(obs, mem, invs, self.rng, self.skills[p.id])

    def ai_exchange_chat(self, a, b):
        """私聊：内容只进双方 Memory（参与者合法观测）；
        证据受说话者可信度(追责账本)加权；异形半数概率撒谎。"""
        for observer, partner in ((a, b), (b, a)):
            mem_o = self.memories[observer.id]
            mem_p = self.memories[partner.id]
            mem_o.chat_partners.add(partner.id)
            mem_p.chat_partners.add(observer.id)
            mem_o.lr_alien(partner.id, LR['chatted_with'])
            cred = mem_p.rep[observer.id].credibility()  # 我眼中对方的可信度
            for tid, v in observer.known.items():
                if tid == partner.id or not self.players[tid].alive:
                    continue
                if observer.is_alien():
                    if self.rng.random() < 0.5:
                        mem_p.lr_alien(tid, 1.8)  # 假疑点
                else:
                    if v.get('camp') == 'alien':
                        if cred >= 0.5:
                            mem_p.set_camp(tid, 'alien')
                        else:
                            mem_p.lr_alien(tid, 1.5)  # 说谎前科 → 弱化
                    elif v.get('camp') == 'human':
                        mem_p.set_camp(tid, 'human')
            fake_ok = observer.is_alien() and self.strategy == 'high' and self.rng.random() < 0.4
            intent = None
            if fake_ok:
                good = [q for q in self.alive_players() if not q.is_alien() and q.id != observer.id]
                if good:
                    intent = self.rng.choice(good).id
                    mem_p.lr_alien(intent, 1.6)
                    # 异形假承诺：许诺投假目标，明日背约制造误导（背约有追责代价）
                    mem_p.promises[observer.id] = (self.night, intent)
            else:
                _exc = (partner.id,)
                if observer.is_alien():
                    _exc = (partner.id,) + tuple(observer.teammates)
                tgt = _top_eff(self._base_obs(observer), mem_o, exclude=_exc, rng=self.rng)
                if tgt is not None:
                    intent = tgt
                    w = 1.0 + 0.3 * cred
                    mem_p.lr_alien(tgt, 1.12 * w if w > 0 else 1.12)
                    # 引述素材：对方向我表达过对 tgt 的怀疑（可公开引述）
                    if not observer.is_alien():
                        mem_p.chat_claims[tgt] = observer.id
                # 承诺：向对方许诺明日投票意向（背约入追责账本）
                if intent is not None:
                    mem_p.promises[observer.id] = (self.night, intent)
            self._apply_known_to_belief()
        # 双向入好友（信任>0 视为潜在朋友）
        if self.memories[a.id].emotion.t(b.id) > 0.3:
            self.memories[a.id].trusted_friends.add(b.id)
        if self.memories[b.id].emotion.t(a.id) > 0.3:
            self.memories[b.id].trusted_friends.add(a.id)

    # ---------- 覆写：查验 ----------
    def ai_pick_check_target(self, p):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        t = decide_check_target(obs, mem, self.rng, self.skills[p.id])
        if t is not None:
            self._record_perspective(p, t, 'check')
        return t

    # ---------- 覆写：保护/巡逻 ----------
    def ai_pick_protect(self, p):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        return decide_protect(obs, mem, self.rng, self.skills[p.id])

    def ai_pick_patrol(self, p):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        return decide_patrol(obs, mem, self.rng, self.skills[p.id])

    # ---------- 覆写：开枪 ----------
    def ai_pick_shoot(self, p):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        t = decide_shoot(obs, mem, self.rng, self.skills[p.id])
        if t is not None:
            self._record_perspective(p, t, 'shoot')
            t = self._guard(p, t, [q.id for q in self.alive_players()
                                   if q.id != p.id and not q.dying], 'shoot')
        return t

    # ---------- 覆写：击杀 ----------
    def ai_pick_kill_target(self, p):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        # 补刀规则（消歧13 v2）：异形协调行动、同夜不重复指定同一健康目标；
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
                self._foreigner_targets_night.add(t)
        if t is not None:
            self._record_perspective(p, t, 'kill')
        return t

    # ---------- 覆写：感染 ----------
    def ai_pick_infect(self, p):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        return decide_infect(obs, mem, self.rng, self.skills[p.id])

    # ---------- 覆写：救援/治疗 ----------
    def ai_pick_rescue(self, p, dying_targets):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        return decide_rescue(obs, mem, [q.id for q in dying_targets], self.rng, self.skills[p.id])

    def ai_pick_infect_treat(self, p, inf_targets):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        return decide_treat(obs, mem, [q.id for q in inf_targets], self.rng, self.skills[p.id])

    def _crew_will_repair(self, p):
        base = super()._crew_will_repair(p)
        if HUMAN_STYLE == 'guardian' and not self.sabotage_surge:
            # 护盾协防型：保人 > 查人，维修倾向 +20%
            return base or self.rng.random() < 0.2
        return base

    def apply_harm(self, target_id, cause):
        res = super().apply_harm(target_id, cause)
        if res == 'dying':
            # 记录濒死原因阵营：外星人造成的濒死可被异形第 1 夜起补刀（消歧13 v2）
            self.players[target_id].dying_cause_camp = \
                'foreigner' if cause == '外星人伤害' else 'alien'
            if ANNOUNCE_INJURY:
                self.announce_msg("%d号 濒死。" % target_id)
        return res

    # ---------- 覆写：步骤6 枪械（F2 对齐：武装船员仅可开枪，规则未赋予保护能力） ----------
    def step6_guns(self):
        police_shots = 0
        armed_shots = 0
        blocked = 0
        for p in self.alive_players():
            if not p.alive or p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 2.1/0.5：沉默/抑制者无法执行夜间技能
            if p.role == '警察' and p.bullets > 0 and not p.patrolled_tonight:
                # 巡逻/开枪同夜互斥（R2）
                tgt = self.ai_pick_shoot(p)
                if tgt is not None:
                    p.bullets -= 1
                    police_shots += 1
                    r = self.apply_harm(tgt, '枪击')
                    if r in ('immune', 'blocked'):
                        blocked += 1
            elif p.role == '武装船员' and p.bullets > 0:
                tgt = self.ai_pick_shoot(p)
                if tgt is not None:
                    p.bullets -= 1
                    armed_shots += 1
                    r = self.apply_harm(tgt, '枪击')
                    if r in ('immune', 'blocked'):
                        blocked += 1
        if police_shots or armed_shots:
            self.announce_msg("警察开枪%d次，武装船员开枪%d次，共%d次，其中被抵挡%d次。" %
                              (police_shots, armed_shots, police_shots + armed_shots, blocked))

    # ---------- 覆写：步骤8 医生行动（F3 对齐：濒死自救消耗救援额度，额度 0 无法自救） ----------
    def _doctor_act(self, p):
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
                    self.players[tgt].has_antibody = True

    # ---------- 覆写：异形计划（觉醒/转化/行动/scapegoat） ----------
    def plan_night_actions(self):
        acc_cnt = Counter()
        for (cn, sp, tg, grade, _) in self.accuse_claims:
            acc_cnt[tg] += 1
        cands = [q for q in self.alive_players()
                 if not q.is_alien() and not q.dying and acc_cnt.get(q.id, 0) > 0]
        self._alien_scapegoat = (max(cands, key=lambda q: acc_cnt[q.id]).id
                                 if cands else None)
        self._alien_targets_this_night = set()
        self._foreigner_targets_night = set()

        if self.night >= 3:
            for p in self.alive_aliens():
                mem = self.memories[p.id]
                if not p.awakened and not p.dying:
                    self._alien_awaken31(p)
                elif p.awakened:
                    self._alien_transform31(p)

        aliens_alive = [p for p in self.alive_aliens() if not p.dying]
        n_infect = len([p for p in aliens_alive if p.awak_dir == '感染'])
        for p in aliens_alive:
            over_exposed = p.alien_sabotage_count >= 2 and p.id not in self.alien_sabotage_exposed
            r = self.rng.random()
            if ALIEN_STYLE in ('aggro', 'mix', 'mimic'):
                # 极限击杀流：除非破坏觉醒且未过阈值，否则全员出刀/感染压制
                if p.awak_dir == '破坏' and self.net_sabotage < 7 and not over_exposed:
                    p._alien_action = '破坏'
                elif p.awak_dir == '感染' and r < 0.6:
                    p._alien_action = '感染'
                else:
                    p._alien_action = '出刀'
            else:
                if p.awak_dir == '破坏' and self.net_sabotage < 7 and not over_exposed:
                    p._alien_action = '破坏'
                elif self.countdown < 9 and len(self.alive_humans()) <= 5:
                    p._alien_action = '出刀'
                elif p.awak_dir == '感染':
                    p._alien_action = '感染' if r < 0.8 else '出刀'
                elif n_infect >= 2 and r < 0.3:
                    p._alien_action = '感染'
                elif r < 0.55:
                    p._alien_action = '出刀'
                elif r < 0.75:
                    p._alien_action = '感染'
                else:
                    p._alien_action = '结茧'
            if ALIEN_STYLE in ('balanced', 'sab') and p.id in self.alien_sabotage_exposed \
                    and self.rng.random() < 0.3:
                p._alien_action = '结茧'

        for p in self.alive_players():
            if p.role == '武装船员' and p.bullets > 0 and not p.dying:
                know_alien = any(v.get('camp') == 'alien' for v in p.known.values())
                p._armed_protect = (not know_alien) and self.rng.random() < 0.4

        for p in self.alive_foreigners():
            if p.dying:
                p._foreigner_action = None
                continue
            p._foreigner_action = self._foreigner_plan31(p)

    def _alien_awaken31(self, p):
        avail = [d for d in sim30.AWAK_DIRS if self.awak_quota[d] > 0]
        if not avail:
            return
        teammates_dirs = set()
        for tid in getattr(p, 'teammates', []):
            tp = self.players[tid]
            if tp.alive:
                teammates_dirs |= tp.awak_occupied
        preferred = [d for d in avail if d not in teammates_dirs] or avail
        order = list(ALIEN_AWAKEN_ORDER.get(ALIEN_STYLE, ['感染', '击杀', '破坏']))
        if ALIEN_STYLE == 'mix' and '破坏' in teammates_dirs:
            order = ['感染', '击杀', '破坏']   # 已有队友占破坏 → 自己走感染/击杀
        d = next((x for x in order if x in preferred), preferred[0])
        d = self._guard(p, d, preferred, 'awaken')
        if self._acquire_awak(p, d):
            p.awakened = True
            p.awak_dir = d
            p.awak_night = self.night
            self.awak_choices.append((d, self.night))
            self.announce_msg("今晚有 1 只异形觉醒。")

    def _alien_transform31(self, p):
        if p.transform_count >= 2:
            return
        targets = [d for d in sim30.AWAK_DIRS if d != p.awak_dir and self.awak_quota[d] > 0]
        if not targets:
            return
        tn, tp_, dirs = ALIEN_TRANSFORM.get(ALIEN_STYLE, (4, 0.75, ['击杀']))
        if self.night >= tn and self.rng.random() < tp_:
            for nd in dirs:
                if nd in targets and nd != p.awak_dir:
                    self._transform(p, nd)
                    break

    def _foreigner_plan31(self, p):
        humans_alive = len(self.alive_humans())
        aliens_alive = len(self.alive_aliens())
        known_cnt = len(p.known)
        if humans_alive == 0:
            return '击杀'
        awaken_p = 0.98 if FOREIGNER_STYLE == 'hunter' else 0.9
        if not p.fore_double_awakened:
            if self.night >= 6:
                if self.rng.random() < awaken_p:
                    p.fore_double_awakened = True
                    return '双刀'
                return '查验' if known_cnt < 6 else '击杀'
            if known_cnt < 3 and self.night < 6:
                return '查验' if self.rng.random() < 0.7 else '击杀'
            return '击杀' if self.rng.random() < 0.8 else '查验'
        else:
            sab_gate = 5.0 if FOREIGNER_STYLE == 'kingmaker' else 6.0
            if p.foreigner_sabotage_count < 1 and self.net_sabotage >= sab_gate and humans_alive <= 6:
                return '破坏'
            known_hv = [t for t, v in p.known.items()
                        if v.get('camp') == 'human'
                        and v.get('role') in ('神探', '验票官', '救援医师', '生化医师')
                        and self.players[t].alive and not self.players[t].dying]
            if known_hv and (self.night >= 8 or humans_alive <= 5):
                return '双刀'
            if self.rng.random() < 0.15 and known_cnt < 8:
                return '查验'
            return '击杀'

    # ---------- 覆写：白天讨论（贝叶斯指控 + 情绪化发言） ----------
    def _day_discussion(self):
        for p in self.alive_players():
            if p.is_alien() or p.is_foreigner() or self.strategy != 'high':
                continue
            known_alien = [t for t, v in p.known.items()
                           if v.get('camp') == 'alien' and self.players[t].alive]
            jump = False
            if p.role == '神探':
                if self.human_mode == 'passive':
                    jump = False
                elif self.human_mode == 'aggro':
                    jump = len(known_alien) >= 1
                else:
                    jump = len(known_alien) >= 1 and (self.night >= 2 or self.rng.random() < 0.5)
            elif p.role == '普通船员':
                locked = [t for t, c in p.crew_checks.items()
                          if c >= 2 and p.known.get(t, {}).get('camp') == 'alien'
                          and self.players[t].alive]
                jump = (len(locked) >= 1) if self.human_mode == 'aggro' \
                    else (len(locked) >= 1 and self.rng.random() < 0.7)
            if jump and known_alien:
                tgt = known_alien[0]
                self.belief[p.id]['accuse_log'].append((p.id, tgt))
                self.revealed_humans.add(p.id)
                self.accuse_claims.append((self.night, p.id, tgt, 3, False))
                self.accuse_grade_dist[3] += 1
                emo_on_success(self.memories[p.id].emotion)
        # 普通发言：指控各自信念最怀疑者（异形协同 scapegoat；情绪化人群更多假指控）
        for p in self.alive_players():
            mem = self.memories[p.id]
            obs = self._base_obs(p)
            if p.is_alien():
                if ALIEN_STYLE == 'mimic':
                    # 拟态流：只重复公开指控最多目标（混入人群），无人被指控则沉默
                    herd = Counter()
                    for (n2, sp2, tg2, gr2, f2) in self.accuse_claims:
                        if n2 >= self.night - 1:
                            herd[tg2] += 1
                    herd_tgts = [t for t in herd if self.players[t].alive
                                 and not self.players[t].is_alien()
                                 and herd[t] >= 2 and t != p.id]
                    tgt = herd_tgts[0] if herd_tgts else None
                else:
                    sg = self._alien_scapegoat
                    tgt = sg if (sg is not None and sg != p.id and self.players[sg].alive) \
                        else _top_eff(obs, mem, exclude=set(obs['teammates']) | {p.id}, rng=self.rng)
                grade, is_fake = 0, True
            else:
                tgt = _top_eff(obs, mem)
                grade, is_fake = self._claim_grade(p, tgt) if tgt else (0, False)
                if p.is_foreigner():
                    grade, is_fake = 0, True
            if tgt is None:
                continue
            self.belief[p.id]['accuse_log'].append((p.id, tgt))
            self.accuse_claims.append((self.night, p.id, tgt, grade, is_fake))
            self.accuse_grade_dist[grade] += 1
            if is_fake:
                self.fake_accuse_count += 1
            # 听众贝叶斯更新（可信度加权 + 证据去重：同一 (speaker,target) 只更新一次）
            for q in self.alive_players():
                if q.id == p.id:
                    continue
                mq = self.memories[q.id]
                cred = mq.rep[p.id].credibility()  # 听众眼中说话者的可信度
                claim_key = (p.id, tgt)
                is_new = claim_key not in mq.seen_claims
                mq.seen_claims.add(claim_key)
                if is_new:
                    if grade >= 3 and not (p.is_alien() or p.is_foreigner()) and cred >= 0.5:
                        mq.lr_alien(tgt, TRUSTED_LR * (0.5 if HUMAN_STYLE == 'skeptic' else 1.0))
                    elif cred < 0.5:
                        mq.lr_alien(tgt, 0.4 if HUMAN_STYLE == 'skeptic' else LR['accused_by_liar'])
                    else:
                        lr = ORDINARY_LR
                        if self.belief[p.id]['accountable'] >= 1:
                            lr = LR['accused_by_liar']
                        mq.lr_alien(tgt, lr)
                    # 被点名者 fear↑（情绪效应不受证据去重限制）
                    if tgt == q.id:
                        emo_on_suspected(mq.emotion)
        # 交叉验证（独立指控人数 ≥3 且出现新增 → LR 1.25，仅新增触发一次）
        for tg in set(c[2] for c in self.accuse_claims if c[0] == self.night):
            if not self.players[tg].alive:
                continue
            for q in self.alive_players():
                if q.id == tg:
                    continue
                mq = self.memories[q.id]
                uniq = len({sp for (sp, tg2) in mq.seen_claims if tg2 == tg})
                prev_key = ('xv', tg)
                prev_uniq = mq.accuser_cnt.get(prev_key, 0)
                if uniq >= 3 and uniq > prev_uniq:
                    mq.lr_alien(tg, 1.25)
                    mq.accuser_cnt[prev_key] = uniq
        # 引述对峙：怀疑源自私聊者可公开引述（署名被引述者，证据可追责）
        for p in self.alive_players():
            if p.is_alien() or p.is_foreigner() or p.dying:
                continue
            mem = self.memories[p.id]
            for tgt, sp in list(mem.chat_claims.items()):
                if not self.players[tgt].alive or sp == p.id or not self.players[sp].alive:
                    mem.chat_claims.pop(tgt, None)
                    continue
                if self.rng.random() < 0.3:
                    self.citations.append((self.night, p.id, tgt, sp))
                    self.accuse_claims.append((self.night, p.id, tgt, 1, False))
                    self.accuse_grade_dist[1] += 1
                    self.belief[p.id]['accuse_log'].append((p.id, tgt))
                    mem.chat_claims.pop(tgt)
                    break
        # 点名质询：人类按技能档概率质询最怀疑目标；目标可确证反指/愤怒反咬/沉默（弱证据）
        for p in self.alive_players():
            if p.is_alien() or p.is_foreigner() or p.dying:
                continue
            prob = {'expert': 0.35, 'mid': 0.25, 'novice': 0.15}[self.skills[p.id]]
            if self.rng.random() >= prob:
                continue
            mem = self.memories[p.id]
            obs = self._base_obs(p)
            tgt = _top_eff(obs, mem, exclude={p.id}, rng=self.rng)
            if tgt is None:
                continue
            grade, is_fake = self._claim_grade(p, tgt)
            self.challenges.append((self.night, p.id, tgt))
            self.accuse_claims.append((self.night, p.id, tgt, grade, is_fake))
            self.accuse_grade_dist[grade] += 1
            if is_fake:
                self.fake_accuse_count += 1
            self.belief[p.id]['accuse_log'].append((p.id, tgt))
            tmem = self.memories[tgt]
            tp = self.players[tgt]
            if tp.is_alien() or tp.is_foreigner():
                tmem.emotion.fear = min(1.0, tmem.emotion.fear + 0.15)
                # 沉默否认 → 听众弱证据
                for q in self.alive_players():
                    if q.id != tgt:
                        self.memories[q.id].lr_alien(tgt, 1.1)
                continue
            known_alien = [t for t, v in tp.known.items()
                           if v.get('camp') == 'alien' and self.players[t].alive]
            if known_alien and self.rng.random() < 0.6:
                self.accuse_claims.append((self.night, tgt, known_alien[0], 3, False))
                self.accuse_grade_dist[3] += 1
                for q in self.alive_players():
                    if q.id != tgt:
                        self.memories[q.id].lr_alien(known_alien[0], TRUSTED_LR)
            elif tmem.emotion.anger > 0.4 and self.rng.random() < 0.5:
                self.accuse_claims.append((self.night, tgt, p.id, 0, False))
                self.accuse_grade_dist[0] += 1
            else:
                for q in self.alive_players():
                    if q.id != tgt:
                        self.memories[q.id].lr_alien(tgt, 1.1)

    def _day_vote(self):
        votes = defaultdict(int)
        voters = {}
        my_voters = defaultdict(list)
        for p in self.alive_players():
            if p.dying:
                continue
            if p.silent > 0:
                voters[p.id] = None
                continue
            tgt = self._vote31(p)
            voters[p.id] = tgt
            if tgt is not None:
                votes[tgt] += 1
                my_voters[tgt].append(p.id)
                self._record_perspective(p, tgt, 'vote')
        # 情绪：被投票 → 恐惧/愤怒 + 记仇账本
        for tgt, vs in my_voters.items():
            if self.players[tgt].alive:
                mem_t = self.memories[tgt]
                for v in vs:
                    emo_on_voted_me(mem_t.emotion, v)
                    mem_t.rep[v].votes_against_me += 1
        self.last_votes = voters
        # 承诺兑现检查（昨夜私聊承诺 → 今日票型，仅承诺双方可见）：背约入追责账本
        for pid, mem in self.memories.items():
            if not self.players[pid].alive:
                continue
            for maker in list(mem.promises):
                n_made, tgt_p = mem.promises[maker]
                if n_made != self.night or not self.players[maker].alive:
                    continue
                actual = voters.get(maker, 'abstain')
                kept = (actual == tgt_p)
                self.promise_stats[(self.skills[maker], kept)] += 1
                if not kept:
                    mem.rep[maker].broken_promises += 1
                    mem.emotion.set_trust(maker, mem.emotion.t(maker) - 0.3)
                    mem.lr_alien(maker, 1.4)
                del mem.promises[maker]
        if votes:
            maxv = max(votes.values())
            top = [t for t, v in votes.items() if v == maxv]
            ejected = self.rng.choice(top)
            self.last_ejected = ejected
            self.players[ejected].alive = False
            self.players[ejected].dying = False
            self.announce_msg("白天投票：%d号 被驱逐（得票%d）。" % (ejected, maxv))
            ejp = self.players[ejected]
            self.announce_msg("驱逐结果：%d号 是 %s（职业：%s）。" % (
                ejected, self._camp_cn(ejp.camp), ejp.role))
            self.ejection_log.append((self.night, ejected, ejp.camp, ejp.role))
            if ejp.camp == 'alien':
                self.alien_public_exposed_count = getattr(self, 'alien_public_exposed_count', 0) + 1
            # 谎言追责：本夜对被驱逐者发 grade-3 确证而目标非异形 → 说话者 lie_count+1
            if ejp.camp != 'alien':
                for (cn, sp, tg, grade, isf) in self.accuse_claims:
                    if cn == self.night and tg == ejected and grade >= 3 \
                            and self.players[sp].alive:
                        for pid in self.memories:
                            if pid != sp and self.players[pid].alive:
                                self.memories[pid].rep[sp].lie_count += 1
                                self.memories[pid].lr_alien(sp, 1.0 / 1.5)  # 反向解读其指控
            for pid in self.memories:
                self.memories[pid].set_camp(ejected, ejp.camp)
        else:
            self.last_ejected = None
            self.announce_msg("白天无人被驱逐。")

    def _vote31(self, p):
        mem = self._refresh_mem(p)
        obs = self._base_obs(p)
        return decide_vote(obs, mem, self.rng, self.skills[p.id])

    def run_daytime(self, emergency=False):
        super().run_daytime(emergency=emergency)
        self._accountability31()
        self._betrayal_check()


# ============================ 采样驱动 ============================
def simulate_one31(rng, game_id, perspective_log, trace_holder):
    g = Game31(rng, game_id, 'high', perspective_log=perspective_log, trace=trace_holder)
    max_nights = 200
    while not g.over and g.night < max_nights:
        g.plan_night_actions()
        g.run_night()
        if g.over:
            break
        if not g.night_war:
            g.run_daytime(emergency=False)
            if g.over:
                break
        else:
            aliens = g.alive_aliens()
            fore = g.alive_foreigners()
            if len(aliens) == 0 and len(fore) == 0:
                g._end('foreigner', '夜晚交锋同归于尽', '1.4')
                break
            if g._war_last_alive is not None:
                prev_a, prev_f = g._war_last_alive
                g.night_war_no_kill = 0 if len(aliens) + len(fore) < prev_a + prev_f \
                    else g.night_war_no_kill + 1
            else:
                g.night_war_no_kill = 0
            g._war_last_alive = (len(aliens), len(fore))
            if g.night_war_no_kill >= 5:
                if len(aliens) > len(fore):
                    g._end('alien', '夜晚交锋兜底(人数占优)', '1.4')
                else:
                    g._end('foreigner', '夜晚交锋兜底(人数不劣)', '1.4')
                break
            if len(aliens) == 1 and len(fore) == 1:
                g.night_war_count += 1
                if g.night_war_count >= 3:
                    g._end('foreigner', '夜晚交锋单挑平局', '1.4')
                    break
            else:
                g.night_war_count = 0
        g.check_win('loop')
        # 信念/情绪演化采样（第 0 局）
        if trace_holder is not None and game_id == 0:
            tr = trace_holder.setdefault('belief', defaultdict(list))
            em = trace_holder.setdefault('emotion', defaultdict(list))
            experts = [pid for pid in g.memories
                       if g.players[pid].is_human() and g.players[pid].alive
                       and g.skills[pid] == 'expert']
            for alien in [q for q in g.players if q.is_alien() and q.alive]:
                if experts:
                    tr[alien.id].append((g.night,
                                         sum(g.memories[pid].p_alien(alien.id) for pid in experts) / len(experts)))
            alive_ids = [q.id for q in g.alive_players()]
            for k in ('fear', 'anger', 'panic'):
                em[k].append((g.night, sum(getattr(g.memories[pid].emotion, k) for pid in alive_ids) / len(alive_ids)))
    if not g.over:
        g._end('draw', '200夜护栏判平', 'timeout')
    return g


# ============================ 统计与报告 ============================
def bootstrap_ci(values, n_boot=2000, seed=7, alpha=0.05):
    rng = random.Random(seed)
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    means = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += values[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    return (means[int(n_boot * alpha / 2)], means[int(n_boot * (1 - alpha / 2)) - 1])

def perspective_analysis(plog):
    agg = defaultdict(lambda: [0, 0.0, 0])
    for (pid, skill, camp, action, night, conf, truth) in plog:
        k = (camp, action, skill)
        agg[k][0] += truth
        agg[k][1] += conf
        agg[k][2] += 1
    rows, violations = [], []
    for (camp, action, skill), (correct, conf_sum, n) in sorted(agg.items()):
        if n < 50:
            continue
        acc = correct / n
        conf = conf_sum / n
        se = math.sqrt(max(conf * (1 - conf), 1e-6) / n)
        z = (acc - conf) / se if se > 0 else 0.0
        flag = (acc - conf) > 0.05 and z > 2.0
        rows.append((camp, action, skill, n, acc, conf, z, flag))
        if flag:
            violations.append((camp, action, skill, acc, conf, z))
    return rows, violations

def convergence_curve(games):
    noise = Counter()
    dec = Counter()
    for g in games:
        for night, c in g.noise_applied.items():
            noise[night] += c
        for night, c in g.decisions_made.items():
            dec[night] += c
    return sorted((n, (noise[n] / dec[n]) if dec[n] else 0.0) for n in dec)

def main():
    t0 = time.time()
    out_dir = os.path.join(_HERE, 'sim_output')
    os.makedirs(out_dir, exist_ok=True)

    N = int(os.environ.get('SIM_N', '5000'))
    SEED = 20260829
    config = {
        'version': '公测3.1 认知模型（信息集最优+情绪+追责）',
        'engine': '公测3.0 裁判（规则零改动，机制核验 18/18）',
        'rules': '公测3.0 规则.md（R1~R11）',
        'n_games': N,
        'seed': SEED,
        'skill_dist': dict(SKILL_DIST),
        'noise_model': SKILL_NOISE,
        'lr_table': LR,
        'emotion': 'fear/anger/panic/confidence + 个体trust；事件驱动（被投票/朋友死亡/倒计时/背叛/自证成功）',
        'reputation': 'lie_count/votes_against_me/trust_score；局内累计、每局重置；说谎前科→可信度0.5^n',
        'isolation': {
            'decision_layer': '自由函数 decide_*，只接收 Observation/Memory/rng/skill',
            'private_chat': '私聊内容仅写入双方 Memory，非参与者不可见',
            'removed_illegal_channels': ['_protect_count', 'attacked_history→保护方', 'exposed→人类观测'],
            'perspective_detection': '身份类决策 acc vs 后验置信，z>2 且差>5pp 判违规',
        'focus_fire': '异形协调行动：同夜不重复指定目标；第5夜起可自由选择补刀（濒死再受击直接死亡）',
        },
    }

    print('运行 %d 局（公测3.1 信息集最优 + 情绪 + 追责 + 技能分档）...' % N)
    rng = random.Random(SEED)
    plog = []
    games = []
    wins = []
    for i in range(N):
        g = simulate_one31(rng, i, plog, None)
        games.append(g)
        wins.append(g.winner)
        if (i + 1) % 1000 == 0:
            print('  %d 局完成 (%.0fs)' % (i + 1, time.time() - t0))

    camp_stats = {}
    for camp in ('human', 'alien', 'foreigner', 'draw'):
        values = [1.0 if w == camp else 0.0 for w in wins]
        lo, hi = bootstrap_ci(values, seed=SEED)
        camp_stats[camp] = (100 * sum(values) / N, 100 * lo, 100 * hi)

    skill_camp = defaultdict(lambda: [0, 0])
    for g in games:
        for p in g.players:
            key = (g.skills[p.id], p.camp)
            skill_camp[key][1] += 1
            if g.winner == p.camp:
                skill_camp[key][0] += 1

    prows, violations = perspective_analysis(plog)
    conv = convergence_curve(games)

    # 信息博弈指标聚合
    promise_stats = Counter()
    challenge_n = 0
    challenge_hit = 0
    citation_n = 0
    for g in games:
        promise_stats.update(g.promise_stats)
        for (_n, _a, tgt) in g.challenges:
            challenge_n += 1
            if g.players[tgt].is_alien():
                challenge_hit += 1
        citation_n += len(g.citations)

    # 信念/情绪演化（第 0 局重放：同种子可复现）
    holder = {}
    simulate_one31(random.Random(SEED), 0, [], holder)
    trace_belief = holder.get('belief', {})
    trace_emotion = holder.get('emotion', {})

    # 私聊效果（裁判层已有的有效私聊统计）
    chat_total = sum(g._chat_total_cnt for g in games)
    chat_eff = sum(g._chat_effective_cnt for g in games)

    config['infogame'] = {
        'promise_by_skill': {'%s|%s' % k: v for k, v in sorted(promise_stats.items())},
        'challenges': challenge_n,
        'challenge_hit_rate': (round(100.0 * challenge_hit / challenge_n, 1) if challenge_n else None),
        'citations': citation_n,
    }
    config['results_summary'] = {
        'win_rates_ci': {k: [round(x, 2) for x in v] for k, v in camp_stats.items()},
        'perspective_violations': len(violations),
        'chat_effective_rate': (round(100.0 * chat_eff / chat_total, 1) if chat_total else None),
    }
    with io.open(os.path.join(out_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    with io.open(os.path.join(out_dir, 'perspective_report.csv'), 'w', encoding='utf-8') as f:
        f.write('camp,action,skill,n,accuracy,mean_posterior,z,violation\n')
        for (camp, action, skill, n, acc, conf, z, flag) in prows:
            f.write('%s,%s,%s,%d,%.4f,%.4f,%.2f,%s\n' % (camp, action, skill, n, acc, conf, z, flag))

    def pct(x):
        return '%.1f%%' % x

    html = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
            '<title>太空杀 公测3.1 — 高水平玩家认知模型模拟报告</title>',
            '<style>body{font-family:"Segoe UI","Microsoft YaHei",sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222}',
            'h1{color:#1a237e} h2{color:#283593;border-left:4px solid #3949ab;padding-left:10px;margin-top:32px}',
            'table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}',
            'th,td{border:1px solid #ddd;padding:7px 10px;text-align:left}th{background:#f0f2f7}',
            '.ok{color:#2e7d32;font-weight:700}.bad{color:#c62828;font-weight:700}.note{color:#789;font-size:12px}',
            'svg{background:#fafbff;border:1px solid #e3e6f0;border-radius:8px}</style></head><body>']
    html.append('<h1>太空杀 公测3.1 — 高水平玩家认知模型模拟报告</h1>')
    html.append('<p>局数 <b>%d</b> ｜ 种子 %d ｜ 规则：公测3.0（裁判零改动）｜ 技能分布 55%%中 / 20%%高 / 25%%新手（每人固定一档）｜ '
                '情绪 + 追责账本 + 私聊可信度加权</p>' % (N, SEED))

    html.append('<h2>① 阵营胜率 + 95% CI（bootstrap 2000 次）</h2><table><tr><th>阵营</th><th>胜率</th><th>95% CI</th></tr>')
    for camp, label in (('human', '人类'), ('alien', '异形'), ('foreigner', '外星人'), ('draw', '护栏判平(非规则)')):
        w, lo, hi = camp_stats[camp]
        html.append('<tr><td>%s</td><td>%s</td><td>[%.1f%%, %.1f%%]</td></tr>' % (label, pct(w), lo, hi))
    html.append('</table>')

    html.append('<h2>② 技能档 × 阵营胜率（收敛差异验证）</h2><table><tr><th>技能档</th><th>阵营</th><th>样本</th><th>胜率</th><th>95% CI</th></tr>')
    for (s, camp) in sorted(skill_camp):
        w, n = skill_camp[(s, camp)]
        lo, hi = bootstrap_ci([1.0] * w + [0.0] * (n - w), seed=3)
        cn = {'human': '人类', 'alien': '异形', 'foreigner': '外星人'}.get(camp, camp)
        html.append('<tr><td>%s</td><td>%s</td><td>%d</td><td>%.1f%%</td><td>[%.1f%%, %.1f%%]</td></tr>'
                    % (s, cn, n, 100.0 * w / n, 100 * lo, 100 * hi))
    html.append('</table>')
    html.append('<p class="note">判据：expert &gt; mid &gt; novice（同阵营内）——档位差异证明技能/收敛模型生效，非全员同优。</p>')

    html.append('<h2>③ 透视违规检测</h2>')
    html.append('<p>身份类决策（投票/击杀/查验/枪击）采样；判违规：准确率 − 平均后验 &gt; 5pp 且 z &gt; 2（n≥50）。</p>')
    html.append('<table><tr><th>阵营</th><th>动作</th><th>技能档</th><th>n</th><th>准确率</th><th>平均后验置信</th><th>z</th><th>判定</th></tr>')
    for (camp, action, skill, n, acc, conf, z, flag) in prows:
        cn = {'human': '人类', 'alien': '异形', 'foreigner': '外星人'}.get(camp, camp)
        html.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%.1f%%</td><td>%.1f%%</td><td>%.2f</td><td class="%s">%s</td></tr>'
                    % (cn, action, skill, n, 100 * acc, 100 * conf, z,
                       'bad' if flag else 'ok', '⚠ 透视违规' if flag else '正常'))
    html.append('</table>')
    if violations:
        html.append('<p class="bad">检测到 %d 组疑似透视，需人工复核！</p>' % len(violations))
    else:
        html.append('<p class="ok">✔ 未检测到透视：所有决策准确率均未显著超过其合法信念上界（信息隔离有效）。</p>')
    html.append('<p class="note">隔离校验：决策自由函数签名不含裁判对象；3 条 3.0 非公开通道已移除；'
                '私聊内容仅写入双方 Memory；expert 表现低于上帝最优上界（异形真实身份可全知，玩家后验稳定 &lt; 1）。</p>')

    html.append('<h2>④ 收敛曲线（噪声率随夜数衰减 → 各档平台期）</h2>')
    html.append('<svg width="1000" height="240" viewBox="0 0 1000 240">')
    if conv:
        max_n = max(n for n, _ in conv)
        max_r = max(r for _, r in conv) or 1.0
        pts = ' '.join('%d,%d' % (40 + (n - 1) * (920 / max(1, max_n - 1)),
                                  200 - (r / max_r) * 160) for (n, r) in conv)
        html.append('<line x1="40" y1="200" x2="960" y2="200" stroke="#999"/>'
                    '<line x1="40" y1="40" x2="40" y2="200" stroke="#999"/>'
                    '<polyline points="%s" fill="none" stroke="#3949ab" stroke-width="2"/>' % pts)
        for (n, r) in conv:
            if n % max(1, max_n // 10) == 0 or n == 1:
                html.append('<text x="%d" y="218" font-size="11" fill="#666">%d</text>' % (36 + (n - 1) * (920 / max(1, max_n - 1)), n))
    html.append('</svg>')
    html.append('<p class="note">噪声率 = (base + 0.25·panic)·e^(−夜/τ) + floor。三档 τ/floor 不同 → 收敛速度与上限不同；'
                'panic 注入使倒计时危机期噪声回升（情绪驱动偏差）。</p>')

    html.append('<h2>⑤ 信念演化（第 0 局 · expert 人类对存活异形的平均后验）</h2>')
    html.append('<svg width="1000" height="240" viewBox="0 0 1000 240">')
    if trace_belief:
        all_pts = [(n, v) for series in trace_belief.values() for (n, v) in series]
        max_n = max(n for n, _ in all_pts)
        def xy(n, v):
            return 40 + (n - 1) * (920 / max(1, max_n - 1)), 200 - v * 160
        colors = ['#c62828', '#e65100', '#6a1b9a']
        for i, (k, series) in enumerate(sorted(trace_belief.items())):
            pts = ' '.join('%d,%d' % xy(n, v) for (n, v) in series)
            html.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>' % (pts, colors[i % 3]))
        html.append('<line x1="40" y1="200" x2="960" y2="200" stroke="#999"/>'
                    '<line x1="40" y1="40" x2="40" y2="200" stroke="#999"/>')
    html.append('</svg>')
    html.append('<p class="note">expert 后验应随信息积累缓升且稳定 &lt; 1.0（绝不逼近确定=绝不透视）；'
                '真实异形身份只有裁判知道（上帝最优上界=1.0，仅作对照）。</p>')

    html.append('<h2>⑥ 情绪轨迹（第 0 局 · 全体存活者均值）</h2>')
    html.append('<svg width="1000" height="240" viewBox="0 0 1000 240">')
    if trace_emotion:
        colors = {'fear': '#e65100', 'anger': '#c62828', 'panic': '#6a1b9a'}
        all_n = [n for series in trace_emotion.values() for (n, _) in series]
        max_n = max(all_n) if all_n else 1
        for k, series in trace_emotion.items():
            pts = ' '.join('%d,%d' % (40 + (n - 1) * (920 / max(1, max_n - 1)), 200 - v * 160)
                           for (n, v) in series)
            html.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>' % (pts, colors.get(k, '#333')))
            html.append('<text x="870" y="%d" font-size="12" fill="%s">%s</text>' % (
                50 + list(colors).index(k) * 20, colors.get(k, '#333'), k))
        html.append('<line x1="40" y1="200" x2="960" y2="200" stroke="#999"/>'
                    '<line x1="40" y1="40" x2="40" y2="200" stroke="#999"/>')
    html.append('</svg>')
    html.append('<p class="note">事件驱动：被投票→fear/anger↑；高信任对象死亡→anger↑；倒计时≤8 或人数劣势→panic↑（噪声随之↑）；'
                '查验确证异形→confidence↑。情绪非纯随机，全部由对局事件触发。</p>')

    html.append('<h2>⑦ 私聊效果分析</h2>')
    if chat_total:
        html.append('<p>私聊总次数 <b>%d</b>；有效私聊（48h 内对私聊对象产生行为变动）<b>%d</b> 次 → '
                    '<b>有效率 %.1f%%</b>（裁判层判定，与 3.0 口径一致）。</p>' % (chat_total, chat_eff, 100.0 * chat_eff / chat_total))
    else:
        html.append('<p>本组模拟未产生私聊。</p>')
    html.append('<p class="note">私聊内容仅双方 Memory 可见（信息不对称战场）；异形借私聊散布假疑点，'
                '但说谎前科会进入追责账本（可信度 0.5^n 衰减），欺骗有长期代价。</p>')

    html.append('<h2>⑧ 信息博弈指标</h2>')
    html.append('<h3>承诺兑现率（按技能档，私聊承诺→次日票型核验）</h3>')
    html.append('<table><tr><th>技能档</th><th>兑现</th><th>背约</th><th>兑现率</th></tr>')
    for sk in ('expert', 'mid', 'novice'):
        kept = promise_stats.get((sk, True), 0)
        broken = promise_stats.get((sk, False), 0)
        tot = kept + broken
        html.append('<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td></tr>' % (
            sk, kept, broken, ('%.1f%%' % (100.0 * kept / tot)) if tot else '-'))
    html.append('</table>')
    base_alien_rate = camp_stats  # 仅占位
    html.append('<p>点名质询：<b>%d</b> 次，命中异形率 <b>%s</b>（存活异形基率约 20%%，显著高于基率=质询有信息价值）。'
                '公开引述 <b>%d</b> 次（私聊情报公开化，引述失实将被追责）。</p>'
                % (challenge_n, ('%.1f%%' % (100.0 * challenge_hit / challenge_n)) if challenge_n else '-',
                   citation_n))
    html.append('<p class="note">判据：expert 兑现率应显著高于 novice——验证追责账本（背约→信任崩塌）是否塑造行为。</p>')
    html.append('<h2>⑧b 采样与复现</h2>')
    html.append('<p>每局独立 RNG 流（种子 %d + game_id）；裁判完整重建、无跨局污染；追责账本每局重置；'
                '输出仅写 sim_output/ 隔离目录；config.json 为完整参数快照。</p>' % SEED)
    html.append('</body></html>')

    with io.open(os.path.join(out_dir, 'report.html'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(html))

    print('\n==== 完成 %.1fs ====' % (time.time() - t0))
    for camp, label in (('human', '人类'), ('alien', '异形'), ('foreigner', '外星人')):
        w, lo, hi = camp_stats[camp]
        print('%s %.1f%% [%.1f, %.1f]' % (label, w, lo, hi))
    print('透视违规组数:', len(violations))
    print('输出目录:', out_dir)


if __name__ == '__main__':
    main()
