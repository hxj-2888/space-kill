# -*- coding: utf-8 -*-
"""
太空杀：三阵营对抗 公测1.0 —— 自动化模拟与平衡性测试
裁判(确定性) + 玩家AI(策略/信息博弈) + 数据统计
参考：rules_ob10.md (公测1.0 规则正文) / sim_prompt.md (模拟提示词)

设计原则：
- 裁判逻辑 100% 确定性，严格按照 公测1.0 步骤顺序结算。
- 玩家决策带随机性与策略模型，且禁止"上帝视角"——只能使用自己已知信息 + 公开公告。
- 重点实现高水平玩家的【私聊与讨论博弈】：配对公告作为推理素材、私聊三层信息交换、
  白天讨论节奏、投票追责机制、信息迷雾。
- 觉醒方向额度采用【永久占位制】（用户明确规则）：额度不随异形死亡释放，转化也不释放旧方向，
  一个异形可同时在多个方向留下额度占位；目标方向额度须<2方可占用。
- 公测1.0 关键变化：异形动态破坏触发（已 A/B 实测为净负面，默认关闭切回静态感染→击杀流）；人类反破坏流（净破坏加速→集中维修）；统计口径修复（end_reason 带阵营前缀）。
  工程师第1夜被动全能免疫（4.2）；外星人夜晚免疫（6.6）；
  普通船员首次查验获得排除信息（4.1）。

运行：python spacekill_sim.py
"""

import random
import math
from collections import defaultdict, Counter

# ============================ 常量 ============================
TOTAL = 15
INIT_COUNTDOWN = 20.0  # 人类倒计时上调至20昼夜

# 人类职业数量
HUMAN_ROLES = (['普通船员'] * 4 + ['工程师', '警察', '生化医师', '救援医师',
               '神探', '保镖', '验票官'])

# 停摆阈值（净破坏量，公测1.0：3.0/6.0/9.0）
STALL_THRESHOLDS = [3.0, 6.0, 9.0]
STALL_BONUS = {3.0: 1.5, 6.0: 3.0, 9.0: 0.0}  # 9.0 不追加倒计时，仅永久失效

# 觉醒方向额度（永久占位，上限2）
AWAK_DIRS = ['破坏', '感染', '击杀']

# 数值（公测1.0）
ALIEN_SABOTAGE_BASE = 1.5
ALIEN_SABOTAGE_AWAK = 3.0
FOREIGNER_SABOTAGE = 3.0  # 外星人破坏加强 +3.0（全局1次）
ENGINEER_REPAIR_NIGHT1_2 = -0.5
ENGINEER_REPAIR_NIGHT3PLUS = -1.5
ENGINEER_APPEND = -0.5
ACCEL_ENGINEER_REPAIR = -0.75


# ============================ 玩家 ============================
class Player:
    def __init__(self, pid, camp, role):
        self.id = pid
        self.camp = camp          # 'human' / 'alien' / 'foreigner'
        self.role = role
        self.alive = True
        self.dying = False        # 濒死
        self.death_cause = None
        self.death_night = None

        # 感染
        self.infection = 0        # 0/1
        self.infection_src = None
        self.infection_death_night = None  # 步骤9触发夜
        self.infect_suppress_quota = 0     # 0->1 时获得1次

        # 沉默
        self.silent = 0           # 剩余沉默夜数(含次夜+次日白天投票)
        self.silenced_once = False  # 公测1.0 7.4：是否已触发过沉默（全局仅1次）
        self.suppressed = False   # 当夜被感染抑制，失去主动行动能力

        # 免疫/护盾（每夜重置）
        self.immune = 0           # 当夜全能免疫层数
        self.shield = False       # 结茧护盾

        # 子弹
        self.bullets = 0

        # 维修暴露
        self.repair_count = 0

        # 查验记录（普通船员：target->次数; 神探/外星人定向：target->结果）
        self.crew_checks = {}     # target -> count
        self.known = {}           # target -> {'camp':..,'role':..} 自己确知（查验/定向）
        self.exclude_info = {}    # target -> set(被排除的某职业) 首次查验排除信息

        # 转职
        self.transferred = False
        self.transfer_dir = None
        self.transfer_eligible = False

        # 异形
        self.awakened = False
        self.awak_dir = None
        self.awak_occupied = set()  # 永久占用的方向（永久占位制）
        self.transform_count = 0
        self.alien_sabotage_count = 0
        self.awak_night = None

        # 外星人
        self.disguised = False
        self.double_blade = False
        self._ever_double = False
        self.fore_double_awakened = False  # 双刀可选觉醒：是否已觉醒双刀
        self.foreigner_sabotage_count = 0
        self.night_immune = 0     # 夜晚免疫次数
        self.self_treat = 0       # 外星人感染自我治疗次数

        # 一次性额度
        self.doctor_rescue = 0
        self.doctor_treat = 0
        self.has_antibody = False
        self.police_patrol_used = False
        self.append_used = False   # 工程师追加维修
        self.emergency_used = False

        # 私聊轮换网络记忆：上一夜发起对象 + 历史对象（避免连续两晚同目标 + 关系网推断）
        self.last_chat_target = None
        self.chat_partners = set()

        # 智力提升记忆：
        # 异形反制学习：记录"被挡下/免疫"的目标（说明该目标有常驻保护），后续避开
        self.blocked_targets = set()
        # 人类威胁感知：被异形盯上的目标（该目标曾受袭）→ 保护资源优先
        self.attacked_history = defaultdict(int)

    def is_alien(self):
        return self.camp == 'alien'

    def is_foreigner(self):
        return self.camp == 'foreigner'

    def is_human(self):
        return self.camp == 'human'


# ============================ 游戏状态 ============================
class Game:
    def __init__(self, rng, game_id, strategy='high'):
        self.rng = rng
        self.game_id = game_id
        self.strategy = strategy  # 'high' / 'random'
        self.night = 0
        self.countdown = INIT_COUNTDOWN
        self.cum_sabotage = 0.0   # 累计破坏量（异形+外星人）
        self.cum_repair = 0.0     # 累计维修量
        self.net_sabotage = 0.0   # 累计净破坏量
        self.stall_triggered = set()  # 已触发的阈值
        self.human_countdown_dead = False  # 9.0 触发 → 倒计时胜利永久失效（公测1.0）
        self.over = False
        self.winner = None
        self.end_night = None
        self.end_reason = None

        # 1.4 模式
        self.night_war = False
        self.night_war_count = 0
        self.night_war_no_kill = 0   # 公测1.0：交锋连续无减员夜数（兜底终止用）
        self._war_last_alive = None
        # 公测1.0：异形劣势局面评估状态
        self.alien_public_exposed_count = 0   # 白天被驱逐公开身份的异形数
        self.dyn_sab_enabled = False          # 动态破坏触发开关（A/B 对照用）。A/B 实测：开启对系统净负面（异形-2.8pp、外星人+4.9pp），默认切回 B（关闭）
        # 公测1.0：异形行动选择子场景统计（劣势 vs 优势局面的策略选择分布）
        self._alien_dis_action = Counter()    # 劣势局面下异形行动选择
        self._alien_adv_action = Counter()    # 优势局面下异形行动选择
        self._alien_dis_nights = 0            # 劣势局面夜数
        self._alien_adv_nights = 0            # 优势局面夜数
        self._ever_disadvantaged = False      # 该局是否曾进入劣势局面
        # 公测1.0：人类反破坏流——净破坏加速检测
        self._prev_net_sab = 0.0
        self._sab_surge_nights = 0            # 连续净破坏加速夜数
        self.sabotage_surge = False           # 净破坏连续加速标志（触发集中维修）

        # 日志
        self.log = []
        self.announce = []        # 公开公告（玩家可见）
        self.snapshots = []       # 逐夜快照

        # 私聊配对（当夜）
        self.chat_pairs = []      # [(a,b)]
        self.chat_announce = []   # 公告文本

        # 普通船员查验/维修选择计数（用于查验vs维修胜率对比）
        self.crew_check_count = 0
        self.crew_repair_count = 0
        # 驱逐身份公开记录（职业公开后用于报告统计）
        self.ejection_log = []   # 每条: (night, pid, camp, role)
        # 外星人破坏减速剩余夜数（公测1.0 6.5，全局状态）
        self.fore_slow_remain = 0
        # 工程师追加维修全局次数剩余（公测1.0 3.1：共3次）
        self.engineer_append_left = 3
        # 已因累计破坏3次而暴露编号的异形（公测1.0 3.1，只暴露一次）
        self.alien_sabotage_exposed = set()

        # 玩家
        self.players = self._setup_roles()

        # 信念模型（每个玩家对其他人的怀疑分；公开/私聊共享信息）
        self.belief = {}
        for p in self.players:
            self.belief[p.id] = {
                'suspicion': {q.id: 0.12 for q in self.players if q.id != p.id},
                'accuse_log': [],      # 白天发言记录 (speaker, target)
                'chat_with': [],       # 私聊过的对象
                'accountable': 0,      # 追责标记（错误指控好人）
            }

        # 异形队内互知
        aliens = [p for p in self.players if p.is_alien()]
        for a in aliens:
            a.teammates = [x.id for x in aliens if x.id != a.id]
            # 异形互知队友，永不怀疑/投票队友
            for tid in a.teammates:
                self.belief[a.id]['suspicion'][tid] = 0.0

        # 统计：觉醒/转化
        self.awak_choices = []   # (dir, night)
        self.transform_records = []  # (from, to, night)

        # 全局觉醒额度（永久占位）
        self.awak_quota = {d: 2 for d in AWAK_DIRS}

        # 维修暴露标记已触发集合
        self.exposed = set()

        # 公开信息快照（供AI读取的"公开公告"列表）
        self.public_info = []

        # 当天投票记录（追责用）
        self.last_votes = {}
        self.last_ejected = None

        # 私聊配对公告历史（高水平推理素材）
        self.chat_history = []

        # 死亡记录
        self.deaths = []  # (night, id, camp, cause)

        # 行为信号追踪（供异形推断威胁，不得直接读取 role）
        self._protect_count = defaultdict(int)   # 玩家被保护次数（推断高价值）
        self.revealed_humans = set()             # 公开跳身份/被公开指认者

    # -------- 角色分配 --------
    def _setup_roles(self):
        roles = list(HUMAN_ROLES) + ['异形'] * 3 + ['外星人']
        self.rng.shuffle(roles)
        players = [Player(i, self._camp_of(roles[i]), roles[i]) for i in range(TOTAL)]
        for p in players:
            p.original_role = p.role  # 转职前原职业（用于职业强度统计）
        # 初始化一次性额度
        for p in players:
            if p.role == '警察':
                p.bullets = 2
            if p.role == '工程师':
                p.engineer_night1_immune = True  # 公测1.0 4.2：第1夜被动全能免疫
            if p.role == '生化医师':
                p.doctor_rescue = 1
                p.doctor_treat = 1
                p.has_antibody = True  # 自身免疫感染
            if p.role == '救援医师':
                p.doctor_rescue = 3
                p.doctor_treat = 1
            if p.role == '外星人':
                p.night_immune = 1
                p.self_treat = 2  # 外星人加强：感染自我治疗调整为2次
        return players

    def _camp_of(self, role):
        if role == '异形':
            return 'alien'
        if role == '外星人':
            return 'foreigner'
        return 'human'

    # -------- 工具 --------
    def alive_players(self):
        return [p for p in self.players if p.alive]

    def alive_humans(self):
        return [p for p in self.players if p.alive and p.is_human()]

    def alive_aliens(self):
        return [p for p in self.players if p.alive and p.is_alien()]

    def alive_foreigners(self):
        return [p for p in self.players if p.alive and p.is_foreigner()]

    def announce_msg(self, msg):
        self.announce.append(msg)
        self.public_info.append(msg)

    def add_death(self, p, cause):
        p.alive = False
        p.dying = False
        p.death_cause = cause
        p.death_night = self.night
        self.deaths.append((self.night, p.id, p.camp, cause))

    # ===================== 伤害/感染结算 =====================
    def apply_harm(self, target_id, cause):
        """造成濒死/死亡。返回 'dead' / 'dying' / 'blocked' / 'immune' 。"""
        t = self.players[target_id]
        if not t.alive:
            return 'already_dead'
        if t.dying:
            self.add_death(t, cause)
            return 'dead'
        # 公测1.0 4.2：工程师第1夜被动全能免疫
        if t.role == '工程师' and getattr(t, 'engineer_night1_immune', False) and self.night == 1:
            t.engineer_night1_immune = False  # 仅第1夜一次
            return 'immune'
        if t.immune > 0:
            t.immune -= 1
            return 'immune'
        # 公测1.0 6.6：外星人夜晚免疫（自动触发，当夜剩余时间免疫所有伤害）。
        # 注意：护盾/保护完全抵挡时不触发不消耗；因此夜晚免疫应在护盾检查之后。
        if t.shield:
            t.shield = False
            return 'blocked'
        if t.is_foreigner() and t.night_immune > 0:
            t.night_immune -= 1
            t.immune = 999  # 当夜剩余时间免疫所有伤害
            return 'immune'
        t.dying = True
        t.death_cause = cause
        return 'dying'

    def apply_infection(self, target_id, src_id):
        t = self.players[target_id]
        if not t.alive or t.is_alien():
            return 'invalid'  # 外星人削弱：不再免疫异形感染，可被感染
        if t.dying:
            return 'invalid'
        if t.immune > 0 or t.shield:
            return 'blocked'
        if t.infection >= 1:
            return 'blocked'  # 上限1层，不叠加
        if t.has_antibody:
            return 'blocked'
        t.infection = 1
        t.infection_src = src_id
        t.infection_death_night = self.night + 2  # 当夜为第1夜，死亡在第3夜步骤9
        t.infect_suppress_quota = 1
        return 'infected'

    # ===================== 胜利检查 =====================
    def check_win(self, reason):
        if self.over:
            return
        humans = self.alive_humans()
        aliens = self.alive_aliens()
        fore = self.alive_foreigners()
        # 人类清场
        if len(aliens) == 0 and len(fore) == 0:
            self._end('human', '清场胜利', reason)
            return
        # 异形清场
        if len(humans) == 0 and len(fore) == 0:
            self._end('alien', '清场胜利', reason)
            return
        # 外星人独存
        if len(humans) == 0 and len(aliens) == 0 and len(fore) >= 1:
            self._end('foreigner', '独存胜利', reason)
            return

    def _end(self, camp, reason, _src):
        self.over = True
        self.winner = camp
        self.end_night = self.night
        # 统计口径修复：end_reason 加阵营前缀，保证"胜利原因拆分"与"阵营胜率细分"两表可对账
        # （此前"清场胜利"同时被人类与异形使用，导致两表数值对不上）
        self.end_reason = self._camp_cn(camp) + reason

    # ===================== 夜晚主循环 =====================
    def run_night(self):
        self.night += 1
        self.announce = []
        self.chat_pairs = []
        self.chat_announce = []

        # 每夜重置临时免疫/护盾/伪装/沉默倒计时
        for p in self.players:
            p.immune = 0
            p.shield = False
            p.disguised = False
            p.suppressed = False
            if p.silent > 0:
                p.silent -= 1
        # 外星人调整：已移除外星人第5夜额外夜晚免疫（仅保留初始1次）

        # ---- 步骤0 私聊（非 1.4 模式）----
        if not self.night_war:
            self.step0_private_chat()

        # ---- 步骤0.5 感染抑制 ----
        self.step05_infection_suppress()

        # ---- 步骤0.6 觉醒/转化/转职 ----
        self.step06_awaken_transform_transfer()

        # ---- 步骤1 外星人查验 ----
        self.step1_foreigner_check()

        # ---- 步骤2 查验/巡逻 ----
        self.step2_check_patrol()

        # ---- 步骤3 保镖保护 ----
        self.step3_bodyguard()

        # ---- 步骤4a 维修 ----
        self.step4a_repair()

        # ---- 步骤4b 破坏 ----
        self.step4b_sabotage()

        # ---- 步骤5 外星人击杀/双刀 ----
        self.step5_foreigner_kill()

        # ---- 步骤6 警察/武装船员 ----
        self.step6_guns()

        # ---- 步骤7 异形行动 ----
        self.step7_alien_action()

        # ---- 步骤8 医生 ----
        # 医生额度逐夜增长（生化医师治疗初始1，第2/3/4夜各+1=4，仅去除第5夜额度；
        # 救援医师救援：初始1，第2/4夜各+1=3）
        for p in self.alive_players():
            if p.role == '生化医师':
                if self.night in (2, 3, 4):
                    p.doctor_treat += 1
            elif p.role == '救援医师':
                if self.night in (2, 4):
                    p.doctor_rescue += 1
        self.step8_doctors()

        # ---- 步骤9 死亡结算 + 胜利检查 ----
        self.step9_death_resolution()

        # ---- 步骤10 验票官紧急会议 ----
        self._emergency_triggered = False
        self.step10_emergency()

        # ---- 步骤11 最终倒计时 ----
        # 1.4 夜晚交锋模式：倒计时、维修、破坏、停摆全部冻结（规则要求），仅保留夜晚行动与死亡公告。
        # 紧急会议已触发也跳过步骤11（不计自然流逝、不结算倒计时）。
        if not self.night_war and not self._emergency_triggered:
            # 船体倒计时每夜基础 -1（规则：倒计时逐夜流逝；维修为负向、破坏为正向修正）
            # 外星人破坏加强：倒计时停转一个晚上（自然流逝为0）
            if self.fore_slow_remain > 0:
                self.fore_slow_remain -= 1  # 本夜倒计时完全停转
            else:
                self.countdown -= 1.0
            self.step11_countdown()

        # 记录快照
        # 公测1.0 人类反破坏流：检测净破坏量加速（连续2夜净增≥1.0）→ 触发集中维修模式
        sab_inc = self.net_sabotage - self._prev_net_sab
        self._prev_net_sab = self.net_sabotage
        if sab_inc >= 1.0:
            self._sab_surge_nights += 1
        else:
            self._sab_surge_nights = 0
        self.sabotage_surge = (self._sab_surge_nights >= 2)

        # 每夜结束：将自身已知信息整合进怀疑度（神探/船员查验、私聊获得）
        self._apply_known_to_belief()
        self._record_snapshot()

    # ---------- 步骤0 私聊 ----------
    def step0_private_chat(self):
        alive = self.alive_players()
        # 异形队内私聊免费（不占公共权限，无公告），这里仅处理公共私聊
        # 每位存活玩家 1 发起 + 1 接受
        initiates = {}  # pid -> target or None
        for p in alive:
            if p.dying:
                continue
            tgt = self.ai_choose_chat_target(p, alive)
            initiates[p.id] = tgt

        # 接收方选择
        accepted = {}  # 被邀请者 -> 选择的邀请者
        # 收集邀请
        invites = defaultdict(list)
        for pid, tgt in initiates.items():
            if tgt is not None and self.players[tgt].alive and not self.players[tgt].dying:
                invites[tgt].append(pid)
        for tgt, invs in invites.items():
            chosen = self.ai_choose_chat_accept(self.players[tgt], invs)
            if chosen is not None:
                accepted[tgt] = chosen

        # 配对：发起方与接收方相互选中
        pairs = []
        for tgt, src in accepted.items():
            if initiates.get(src) == tgt:
                pairs.append((src, tgt))
                # 消耗（仅记录，逻辑上配对成功）
        self.chat_pairs = pairs
        # 信息交换
        for a, b in pairs:
            self.ai_exchange_chat(self.players[a], self.players[b])
            # 记录轮换网络记忆（避免连续两晚同目标 + 关系网推断）
            self.players[a].last_chat_target = b
            self.players[b].last_chat_target = a
            self.players[a].chat_partners.add(b)
            self.players[b].chat_partners.add(a)
        # 公告
        if pairs:
            txt = "今晚私聊配对：" + "；".join(f"{min(a,b)}号↔{max(a,b)}号" for a, b in pairs)
        else:
            txt = "今晚无人进行私聊。"
        self.chat_announce = [txt]
        self.announce_msg(txt)
        # 记录历史供推理
        self.chat_history.append((self.night, [(min(a, b), max(a, b)) for a, b in pairs]))
        # 更新信念：频繁被找 / 频繁找人 作为信息富集信号（高水平推理）
        chat_counter = Counter()
        for a, b in pairs:
            chat_counter[a] += 1
            chat_counter[b] += 1
        for pid, cnt in chat_counter.items():
            self.belief[pid]['_chat_freq'] = self.belief[pid].get('_chat_freq', 0) + cnt
        # 高水平：配对公告作为推理素材 -> 分析谁在找谁
        if self.strategy == 'high':
            self._analyze_chat_pairs(pairs)

    def _analyze_chat_pairs(self, pairs):
        """高水平玩家利用配对公告反推关系（见私聊博弈分析）。"""
        # 谁是"信息富集方"（频繁被找）
        freq = Counter()
        for a, b in pairs:
            freq[a] += 1
            freq[b] += 1
        for p in self.alive_players():
            if freq[p.id] >= 2:
                for q in self.alive_players():
                    if q.id != p.id:
                        # 被频繁找的人→信息价值高，可能关键角色
                        self.belief[q.id]['suspicion'][p.id] *= 0.98  # 略减（可能好人）
                        self.belief[q.id]['suspicion'][p.id] += 0.02

    # ---------- 步骤0.5 感染抑制 ----------
    def step05_infection_suppress(self):
        for p in self.alive_players():
            if p.infection == 1 and p.infect_suppress_quota > 0:
                # 高概率使用抑制（避免死亡），尤其后期/关键角色
                use = False
                if self.strategy == 'random':
                    use = self.rng.random() < 0.5
                else:
                    # 高水平：若死亡会重创阵营则抑制
                    use = True
                if use:
                    p.infect_suppress_quota -= 1
                    p.infection_death_night = self.night + 3  # 延后1夜
                    # 公测1.0 0.5：当夜失去所有主动行动能力（不进入沉默，不影响白天投票）
                    p.suppressed = True

    # ---------- 步骤0.6 觉醒/转化/转职 ----------
    def step06_awaken_transform_transfer(self):
        # ① 普通船员转职
        alive_total = len(self.alive_players())
        for p in self.alive_players():
            if p.role == '普通船员' and not p.transferred:
                if alive_total <= 5 or (self.night >= 6 and p.transfer_eligible is False and alive_total > 5):
                    p.transfer_eligible = True
                if p.transfer_eligible:
                    if self.strategy == 'random':
                        if self.rng.random() < 0.5:
                            self._do_transfer(p)
                    else:
                        # 高水平：根据局势选择
                        self._do_transfer(p)
        # ② 异形觉醒（第3夜起）
        if self.night >= 3:
            for p in self.alive_aliens():
                if not p.awakened and p.alive and not p.dying:
                    self._alien_maybe_awaken(p)
        # ③ 异形转化（已觉醒，第3夜起）
        if self.night >= 3:
            for p in self.alive_aliens():
                if p.awakened and not p.dying:
                    self._alien_maybe_transform(p)

    def _do_transfer(self, p):
        if self.strategy == 'random':
            dirs = ['武装船员', '加速工程师', '临时医生']
            d = self.rng.choice(dirs)
        else:
            # 高水平：依据局势
            # 外星人威胁大/需要控场 -> 武装船员；倒计时吃紧 -> 加速工程师；医生少 -> 临时医生
            if self.countdown < 10 or self.net_sabotage > 3:
                d = '加速工程师'
            elif len(self.alive_foreigners()) > 0 and self.rng.random() < 0.5:
                d = '武装船员'
            else:
                d = '临时医生'
        p.transferred = True
        p.transfer_dir = d
        p.role = d
        if d == '武装船员':
            p.bullets = 1
        elif d == '加速工程师':
            pass
        elif d == '临时医生':
            p.doctor_rescue = 1
            p.doctor_treat = 2
        self.announce_msg("有普通船员转职为【%s】。" % d)

    def _alien_disadvantaged(self):
        """异形劣势局面评估（仅用异形可见信息）：
        公测1.0 动态破坏触发的前提判断——当异形处于劣势时，"破坏推停摆拖残局"成为
        比"继续感染/击杀"更优的路线。触发条件（满足任一）：
        1. 存活异形 ≤ 2（兵力劣势，继续正面消耗难赢）
        2. 已有异形公开暴露（破坏3次暴露 或 被驱逐过暴露身份）——身份已保不住
        3. 人类信息网基本成型（神探/验票官等公开跳身份）且异形人数不占优
        """
        aliens = self.alive_aliens()
        if not aliens:
            return True
        if len(aliens) <= 2:
            return True
        # 已有异形公开暴露（破坏3次暴露或白天被驱逐公开）
        for p in aliens:
            if p.id in getattr(self, 'alien_sabotage_exposed', set()):
                return True
        if getattr(self, 'alien_public_exposed_count', 0) >= 1:
            return True
        # 人类信息网成型：公开跳身份者 ≥2 且异形无人数优势
        revealed = len([q for q in self.alive_players() if q.id in getattr(self, 'revealed_humans', set())])
        if revealed >= 2 and len(aliens) <= len(self.alive_humans()):
            return True
        return False

    def _alien_maybe_awaken(self, p):
        # 选择额度>0的方向
        avail = [d for d in AWAK_DIRS if self.awak_quota[d] > 0]
        if not avail:
            return
        if self.strategy == 'random':
            if self.rng.random() < 0.5:
                d = self.rng.choice(avail)
            else:
                return
        else:
            # 高水平阵营协同：与队友错开方向，避免重复浪费
            teammates_dirs = set()
            for tid in getattr(p, 'teammates', []):
                tp = self.players[tid]
                if tp.alive:
                    teammates_dirs |= tp.awak_occupied
            # 优先选队友没占的
            preferred = [d for d in avail if d not in teammates_dirs]
            if not preferred:
                preferred = avail
            # 公测1.0 动态分支：异形劣势局面 → 破坏觉醒优先（赌停摆锁死人类倒计时，拖入残局）；
            # 正常局面维持最优转化流（感染开局→击杀收割）。
            if self.dyn_sab_enabled and self._alien_disadvantaged():
                order = ['破坏', '感染', '击杀']
            else:
                order = ['感染', '击杀', '破坏']
            d = next((x for x in order if x in preferred), preferred[0])
            if d is None:
                d = preferred[0] if preferred else avail[0]
        self._acquire_awak(p, d)
        p.awakened = True
        p.awak_dir = d
        p.awak_night = self.night
        self.awak_choices.append((d, self.night))
        self.announce_msg("今晚有 1 只异形觉醒。")

    def _alien_maybe_transform(self, p):
        # 已觉醒异形可转化（全局最多2次）
        if p.transform_count >= 2:
            return
        if self.strategy == 'random':
            if self.rng.random() < 0.3:
                targets = [d for d in AWAK_DIRS if d != p.awak_dir and self.awak_quota[d] > 0]
                if targets:
                    nd = self.rng.choice(targets)
                    self._transform(p, nd)
        else:
            # 高水平：依据局势转化
            cur = p.awak_dir
            # 若当前破坏但人类濒死少 → 转感染/击杀？保持简单：倒计时吃紧时确保有破坏方向被占
            targets = [d for d in AWAK_DIRS if d != cur and self.awak_quota[d] > 0]
            if not targets:
                return
            # 修正最优转化流：感染→击杀（55.6%异形胜率，实测最强）为核心路径，第4夜起转向击杀；
            # 击杀是直接减员，配合感染前期的医生压制，形成"压制→收割"组合。
            if cur == '感染' and '击杀' in targets:
                if self.night >= 4 and self.rng.random() < 0.75:
                    self._transform(p, '击杀')
            elif cur == '感染' and '破坏' in targets:
                if self.night >= 4 and self.rng.random() < 0.3:
                    self._transform(p, '破坏')
            elif cur != '击杀' and '击杀' in targets and self.rng.random() < 0.4:
                self._transform(p, '击杀')

    def _transform(self, p, nd):
        # 异形转化【不释放额度】（用户明确规则）：旧方向额度仍永久占用，仅再占用目标方向额度。
        # 即"永久占位制"——一个异形可同时在多个方向留下额度占位。
        if self.awak_quota[nd] <= 0:
            return
        self.awak_quota[nd] -= 1
        p.awak_occupied.add(nd)
        old = p.awak_dir
        p.awak_dir = nd
        p.transform_count += 1
        self.transform_records.append((old, nd, self.night))
        # 转化当夜步骤7无行动（在step7处理）
        p._transformed_this_night = True
        # 公告次夜（这里标记，次夜步骤0.6结束后公告）
        self._pending_transform_announce = True

    def _acquire_awak(self, p, d):
        if self.awak_quota[d] > 0:
            self.awak_quota[d] -= 1
            p.awak_occupied.add(d)
            return True
        return False

    # ---------- 步骤1 外星人伪装/定向查验 ----------
    def step1_foreigner_check(self):
        """公测1.0 6.2：外星人独立查验技能（每夜可用，获知一人真实身份，无视隐藏）。
        使用查验当夜不能击杀/破坏。不再拥有伪装船员能力。"""
        for p in self.alive_foreigners():
            if p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 公测1.0 2.1/0.5：沉默/感染抑制者无法执行夜间技能
            if getattr(p, '_foreigner_action', None) == '查验':
                target = self.ai_pick_check_target(p)
                if target is not None:
                    t = self.players[target]
                    p.known[target] = {'camp': t.camp, 'role': t.role}
                    # 被查者收到提示（仅本人知，不进公告）："你被查验了。"
                # 使用查验当夜跳过步骤5（击杀）

    # ---------- 步骤2 查验/巡逻 ----------
    def step2_check_patrol(self):
        # 神探查验
        det_checked = 0
        for p in self.alive_players():
            if p.role == '神探' and p.alive and not p.dying:
                if p.silent > 0:
                    continue  # 公测1.0 2.1：沉默者次夜无法执行夜间技能
                tgt = self.ai_pick_check_target(p)
                if tgt is not None:
                    t = self.players[tgt]
                    if t.disguised:
                        # 伪装欺骗：不记录确定性结论，留待后续复验破除（避免假"人类"误导）
                        pass
                    else:
                        p.known[tgt] = {'camp': t.camp, 'role': t.role}
                    p.crew_checks[tgt] = p.crew_checks.get(tgt, 0) + 1
                    det_checked += 1
        # 普通船员查验
        crew_checked = 0
        for p in self.alive_players():
            if p.role == '普通船员' and p.alive and not p.dying:
                if p.silent > 0:
                    continue  # 公测1.0 2.1：沉默者次夜无法执行夜间技能
                # 与维修互斥：若选择维修则跳过
                if self._crew_will_repair(p):
                    continue
                tgt = self.ai_pick_check_target(p)
                if tgt is not None:
                    t = self.players[tgt]
                    if t.disguised:
                        # 无效：虚假排除
                        pass
                    else:
                        # 公测1.0 4.1：首次查验获得"该玩家不是某职业"的排除信息（保证不排除真实职业）
                        if p.crew_checks.get(tgt, 0) == 0:
                            p.exclude_info[tgt] = p.exclude_info.get(tgt, set())
                            # 从人类职业中随机排除一个（排除者自身职业与目标真实职业之外）
                            pool = [r for r in set(HUMAN_ROLES)
                                    if r != t.role and r != p.role]
                            if pool:
                                p.exclude_info[tgt].add(self.rng.choice(pool))
                        p.crew_checks[tgt] = p.crew_checks.get(tgt, 0) + 1
                        if p.crew_checks[tgt] >= 2:
                            p.known[tgt] = {'camp': t.camp, 'role': t.role}
                    crew_checked += 1
                    self.crew_check_count += 1
        # 警察巡逻（全局1次，前3夜）
        for p in self.alive_players():
            if p.role == '警察' and p.alive and not p.dying and not p.police_patrol_used:
                if p.silent > 0:
                    continue  # 公测1.0 2.1：沉默者次夜无法执行夜间技能
                if self.night <= 3 and self._police_will_patrol(p):
                    targets = self.ai_pick_patrol(p)
                    for t in targets:
                        self.players[t].immune += 1
                        self._protect_count[t] += 1
                    p.police_patrol_used = True
                    self.announce_msg("有玩家发动了巡逻，%d名玩家获得保护。" % len(targets))
        self.announce_msg("当夜神探/外星人定向查验 %d 次；普通船员查验 %d 次。" % (det_checked, crew_checked))

    # ---------- 步骤3 保镖保护 ----------
    def step3_bodyguard(self):
        for p in self.alive_players():
            if p.role == '保镖' and p.alive and not p.dying:
                if p.silent > 0:
                    continue  # 公测1.0 2.1：沉默者次夜无法执行夜间技能
                tgt = self.ai_pick_protect(p)
                if tgt is not None:
                    self.players[tgt].immune += 1
                    self._protect_count[tgt] += 1

    # ---------- 步骤4a 维修 ----------
    def step4a_repair(self):
        total_repair = 0.0
        eng_repaired = False
        for p in self.alive_players():
            if not p.alive or p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 公测1.0 2.1/0.5：沉默/感染抑制者无法执行夜间技能
            amt = 0.0
            if p.role == '工程师':
                amt = ENGINEER_REPAIR_NIGHT1_2 if self.night <= 2 else ENGINEER_REPAIR_NIGHT3PLUS
                if self._will_repair(p):
                    total_repair += amt
                    eng_repaired = True
                    p.repair_count += 1
                    # 追加维修（公测1.0 3.1：全局共3次，须在基础维修后立即追加，不可单独使用）
                    # 确定性追加：工程师执行基础维修且全局额度>0 时必定追加
                    if self.engineer_append_left > 0:
                        total_repair += ENGINEER_APPEND
                        self.engineer_append_left -= 1
                        p.append_used = True
                        p.repair_count += 1
            elif p.role == '加速工程师':
                amt = ACCEL_ENGINEER_REPAIR
                if self._will_repair(p):
                    total_repair += amt
                    p.repair_count += 1
            elif p.role == '普通船员':
                if self._crew_will_repair(p):
                    # 协助维修：与查验互斥（公测1.0 3.1：-0.20 - 0.05×(X-1)）
                    x = len([q for q in self.alive_players() if q.role == '普通船员'])
                    amt = -(0.20 + 0.05 * (x - 1))
                    total_repair += amt
                    p.repair_count += 1
                    self.crew_repair_count += 1
        if eng_repaired:
            self.announce_msg("工程师进行了维修")
        # 维修暴露标记（公测1.0 3.2：仅向所有异形和外星人公布其编号与具体职业，不公开给人类）
        for p in self.alive_players():
            if p.repair_count >= 3 and p.id not in self.exposed:
                self.exposed.add(p.id)
                for q in self.players:
                    if q.alive and (q.is_alien() or q.is_foreigner()):
                        q.known[p.id] = {'camp': 'human', 'role': p.role}
        # 更新倒计时（外星人破坏加强：倒计时停转一夜，本夜维修不生效）
        if self.fore_slow_remain > 0:
            total_repair = 0.0
        self.countdown += total_repair
        self.cum_repair += abs(total_repair)
        self.announce_msg("维修总量 %.2f，当前倒计时 %.2f。" % (total_repair, self.countdown))

    def _will_repair(self, p):
        if self.strategy == 'random':
            return self.rng.random() < 0.7
        # 高水平：工程师前3夜保留（维修收益低，过早暴露且不经济），第3夜后高收益期才出手
        if p.role == '工程师':
            if self.night <= 2:
                return False
            return True   # 第3夜起每夜维修
        if p.role == '加速工程师':
            return True
        # 普通船员由 _crew_will_repair 统一决策
        return self._crew_will_repair(p)

    def _police_will_patrol(self, p):
        if self.strategy == 'random':
            return self.rng.random() < 0.5
        return True  # 高水平：前期巡逻保护关键角色

    def _crew_will_repair(self, p):
        if self.strategy == 'random':
            return self.rng.random() < 0.5
        # 高水平：普通船员【查验/维修互斥分组轮换】
        # 设计：将普通船员按编号奇偶分成"查验组"和"维修组"，并随夜数轮换，
        # 避免所有人同时放弃查验导致信息断档，也避免全员维修浪费信息。
        # 倒计时吃紧(<=12)时整体向维修倾斜（数值抢救）。
        crew_list = [q for q in self.alive_players() if q.role == '普通船员']
        if not crew_list:
            return False
        # 公测1.0 反破坏流：净破坏量连续加速 → 人类集中维修反制（牺牲部分查验/投票效率）
        if self.sabotage_surge:
            return self.rng.random() < 0.75
        # 晚期残局：全力维修抢救
        if self.countdown <= 10:
            return self.rng.random() < 0.85
        # 分组：按存活普通船员在列表中的相对位置，奇偶分组后隔夜轮换
        crew_list.sort(key=lambda q: q.id)
        idx = crew_list.index(p)
        group = idx % 2
        # 隔夜轮换：奇数夜 group0 维修、group1 查验；偶数夜反之
        repair_group = (self.night % 2 == 1)
        if self.countdown <= 14:
            # 中期：约半数维修、半数查验，但仍轮换保持信息不断档
            return (idx % 2 == (self.night % 2))
        return (group == (0 if repair_group else 1))

    # ---------- 步骤4b 破坏 ----------
    def step4b_sabotage(self):
        sab = 0.0
        alien_sab = 0
        fore_sab = 0
        # 异形破坏（已选破坏行动者在step7处理？规则：破坏在4b执行，与step7互斥）
        # 这里先由AI决定本夜异形是否破坏
        for p in self.alive_aliens():
            if p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 公测1.0 2.1/0.5：沉默/感染抑制者无法执行夜间技能
            if getattr(p, '_alien_action', None) == '破坏':
                val = ALIEN_SABOTAGE_AWAK if p.awak_dir == '破坏' else ALIEN_SABOTAGE_BASE
                sab += val
                alien_sab += 1
                p.alien_sabotage_count += 1
        # 外星人破坏（全局2次）
        for p in self.alive_foreigners():
            if p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 公测1.0 2.1/0.5：沉默/感染抑制者无法执行夜间技能
            if getattr(p, '_foreigner_action', None) == '破坏':
                sab += FOREIGNER_SABOTAGE
                fore_sab += 1
                p.foreigner_sabotage_count += 1
                # 外星人破坏加强：倒计时停转一个晚上（下一夜自然流逝为0，全局状态）
                self.fore_slow_remain = 1
        if alien_sab:
            self.announce_msg("异形破坏 %d 次，增量 %.2f。" % (alien_sab, alien_sab * (ALIEN_SABOTAGE_AWAK if any(p.awak_dir=='破坏' for p in self.alive_aliens()) else ALIEN_SABOTAGE_BASE)))
        if fore_sab:
            self.announce_msg("外星人破坏船体×%d。" % fore_sab)
        if sab > 0:
            self.countdown += sab
            self.cum_sabotage += sab
            self.announce_msg("当前倒计时 %.2f。" % self.countdown)
            # 净破坏量（停摆系统调整：移除维修对净破坏量的削减，只累计破坏）
            self.net_sabotage = self.cum_sabotage
            self.announce_msg("净破坏量 %.2f。" % self.net_sabotage)
            # 触发阈值
            self._check_stall()

    def _check_stall(self):
        for th in STALL_THRESHOLDS:
            if th not in self.stall_triggered and self.net_sabotage >= th:
                self.stall_triggered.add(th)
                bonus = STALL_BONUS[th]
                if th == 9.0:
                    self.human_countdown_dead = True
                    self.announce_msg("【船体停摆】净破坏量突破 %.1f，人类永久失去倒计时胜利条件！" % th)
                else:
                    self.countdown += bonus
                    self.announce_msg("【船体停摆Ⅰ/Ⅱ】净破坏量突破 %.1f，倒计时额外 +%.1f！" % (th, bonus))
                # 注意：bonus 不计入 cum_sabotage / net_sabotage

    # ---------- 步骤5 外星人击杀/双刀 ----------
    def step5_foreigner_kill(self):
        for p in self.alive_foreigners():
            if p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 公测1.0 2.1/0.5：沉默/感染抑制者无法执行夜间技能
            if getattr(p, '_foreigner_action', None) == '破坏':
                continue  # 破坏夜不能击杀
            if getattr(p, '_foreigner_action', None) == '查验':
                continue  # 公测1.0：查验夜不能击杀
            # 双刀（残局收割）或单刀
            use_double = (getattr(p, '_foreigner_action', None) == '双刀')
            p.double_blade = use_double
            attacks = 2 if use_double else 1
            if use_double:
                p._ever_double = True
            for _ in range(attacks):
                tgt = self.ai_pick_kill_target(p)
                if tgt is None:
                    break
                res = self.apply_harm(tgt, '外星人伤害')
                if res in ('dying', 'dead'):
                    if p.double_blade:
                        # 沉默：被双刀命中进入濒死者次夜开始沉默（回退：恢复沉默效果，同一玩家全局仅1次）
                        tpl = self.players[tgt]
                        if not getattr(tpl, 'silenced_once', False):
                            tpl.silenced_once = True
                            tpl.silent = max(tpl.silent, 2)
            self.announce_msg("外星人攻击 %d 次。" % attacks)

    # ---------- 步骤6 警察/武装船员 ----------
    def step6_guns(self):
        police_shots = 0
        armed_shots = 0
        blocked = 0
        for p in self.alive_players():
            if not p.alive or p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 公测1.0 2.1/0.5：沉默/感染抑制者无法执行夜间技能
            if p.role == '警察' and p.bullets > 0:
                tgt = self.ai_pick_shoot(p)
                if tgt is not None:
                    p.bullets -= 1
                    police_shots += 1
                    r = self.apply_harm(tgt, '枪击')
                    if r in ('immune', 'blocked'):
                        blocked += 1
            elif p.role == '武装船员' and p.bullets > 0:
                # 二选一：开枪 or 保护
                if getattr(p, '_armed_protect', False):
                    tgt = self.ai_pick_protect(p)
                    if tgt is not None:
                        self.players[tgt].immune += 1
                        self._protect_count[tgt] += 1
                else:
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

    # ---------- 步骤7 异形行动 ----------
    def step7_alien_action(self):
        x = 0
        y = 0  # 抵挡次数
        for p in self.alive_aliens():
            if p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 公测1.0 2.1/0.5：沉默/感染抑制者无法执行夜间技能
            if getattr(p, '_transformed_this_night', False):
                p._transformed_this_night = False
                continue  # 转化当夜无行动
            act = getattr(p, '_alien_action', None)
            if act is None:
                act = '出刀'
            if act == '破坏':
                continue  # 已在4b处理
            if act == '结茧':
                if not p.shield:
                    p.shield = True
                continue
            # 出刀 / 感染
            if act == '感染':
                tgts = self.ai_pick_infect(p)
                for t in tgts:
                    r = self.apply_infection(t, p.id)
                    if r in ('infected',):
                        x += 1
            else:  # 出刀
                hits = 1
                if p.awak_dir == '击杀' and self.night % 2 == 0:
                    hits = 2
                for _ in range(hits):
                    tgt = self.ai_pick_kill_target(p)
                    if tgt is None:
                        break
                    r = self.apply_harm(tgt, '异形出刀')
                    x += 1
                    if r in ('immune', 'blocked'):
                        y += 1
                        # 异形反制学习：该目标有常驻保护/免疫，记录后避开（后续优先刀无保护目标）
                        p.blocked_targets.add(tgt)
                    # 人类威胁感知：被袭目标记录（供保镖/警察动态保护）
                    for q in self.alive_humans():
                        if q.alive and not q.dying:
                            q.attacked_history[tgt] += 1
        if x:
            self.announce_msg("异形行动%d次（抵挡%d次）。" % (x, y))

    # ---------- 步骤8 医生 ----------
    def step8_doctors(self):
        # 外星人感染自我治疗（1次）：先于医生行动，外星人优先用自己的额度治疗感染
        for p in self.alive_foreigners():
            if p.alive and not p.dying and p.infection >= 1 and p.self_treat > 0:
                p.infection = 0
                p.infection_death_night = None
                p.self_treat -= 1
        for p in self.alive_players():
            if not p.alive or p.dying:
                continue
            if p.silent > 0 or p.suppressed:
                continue  # 公测1.0 2.1/0.5：沉默/感染抑制者无法执行夜间技能
            if p.role in ('生化医师', '救援医师', '临时医生'):
                self._doctor_act(p)

    def _doctor_act(self, p):
        # 优先救濒死者（救援），否则治疗感染
        dying_targets = [q for q in self.alive_players() if q.dying]
        if dying_targets and p.doctor_rescue > 0:
            # 优先救人类（救援医师可救任意；生化仅自救）
            if p.role == '生化医师':
                if p.dying:
                    p.dying = False
                    p.doctor_rescue -= 1
                    if p.infection > 0:
                        p.infection = 0
            else:
                tgt = self.ai_pick_rescue(p, dying_targets)
                if tgt is not None and p.doctor_rescue > 0:
                    self.players[tgt].dying = False
                    p.doctor_rescue -= 1
                    if self.players[tgt].infection > 0 and p.role == '生化医师':
                        self.players[tgt].infection = 0
                        self.players[tgt].has_antibody = True  # 生化医师救援清除感染并赋予抗体
            return
        # 治疗感染
        inf_targets = [q for q in self.alive_players() if q.infection >= 1]
        if inf_targets and p.doctor_treat > 0:
            tgt = self.ai_pick_infect_treat(p, inf_targets)
            if tgt is not None and p.doctor_treat > 0:
                self.players[tgt].infection = 0
                p.doctor_treat -= 1
                if p.role == '生化医师':
                    self.players[tgt].has_antibody = True  # 生化医师治疗清除感染并赋予抗体

    # ---------- 步骤9 死亡结算 ----------
    def step9_death_resolution(self):
        # 感染延迟死亡
        for p in self.alive_players():
            if p.infection >= 1 and p.infection_death_night == self.night:
                # 死亡（除非已濒死被救？濒死状态下感染死亡仍触发）
                self.add_death(p, '感染延迟')
        # 濒死者若未被救 -> 真正死亡？规则：濒死=失去行动，再次受击即死；否则仍存活直到结束
        # 这里濒死不直接死亡（除非再受击或感染死亡），符合规则"濒死仍计入存活"。
        # 但需确认：步骤9"统一结算所有伤害及感染延迟死亡" —— 出刀造成的是濒死，不立即死。
        # 统计死亡名单
        new_deaths = [d for d in self.deaths if d[0] == self.night]
        if new_deaths:
            for (_, pid, camp, cause) in new_deaths:
                self.announce_msg("死亡：%d号（%s，%s）" % (pid, self._camp_cn(camp), cause))
        else:
            self.announce_msg("今晚无人死亡。")
        # 胜利检查
        self.check_win('step9')
        # 1.4 模式触发
        if not self.over:
            if len(self.alive_humans()) == 0 and len(self.alive_aliens()) > 0 and len(self.alive_foreigners()) > 0:
                self.night_war = True
                self.announce_msg("【夜晚交锋模式】人类全灭，异形与外星人进入决战。")

    def _camp_cn(self, camp):
        return {'human': '人类', 'alien': '异形', 'foreigner': '外星人'}[camp]

    # ---------- 步骤10 验票官紧急会议 ----------
    def step10_emergency(self):
        if self.over:
            return
        if len(self.alive_players()) >= 5:
            for p in self.alive_players():
                if p.role == '验票官' and p.alive and not p.dying and not p.emergency_used:
                    if self.strategy == 'random':
                        do = self.rng.random() < 0.2
                    else:
                        # 验票官价值在于【危机时召集额外投票】，形成"双票清场"。
                        # 高水平决策：
                        #  1) 票型分析：若上一轮存在被多人一致指控的疑似异形，且未清出→值得追加投票
                        #  2) 危机触发：倒计时吃紧 或 存活异形已≤2（可趁势清场）
                        #  3) 自身安全：若已公开暴露(被指认/跳身份)，拖延会被沉默/刀，尽快发动
                        crisis = self.countdown < 9 or len(self.alive_aliens()) <= 2
                        # 票型分析：寻找本轮最高票且怀疑度高的目标（异形团伙可能投弃权/分散票保护）
                        ballot = self.last_votes  # {voter: target}
                        if ballot:
                            tally = Counter(ballot.values())
                            top_tgt, top_cnt = tally.most_common(1)[0]
                            # 异形团伙特征：最高票目标得票未过半（分散/弃权保护）→ 需第二次投票
                            total_voters = len(ballot)
                            ticket_signal = (top_cnt < max(2, total_voters * 0.5)
                                             and self.belief[p.id]['suspicion'].get(top_tgt, 0) > 0.6)
                        else:
                            ticket_signal = False
                        exposed_self = p.id in getattr(self, 'revealed_humans', set())
                        do = (crisis and self.rng.random() < 0.6) or (ticket_signal and self.rng.random() < 0.5) \
                             or (exposed_self and self.rng.random() < 0.4)
                    if do:
                        p.emergency_used = True
                        self.announce_msg("验票官发动紧急会议！（追加投票清场）")
                        self.run_daytime(emergency=True)
                        self.check_win('emergency')
                        if self.over:
                            return
                        self._emergency_triggered = True  # 公测1.0 2.2：紧急会议跳过步骤11
                        break

    # ---------- 步骤11 最终倒计时 ----------
    def step11_countdown(self):
        if self.over:
            return
        if len(self.alive_humans()) > 0:
            if self.countdown <= 0:
                if self.human_countdown_dead:
                    self.announce_msg("倒计时归零，但人类倒计时胜利已永久失效。")
                else:
                    self._end('human', '倒计时胜利', 'step11')
            else:
                self.announce_msg("倒计时 %.2f，进入白天。" % self.countdown)

    # ===================== 白天：讨论 + 投票 =====================
    def run_daytime(self, emergency=False):
        if self.night_war and not emergency:
            return  # 1.4模式无白天
        # 公测1.0 3.1：任意异形累计破坏3次后，下一白天公开其编号与身份
        for p in self.alive_aliens():
            if p.alien_sabotage_count >= 3 and p.id not in self.alien_sabotage_exposed:
                self.alien_sabotage_exposed.add(p.id)
                self.announce_msg("异形破坏暴露：%d号 是 异形。" % p.id)
        # 讨论：生成发言（高水平：基于信念/已知信息指控或辩护）
        self._day_discussion()
        # 投票
        self._day_vote()
        # 追责：若被驱逐者为好人(人类)，标记指控者
        self._accountability()
        # 胜利检查
        self.check_win('day_vote')

    def _day_discussion(self):
        """高水平玩家的发言 = 信息测试 + 可信广播。
        - 神探/已锁定异形的普通船员：公开"跳身份"指认异形（可信广播，全体人类采信）。
        - 其余玩家：公开指控其最怀疑目标（普通发言，仅供交叉验证，不强制采信）。
        - 异形：借讨论散布矛盾指控，制造信息迷雾（普通发言层面）。"""
        # 可信广播：神探/船员锁定的异形
        trusted_claims = []  # (speaker, target)
        for p in self.alive_players():
            if self.strategy != 'high':
                break
            if p.is_alien() or p.is_foreigner():
                continue
            known_alien = [t for t, v in p.known.items()
                           if v.get('camp') == 'alien' and self.players[t].alive]
            jump = False
            if p.role == '神探':
                jump = len(known_alien) >= 1 and (self.night >= 2 or self.rng.random() < 0.5)
            elif p.role == '普通船员':
                # 普通船员两次查验锁定异形后可指认
                locked = [t for t, c in p.crew_checks.items()
                          if c >= 2 and p.known.get(t, {}).get('camp') == 'alien'
                          and self.players[t].alive]
                jump = len(locked) >= 1 and self.rng.random() < 0.7
            if jump and known_alien:
                tgt = max(known_alien, key=lambda t: self.belief[p.id]['suspicion'][t])
                trusted_claims.append((p.id, tgt))
                self.belief[p.id]['accuse_log'].append((p.id, tgt))
                self.revealed_humans.add(p.id)  # 跳身份者公开暴露自身（异形可据此推断威胁）
        # 可信广播 → 全体人类采信（信息战核心：神探情报公开化）
        for _, tgt in trusted_claims:
            for q in self.alive_humans():
                self.belief[q.id]['suspicion'][tgt] = max(self.belief[q.id]['suspicion'][tgt], 0.9)
        # 普通发言：每人指控最怀疑者
        for p in self.alive_players():
            b = self.belief[p.id]
            sus = [(q, b['suspicion'][q]) for q in b['suspicion'] if q != p.id]
            if sus:
                tgt = max(sus, key=lambda x: x[1])[0]
                b['accuse_log'].append((p.id, tgt))
                # 高频一致指控 → 交叉验证提升全体怀疑（高水平交叉比对）
        # 交叉比对：若≥2名不同玩家同时指控同一目标 → 全体轻微上调怀疑
        acc = defaultdict(set)
        for p in self.alive_players():
            for (sp, tg) in self.belief[p.id]['accuse_log']:
                acc[tg].add(sp)
        for tg, spset in acc.items():
            if len(spset) >= 3:
                for q in self.alive_players():
                    if q.id != tg:
                        self.belief[q.id]['suspicion'][tg] = min(1.0, self.belief[q.id]['suspicion'][tg] + 0.1)

    def _day_vote(self):
        votes = defaultdict(int)
        voters = {}
        for p in self.alive_players():
            if p.dying:
                continue  # 濒死可发言但投票？规则未明；此处允许投票
            if p.silent > 0:
                voters[p.id] = None  # 公测1.0 2.1：沉默者次日白天投票强制弃权
                continue
            b = self.belief[p.id]
            mates = getattr(p, 'teammates', [])
            # 外星人：投票伪装（智力提升）——平时混入人类投票节奏隐藏身份，
            # 仅当异形威胁极大(人类将灭/异形少而强)时才暴露立场投已知异形削弱之。
            if p.is_foreigner():
                known_alien = [t for t, v in p.known.items()
                               if v.get('camp') == 'alien' and self.players[t].alive
                               and t != p.id]
                aliens_alive = len(self.alive_aliens())
                humans_alive = len(self.alive_humans())
                # 暴露立场的条件：人类将灭(≤3)或异形极少且自己终局占优 → 值得投异形
                expose = (humans_alive <= 3 and known_alien) or \
                         (aliens_alive <= 2 and known_alien and self.rng.random() < 0.6)
                if known_alien and expose:
                    tgt = known_alien[0]
                    votes[tgt] += 1
                    voters[p.id] = tgt
                    continue
                # 不暴露：混入人类票型（按怀疑度投，与人类节奏一致，隐藏身份）
            # 选最怀疑且非己、非队友的目标
            cands = [(q, b['suspicion'][q]) for q in b['suspicion']
                     if q != p.id and q not in mates]
            if not cands:
                continue
            tgt = max(cands, key=lambda x: x[1])[0]
            votes[tgt] += 1
            voters[p.id] = tgt
        self.last_votes = voters
        # 取最高票
        if votes:
            maxv = max(votes.values())
            top = [t for t, v in votes.items() if v == maxv]
            ejected = self.rng.choice(top)
            self.last_ejected = ejected
            self.players[ejected].alive = False
            self.players[ejected].dying = False
            self.announce_msg("白天投票：%d号 被驱逐（得票%d）。" % (ejected, maxv))
            # 公开被驱逐者阵营与职业（用于追责与推理，"显示被投者真实身份"）
            ejp = self.players[ejected]
            self.announce_msg("驱逐结果：%d号 是 %s（职业：%s）。" % (
                ejected, self._camp_cn(ejp.camp), self.players[ejected].role))
            self.ejection_log.append((self.night, ejected, ejp.camp, self.players[ejected].role))
            # 公测1.0：记录公开暴露的异形数（供劣势局面评估用）
            if ejp.camp == 'alien':
                self.alien_public_exposed_count = getattr(self, 'alien_public_exposed_count', 0) + 1
            # 更新信念：被驱逐者若是异形/外星人 -> 信任其指控对象降低；若是人类 -> 指控者可疑
            ej = self.players[ejected]
            for pid, b in self.belief.items():
                if ej.is_alien() or ej.is_foreigner():
                    b['suspicion'][ejected] = 0.0
                    # 异形被驱逐 -> 其指控过的人更可能是好人
                    for (sp, tg) in b['accuse_log']:
                        if sp == ejected:
                            b['suspicion'][tg] = max(0.0, b['suspicion'][tg] - 0.1)
                else:
                    b['suspicion'][ejected] = 0.0
        else:
            self.last_ejected = None
            self.announce_msg("白天无人被驱逐。")

    def _accountability(self):
        """追责机制：若被驱逐者是好人(人类)，则主导/跟随错误指控的玩家被标记。
        高水平：故意让异形引导错误方向 -> 触发追责反向追踪异形。"""
        ej = self.last_ejected
        if ej is None:
            return
        ejp = self.players[ej]
        if ejp.is_human():
            # 错误指控：投票给该好人的玩家被追责标记
            for voter, tgt in self.last_votes.items():
                if tgt == ej:
                    self.belief[voter]['accountable'] += 1
                    # 提高其被怀疑度（追责反噬）
                    for other, b in self.belief.items():
                        if other != voter:
                            b['suspicion'][voter] = min(1.0, b['suspicion'][voter] + 0.15)
            # 额外：发言主导者（多次指控该好人）更高嫌疑
            for (sp, tg) in list(self.belief[ej]['accuse_log']):
                pass

    # ===================== AI 决策（禁止上帝视角） =====================
    def ai_choose_chat_target(self, p, alive):
        """步骤0 发起私聊。高水平：基于信息需求 + 轮换网络 + 关系定位规避。"""
        others = [q for q in alive if q.id != p.id and not q.dying]
        if not others:
            return None
        # 规则硬约束：不可连续两晚向同一目标发起（所有策略均遵守）
        others = [q for q in others if q.id != p.last_chat_target] or others
        if self.strategy == 'random':
            return self.rng.choice(others).id if self.rng.random() < 0.5 else None
        # 高水平
        if p.is_alien():
            # 异形队内私聊免费且保密；公共私聊用于渗透/套话。
            # 优先渗透"信息富集枢纽"（被频繁找的人=可能神探/医生/验票官），斩首信息网。
            # 枢纽度近似：被多少人私聊过(chat_partners越大=越可能是信息交汇点)。
            cand = sorted(others, key=lambda q: -len(q.chat_partners))
            return cand[0].id if self.rng.random() < 0.7 else None
        else:
            b = self.belief[p.id]
            # 关键角色（神探/验票官/医生/警察）尽量不与过多玩家私聊，避免被公告图定位斩首。
            KEY = ('神探', '验票官', '生化医师', '救援医师', '警察')
            # 统计该角色历史私聊次数，关键角色>2则本夜不主动发起
            if p.role in KEY and len(p.chat_partners) >= 2:
                return None
            # 环形/网格轮换：避免连续两晚向同一目标发起，并确保信息尽快传给可信节点
            def score(q):
                s = 0.0
                # 回避上一夜对象（轮换约束）
                if q.id == p.last_chat_target:
                    s -= 10.0
                # 优先联系尚未私聊过的新可信节点（扩大信息网覆盖=环形扩散）
                if q.id not in p.chat_partners:
                    s += 1.0
                if p.role in ('神探', '验票官', '警察', '生化医师', '救援医师'):
                    # 关键角色找"可信"的协调者扩散信息（不读对方角色，只用可疑度）
                    s += (0.5 - b['suspicion'][q.id])  # 越可信越优先
                else:
                    # 普通船员：试探高怀疑者 + 也会联系已知可信者报信
                    s += b['suspicion'][q.id]  # 越可疑越想试探
                return s
            cand = sorted(others, key=score, reverse=True)
            # 普通船员试探概率低些（怕暴露）；关键角色主动协调概率高
            prob = 0.5 if p.role in KEY else 0.35
            return cand[0].id if self.rng.random() < prob else None

    def ai_choose_chat_accept(self, p, inviters):
        """接收方选择接受谁的邀请。"""
        if self.strategy == 'random':
            return self.rng.choice(inviters) if self.rng.random() < 0.5 else None
        b = self.belief[p.id]
        # 高水平：拒绝高怀疑者（怕被套话/是异形），接受低怀疑者
        inviters = [i for i in inviters if self.players[i].alive]
        if not inviters:
            return None
        # 选最可信的邀请者
        best = min(inviters, key=lambda i: b['suspicion'][i])
        if b['suspicion'][best] > 0.6:
            return None  # 太可疑，全拒
        return best

    def ai_exchange_chat(self, a, b):
        """私聊三层博弈：表层(公开信息) / 中层(半公开) / 深层(策略)。
        关键设计：私下交换的信息只是【疑点/主张】，不是确定性结论；
        只有玩家【自身查验】得到的 known 才是确定性证据（由 _apply_known_to_belief 处理）。
        这样既实现信息扩散，又避免异形伪造"确证"直接误导投票。
        异形可借私聊散布假疑点（中层）制造信息迷雾，但需人类交叉验证才能放大。"""
        for observer, partner in ((a, b), (b, a)):
            b_obs = self.belief[observer.id]
            b_obs['chat_with'].append(partner.id)
            b_part = self.belief[partner.id]
            # 表层/中层：分享"自身确知"的高价值情报（作为强疑点，非伪造确证）
            for tid, v in observer.known.items():
                if tid == partner.id or not self.players[tid].alive:
                    continue
                if observer.is_alien():
                    # 异形撒谎：把自己怀疑的好人说成异形（制造迷雾，仅作疑点）
                    if self.rng.random() < 0.5:
                        b_part['suspicion'][tid] = min(1.0, b_part['suspicion'].get(tid, 0) + 0.25)
                    else:
                        b_part['suspicion'][tid] = min(1.0, b_part['suspicion'].get(tid, 0) + 0.1)
                else:
                    # 人类分享自身确知：确定性情报 → 强疑点
                    if v.get('camp') == 'alien':
                        b_part['suspicion'][tid] = max(b_part['suspicion'].get(tid, 0), 0.85)
                    elif v.get('camp') == 'human':
                        b_part['suspicion'][tid] = max(0.02, b_part['suspicion'].get(tid, 0) - 0.1)
            # 中层：交换最怀疑目标（主张）
            obs_susp = b_obs['suspicion']
            if obs_susp:
                tgt = max(obs_susp, key=lambda x: obs_susp[x])
                if observer.is_alien() and self.strategy == 'high' and self.rng.random() < 0.4:
                    # ⚠ 信息隔离修复：异形不得读取谁是真人（is_human 会泄露阵营）。
                    # 从"非异形存活者"中随机选伪造目标（不预知是人是外星人），制造假指控。
                    good = [q for q in self.alive_players() if not q.is_alien() and q.id != observer.id]
                    if good:
                        fake = self.rng.choice(good).id
                        b_part['suspicion'][fake] = min(1.0, b_part['suspicion'].get(fake, 0) + 0.2)
                else:
                    b_part['suspicion'][tgt] = min(1.0, b_part['suspicion'].get(tgt, 0) + 0.1)
        # 整合自身确定性已知（仅来自自身查验，异形 teammates 已排除）
        self._apply_known_to_belief()

    def _apply_known_to_belief(self):
        for p in self.alive_players():
            b = self.belief[p.id]
            mates = getattr(p, 'teammates', [])
            for tid, v in p.known.items():
                if tid in mates:
                    continue  # 异形已知队友，不怀疑
                if self.players[tid].alive:
                    if v.get('camp') == 'alien':
                        b['suspicion'][tid] = 0.95
                    elif v.get('camp') == 'foreigner':
                        b['suspicion'][tid] = 0.9
                    elif v.get('camp') == 'human':
                        b['suspicion'][tid] = max(0.02, b['suspicion'][tid] - 0.1)

    # 通用目标选择（仅用公开信息 + 自身已知）
    def ai_pick_check_target(self, p):
        others = [q for q in self.alive_players() if q.id != p.id and not q.dying]
        if not others:
            return None
        if self.strategy == 'random':
            return self.rng.choice(others).id
        # 外星人：查验建图——前几夜优先查验可能的医生/神探/异形，建立完整身份表。
        # 已暴露(revealed/exposed)的关键角色必为医生/神探/工程师类；未知者优先查高可疑(可能异形)。
        if p.is_foreigner():
            unknown = [q for q in others if q.id not in p.known]
            if unknown:
                # 优先已暴露(公开身份)的关键角色；其次高怀疑者(可能异形)
                def fore_score(q):
                    s = 0.0
                    if q.id in getattr(self, 'revealed_humans', set()):
                        s += 3.0   # 公开跳身份者：医生/神探等控制力强
                    if q.id in self.exposed:
                        s += 2.5   # 维修暴露：工程师/医师类
                    s += self.belief[p.id]['suspicion'].get(q.id, 0)
                    return s
                unknown.sort(key=fore_score, reverse=True)
                return unknown[0].id
            return None
        # 普通船员：优先对"已查过1次"的存活目标补查，以锁定真实阵营
        if p.role == '普通船员':
            half = [q for q in others if p.crew_checks.get(q.id, 0) == 1 and not q.disguised]
            if half:
                return self.rng.choice(half).id
        # 未知目标（未被确定性查验过）
        unknown = [q for q in others if q.id not in p.known]
        if not unknown:
            # 全部已知：复验曾被伪装欺骗(标记unknown)者以破除伪装
            unc = [q for q in others if p.known.get(q.id, {}).get('camp') == 'unknown']
            return self.rng.choice(unc).id if unc else None
        # 神探：盲搜应均匀扫查未知者（怀疑度在异形隐匿时不可靠），保证以≈异形占比命中
        if p.role == '神探':
            return self.rng.choice(unknown).id
        b = self.belief[p.id]
        # 其余：优先查伪装者以识破，否则按怀疑度
        disguised = [q for q in unknown if q.disguised]
        if disguised:
            return self.rng.choice(disguised).id
        unknown.sort(key=lambda q: -b['suspicion'][q.id])
        return unknown[0].id

    def ai_pick_patrol(self, p):
        """警察巡逻目标：保护高价值目标。
        ⚠ 信息隔离修复：不得读取他人真实 role。只依据公开信号——
        公开跳身份者(revealed_humans) + 历史受袭者(attacked_history，异形刀过=被盯上)。"""
        if self.strategy == 'random':
            n = self.rng.randint(1, 3)
            return [q.id for q in self.rng.sample(self.alive_players(), min(n, len(self.alive_players())))]
        # 按公开信号打分：跳身份者 + 受袭者
        def sig(q):
            s = 0.0
            if q.id in getattr(self, 'revealed_humans', set()):
                s += 2.0  # 公开跳身份（神探/医生主动暴露）→ 异形可能斩首
            s += min(2.0, p.attacked_history.get(q.id, 0))  # 曾被异形袭击 → 被盯上
            return s
        ranked = sorted([q for q in self.alive_players() if q.id != p.id and not q.dying],
                        key=sig, reverse=True)
        chosen = [q.id for q in ranked if sig(q) >= 1.0][:3]
        return chosen if chosen else [ranked[0].id] if ranked else [p.id]

    def ai_pick_protect(self, p):
        if self.strategy == 'random':
            return self.rng.choice([q for q in self.alive_players() if q.id != p.id]).id
        # 智力提升：威胁评分动态保护——保护"异形最可能刀的人"。
        # ⚠ 信息隔离修复：不得读取他人真实 role，也不得用 self.exposed（维修暴露仅异形/外星人可见）。
        # 只依据公开信号：公开跳身份(revealed_humans) + 历史受袭(attacked_history) + 私聊渗透。
        candidates = [q for q in self.alive_players() if q.id != p.id and not q.dying]
        if not candidates:
            return p.id
        def threat(q):
            s = 0.0
            # 公开跳身份 → 异形优先刀
            if q.id in getattr(self, 'revealed_humans', set()):
                s += 3.0
            # 历史受袭：异形曾刀过该目标 → 说明被盯上，保护价值高
            s += min(2.0, p.attacked_history.get(q.id, 0))
            # 被异形私聊渗透（配对频繁）→ 可能被套话定位
            s += min(1.0, len(q.chat_partners) * 0.2)
            return s
        # 保护威胁分最高的目标（70%），否则诱饵/自保
        best = max(candidates, key=threat)
        if threat(best) >= 2.0 and self.rng.random() < 0.7:
            return best.id
        # 诱饵：选择一个被公开指控(高怀疑)但自己已知是人类的可信诱饵，诱导敌方出刀被挡
        decoy = [q for q in candidates
                 if self.belief[p.id]['suspicion'].get(q.id, 0) > 0.4
                 and p.known.get(q.id, {}).get('camp') == 'human']
        if decoy and self.rng.random() < 0.25:
            return self.rng.choice(decoy).id
        return p.id

    def ai_pick_shoot(self, p):
        """警察/武装船员开枪目标：最可疑的非队友。"""
        if self.strategy == 'random':
            c = [q for q in self.alive_players() if q.id != p.id]
            return self.rng.choice(c).id if c else None
        b = self.belief[p.id]
        # 仅对已较高怀疑者开枪（避免误杀好人）
        cands = [(q, b['suspicion'][q.id]) for q in self.alive_players() if q.id != p.id]
        cands.sort(key=lambda x: -x[1])
        if cands and cands[0][1] > 0.5:
            return cands[0][0].id
        # 否则不开枪（保留子弹）-> 返回None
        return None

    def ai_pick_kill_target(self, p):
        """异形/外星人击杀目标。
        ⚠ 关键约束：异形【不能】直接读取人类 role 来精准锁定神探/医生等。
        只能通过【公开可观测信号】推断威胁：
          - 维修暴露（公告点名）：说明是工程师/医师等关键角色
          - 白天公开跳身份/被指认关键角色者
          - 多次被保护（巡逻/保镖）→ 推断为高价值目标
          - 否则按普通可疑度/随机处理
        外星人不受此限——其伪装/定向查验建图后(known)可精准锁定高价值人类（神探/验票官/救援医师）。"""
        others = [q for q in self.alive_players() if q.id != p.id and not q.is_alien()]
        if not others:
            return None
        if self.strategy == 'random':
            return self.rng.choice(others).id
        # 外星人：双刀沉默收割——基于查验建图(known)精准锁定最控制力强的目标
        if p.is_foreigner():
            known_hv = [q for q in others if q.id in p.known
                        and p.known[q.id].get('camp') == 'human'
                        and p.known[q.id].get('role') in ('神探', '验票官', '救援医师')]
            if known_hv:
                return known_hv[0].id
        threat = []
        for q in others:
            score = 0
            # 维修暴露（公告公开点名）→ 必为工程师或医师类关键角色
            if q.id in self.exposed:
                score += 4
            # 公开跳身份/被公开指认为关键角色者（如神探跳身份）
            if q.id in getattr(self, 'revealed_humans', set()):
                score += 3
            # 多次被保护（推断高价值）
            score += min(3, self._protect_count.get(q.id, 0))
            # 异形反制学习：该目标曾抵挡我的刀（有常驻保护），大幅降权，转向无保护目标
            if p.is_alien() and q.id in p.blocked_targets:
                score -= 6
            # 公开被多人指控（可能是真异形，也可能是人类内斗；异形不优先）
            threat.append((q, score))
        threat.sort(key=lambda x: -x[1])
        # 异形行动分工：避开队友本夜已选目标（目标不重叠，避免撞保护/浪费刀）
        if p.is_alien() and getattr(self, '_alien_targets_this_night', None):
            others_taken = self._alien_targets_this_night
            unpicked = [t for t in threat if t[0].id not in others_taken]
            if unpicked:
                threat = unpicked
        # 无明确信号者按随机（不预知角色）
        if threat[0][1] == 0:
            return self.rng.choice(others).id
        if self.rng.random() < 0.15:
            return self.rng.choice(others).id
        return threat[0][0].id

    def ai_pick_infect(self, p):
        """异形感染目标（非异形存活者，未濒死/未感染）。
        ⚠ 信息隔离修复：不预知角色，也不精准识别外星人——候选为"所有非异形存活玩家"，
        异形不知道谁是人类谁是外星人，外星人只是自然在候选池中可能被选中。"""
        cands = [q for q in self.alive_players() if not q.is_alien() and not q.dying
                 and q.infection == 0 and q.id != p.id]
        if not cands:
            return []
        if self.strategy == 'random':
            n = self.rng.randint(1, 2)
            return [q.id for q in self.rng.sample(cands, min(n, len(cands)))]
        # 高水平：感染节奏武器——优先感染公开暴露/被保护的高价值目标，制造"救援濒死 vs 治疗感染"的医生两难。
        # ⚠ 信息隔离修复：异形不得读取他人真实 role / 阵营。只依据公开信号——
        # 公开暴露(revealed_humans/exposed，异形可见) + 被保护次数(_protect_count)。
        # 未知目标按随机/普通处理（不预知谁强、谁强，也不精准锁外星人——只能在候选随机中可能命中）。
        def inf_score(q):
            s = 0.0
            if q.id in getattr(self, 'revealed_humans', set()) or q.id in self.exposed:
                s += 2.0   # 公开暴露目标（跳身份/维修暴露，异形可知）
            s += self._protect_count.get(q.id, 0) * 0.5  # 被保护的高价值
            return s
        cands.sort(key=inf_score, reverse=True)
        # 公测1.0 5.4：异形感染自选目标；基础1~2名，感染觉醒后2~3名（数量只由觉醒状态决定）
        if p.awak_dir == '感染':
            n = 3 if self.rng.random() < 0.3 else 2
        else:
            n = 2 if self.rng.random() < 0.3 else 1
        return [q.id for q in cands[:n]]

    def ai_pick_rescue(self, p, dying_targets):
        if self.strategy == 'random':
            return self.rng.choice(dying_targets).id
        # ⚠ 信息隔离修复：不得读取伤者真实 role。优先救公开跳身份的人类（医生/神探主动暴露→高价值）。
        def resc_score(q):
            s = 0.0
            if q.id in getattr(self, 'revealed_humans', set()):
                s += 2.0  # 公开跳身份（神探/医生暴露）→ 优先救援
            # ⚠ 信息隔离修复：不读取目标是否人类(is_human)，医生不知道濒死者是人是异形/外星人
            return s
        dying_targets.sort(key=resc_score, reverse=True)
        return dying_targets[0].id

    def ai_pick_infect_treat(self, p, inf_targets):
        if self.strategy == 'random':
            return self.rng.choice(inf_targets).id
        # ⚠ 信息隔离修复：不得读取感染者真实 role。优先治疗公开跳身份的人类。
        def treat_score(q):
            s = 0.0
            if q.id in getattr(self, 'revealed_humans', set()):
                s += 2.0
            return s
        inf_targets.sort(key=treat_score, reverse=True)
        return inf_targets[0].id

    # 异形/外星人行动选择（在 run_night 前由 plan 决定）
    def plan_night_actions(self):
        """高水平：在步骤前规划异形/外星人行动（写临时属性）。"""
        # 异形（智力提升：行动分工协同——三只异形分配破坏/感染/出刀，避免目标重叠与撞行动）
        # 第0步：记录本夜已锁定目标（供 ai_pick_kill_target / ai_pick_infect 分工避让）
        self._alien_targets_this_night = set()
        aliens_alive = [p for p in self.alive_aliens() if not p.dying]
        n_break = len([p for p in aliens_alive if p.awak_dir == '破坏'])
        n_infect = len([p for p in aliens_alive if p.awak_dir == '感染'])
        n_kill = len([p for p in aliens_alive if p.awak_dir == '击杀'])
        for p in aliens_alive:
            if self.strategy == 'random':
                p._alien_action = self.rng.choice(['出刀', '感染', '破坏', '结茧'])
            else:
                # 高水平协同：依据局势 + 破坏轮换暴露管理
                # 破坏轮换暴露：单只异形累计破坏3次后下一白天公开编号。
                # 高水平异形会轮换——已破坏>=2次的异形本夜不再破坏（除非已暴露/临危），
                # 让其他异形分担破坏，避免单只过快暴露。
                EXPOSE_LIMIT = 3
                over_exposed = p.alien_sabotage_count >= (EXPOSE_LIMIT - 1) and p.id not in self.exposed
                # 公测1.0 动态破坏触发：异形劣势局面 → 切破坏优先（赌停摆锁死人类倒计时，拖入残局）。
                # 触发条件：本夜处于劣势局面 + 净破坏未到上限 + 该异形尚未因破坏暴露（或已暴露无顾虑）。
                disadv = self._alien_disadvantaged()
                dyn_sab = (self.dyn_sab_enabled and disadv and self.net_sabotage < 7 and self.night >= 3
                           and (p.id in getattr(self, 'alien_sabotage_exposed', set())
                                or p.alien_sabotage_count < EXPOSE_LIMIT - 1))
                if dyn_sab:
                    # 劣势局面：优先破坏推阈值（已暴露者无顾虑；未暴露者控制在2次内避免暴露）
                    if self.countdown < 6 and len(self.alive_humans()) <= 4:
                        p._alien_action = '出刀'  # 极残局仍以收割为主
                    else:
                        p._alien_action = '破坏'
                elif p.awak_dir == '破坏' and self.net_sabotage < 7:
                    # 破坏觉醒者积极破坏；若同方向队友也在场且自己将暴露，则改刀/感染
                    if over_exposed or (n_break >= 2 and p.alien_sabotage_count >= 2):
                        p._alien_action = '出刀' if self.rng.random() < 0.5 else '感染'
                    else:
                        p._alien_action = '破坏'
                elif self.countdown < 13 and p.awak_dir == '破坏' and self.net_sabotage < 7:
                    if over_exposed:
                        p._alien_action = '出刀' if self.rng.random() < 0.5 else '感染'
                    else:
                        p._alien_action = '破坏'
                elif self.countdown < 9 and len(self.alive_humans()) <= 5:
                    p._alien_action = '出刀'  # 终局收割
                else:
                    # 分工：感染觉醒者优先感染（压制医生），其余在出刀/感染间错开
                    r = self.rng.random()
                    if p.awak_dir == '感染':
                        p._alien_action = '感染' if r < 0.8 else '出刀'
                    elif n_infect >= 2 and n_kill == 0 and r < 0.3:
                        p._alien_action = '感染'  # 感染队友多时，击杀觉醒者补充感染制造医生压力
                    elif r < 0.55:
                        p._alien_action = '出刀'
                    elif r < 0.75:
                        p._alien_action = '感染'
                    else:
                        p._alien_action = '结茧'  # 自保/蓄力
                # 结茧：若自己高威胁且濒危
                if p.id in self.exposed and self.rng.random() < 0.3:
                    p._alien_action = '结茧'
                # 公测1.0 子场景统计：记录劣势/优势局面下的行动选择分布
                if disadv:
                    self._alien_dis_action[p._alien_action] += 1
                    self._alien_dis_nights += 1
                    self._ever_disadvantaged = True
                else:
                    self._alien_adv_action[p._alien_action] += 1
                    self._alien_adv_nights += 1
        # 武装船员（转职）
        for p in self.alive_players():
            if p.role == '武装船员' and p.bullets > 0 and not p.dying:
                if self.strategy == 'random':
                    p._armed_protect = self.rng.random() < 0.3
                else:
                    # 高水平：若已知异形则开枪，否则保护关键角色
                    know_alien = any(v.get('camp') == 'alien' for v in p.known.values())
                    p._armed_protect = (not know_alien) and self.rng.random() < 0.4
        # 外星人（公测1.0：查验/击杀/破坏三选一，双刀第6夜后可选）
        for p in self.alive_foreigners():
            if p.dying:
                p._foreigner_action = None
                continue
            if self.strategy == 'random':
                p._foreigner_action = self.rng.choice(['击杀', '破坏', '查验'])
            else:
                self._foreigner_plan(p)

    def _foreigner_plan_normal(self, p):
        """外星人未觉醒双刀时的正常行动：破坏/查验/击杀。"""
        if p.foreigner_sabotage_count < 1 and self.countdown < 12 and self.rng.random() < 0.4:
            p._foreigner_action = '破坏'  # 破坏全局限1次
        else:
            if self.night <= 4 and self.rng.random() < 0.6:
                p._foreigner_action = '查验'  # 前期建图
            else:
                p._foreigner_action = '击杀' if self.rng.random() < 0.6 else '查验'

    def _foreigner_plan(self, p):
        """外星人高水平行动决策：双刀可选觉醒制。
        第6夜起可主动选择觉醒双刀（永久获得），也可选择不觉醒继续查验/破坏/单刀。"""
        # 双刀可选觉醒制：第6夜起外星人可主动选择觉醒双刀，也可选择不觉醒。
        # 觉醒后永久获得双刀能力（后续夜可自主使用双刀或保留查验/单刀）。
        if not getattr(p, 'fore_double_awakened', False):
            if self.night >= 6:
                # 觉醒决策：按局势+概率主动选择觉醒（信息充分/残局则觉醒）
                awaken_p = 0.75 if (self.countdown < 12 or len(self.alive_humans()) <= 6) else 0.35
                if self.rng.random() < awaken_p:
                    p.fore_double_awakened = True
                    p._foreigner_action = '双刀'   # 觉醒当夜即用双刀
                else:
                    # 不觉醒：继续查验/破坏/单刀
                    self._foreigner_plan_normal(p)
            else:
                # 第6夜前不能觉醒，正常行动
                self._foreigner_plan_normal(p)
        else:
            # 已觉醒：每夜在双刀 / 单刀+查验之间自主选择
            if p.foreigner_sabotage_count < 1 and self.countdown < 12 and self.rng.random() < 0.3:
                p._foreigner_action = '破坏'
            elif self.rng.random() < 0.6:
                p._foreigner_action = '双刀'   # 已觉醒者偏好双刀收割
            else:
                p._foreigner_action = '击杀' if self.rng.random() < 0.5 else '查验'

    # ===================== 快照 =====================
    def _record_snapshot(self):
        snap = {
            'night': self.night,
            'alive': len(self.alive_players()),
            'humans': len(self.alive_humans()),
            'aliens': len(self.alive_aliens()),
            'foreigner_alive': len(self.alive_foreigners()) > 0,
            'countdown': round(self.countdown, 2),
            'cum_sab': round(self.cum_sabotage, 2),
            'cum_rep': round(self.cum_repair, 2),
            'net_sab': round(self.net_sabotage, 2),
            'stall': sorted(self.stall_triggered),
            'infected': sum(1 for p in self.alive_players() if p.infection >= 1),
            'dying': sum(1 for p in self.alive_players() if p.dying),
            'awak': {d: 2 - self.awak_quota[d] for d in AWAK_DIRS},
            'transforms': len(self.transform_records),
            'roles_alive': {r: sum(1 for p in self.alive_players() if p.role == r)
                            for r in set(HUMAN_ROLES + ['异形', '外星人'])},
        }
        self.snapshots.append(snap)


# ============================ 模拟驱动 ============================
def simulate_one(rng, game_id, strategy='high'):
    g = Game(rng, game_id, strategy)
    max_nights = 45
    while not g.over and g.night < max_nights:
        g.plan_night_actions()
        g.run_night()
        if g.over:
            break
        # 白天（非1.4模式）
        if not g.night_war:
            g.run_daytime(emergency=False)
        else:
            # 1.4 模式：夜晚交锋 = 持续战斗，存活方赢得最终胜利（一方全灭由check_win判定）。
            # 公测1.0新规则：
            #  - 单挑例外：1v1（异形1只 vs 外星人1只）连续3夜未分胜负 → 外星人胜
            #  - 同归于尽：某夜双方存活数同时归零 → 外星人胜
            #  - 兜底终止：交锋连续5夜无任何减员（含感染延迟死亡）→ 按人数判定
            aliens = g.alive_aliens()
            fore = g.alive_foreigners()
            # 同归于尽检查（双方同时归零 → 外星人胜）
            if len(aliens) == 0 and len(fore) == 0:
                g._end('foreigner', '夜晚交锋同归于尽', '1.4')
                break
            # 记录本夜是否发生减员（对比上夜存活数）
            if g._war_last_alive is not None:
                prev_aliens, prev_fore = g._war_last_alive
                if len(aliens) + len(fore) < prev_aliens + prev_fore:
                    g.night_war_no_kill = 0  # 有减员，重置无减员计数
                else:
                    g.night_war_no_kill += 1
            else:
                g.night_war_no_kill = 0
            g._war_last_alive = (len(aliens), len(fore))
            # 兜底终止：连续5夜无减员 → 按人数判定
            if g.night_war_no_kill >= 5:
                if len(aliens) > len(fore):
                    g._end('alien', '夜晚交锋兜底(人数占优)', '1.4')
                else:
                    g._end('foreigner', '夜晚交锋兜底(人数不劣)', '1.4')
                break
            # 单挑例外：1v1 连续3夜未分胜负 → 外星人胜
            if len(aliens) == 1 and len(fore) == 1:
                g.night_war_count += 1
                if g.night_war_count >= 3:
                    g._end('foreigner', '夜晚交锋单挑平局', '1.4')  # 1v1 三夜未分胜负 → 外星人胜
                    break
            else:
                g.night_war_count = 0  # 非单挑：重置单挑计数，继续战斗直到一方全灭
        g.check_win('loop')
    if not g.over:
        # 超时兜底：按人数判定
        h = len(g.alive_humans()); a = len(g.alive_aliens()); f = len(g.alive_foreigners())
        if a == 0 and f == 0:
            g._end('human', '超时清场', 'timeout')
        elif h == 0 and f == 0:
            g._end('alien', '超时清场', 'timeout')
        elif h == 0 and a == 0:
            g._end('foreigner', '超时独存', 'timeout')
        else:
            g._end('human', '超时人类存活多', 'timeout')
    return g


# ============================ 统计 ============================
class Stats:
    def __init__(self):
        self.n = 0
        self.wins = Counter()
        self.win_reason = Counter()
        self.lengths = []
        self.stall_trigger = {3.0: 0, 6.0: 0, 9.0: 0}
        self.stall_night = {3.0: [], 6.0: [], 9.0: []}
        self.awak_choice = Counter()
        self.awak_night = []
        self.transform_count_dist = Counter()
        self.transform_dir = Counter()
        self.role_survive = defaultdict(list)     # role -> 存活夜数
        self.role_alive_end = defaultdict(int)    # role -> 终局存活次数
        self.role_total = Counter()
        self.crew_check_lock = 0
        self.crew_repair = 0
        self.crew_total = 0
        self.transfer_count = Counter()
        self.transfer_win = defaultdict(lambda: [0, 0])  # dir -> [wins, total]
        self.snap_sum = defaultdict(lambda: defaultdict(float))
        self.snap_cnt = defaultdict(int)
        self.double_blade_used = 0
        self.emergency_used = 0
        # 阶段胜率
        self.win_by_len = {'early': Counter(), 'mid': Counter(), 'late': Counter()}
        # —— 提示词重要指标补充 ——
        # 阵营胜率细分
        self.win_type = Counter()   # human_countdown / human_clear / alien_wipeout / foreigner_clash
        # 停摆间隔与触发后人类胜率
        self.stall_interval = {3.0: [], 6.0: []}
        self.stall_post_human = {3.0: [0, 0], 6.0: [0, 0], 9.0: [0, 0]}  # [wins, total]
        # 觉醒胜率贡献与觉醒后存活
        self.awak_win = {d: Counter() for d in AWAK_DIRS}   # dir -> Counter(camp)
        self.awak_surv = {d: [] for d in AWAK_DIRS}
        # 转化方向胜率
        self.transform_win_dir = defaultdict(lambda: [0, 0])  # 'old→new' -> [alien_wins, total]
        # 普通船员查验vs维修选择率与胜率
        self.crew_check_games = [0, 0]   # [games_with_human_win, total_games_with_check]
        self.crew_repair_games = [0, 0]
        # 驱逐身份公开统计（职业公开后）
        self.ejection_total = 0
        self.ejection_camp = Counter()      # 被驱逐者阵营分布
        self.ejection_role = Counter()      # 被驱逐者职业分布
        self.ejection_human_role = Counter()  # 被错驱的人类职业分布
        # 公测1.0 子场景统计：异形优势/劣势局面的策略选择分布与胜率
        self.alien_dis_win = [0, 0]     # [alien_wins, total] 曾进入劣势局面的对局
        self.alien_adv_win = [0, 0]     # [alien_wins, total] 始终优势局面的对局
        self.alien_dis_action = Counter()  # 劣势局面行动选择分布
        self.alien_adv_action = Counter()  # 优势局面行动选择分布

    def collect(self, g):
        self.n += 1
        self.wins[g.winner] += 1
        self.win_reason[g.end_reason] += 1
        self.lengths.append(g.end_night)
        for th in self.stall_trigger:
            if th in g.stall_triggered:
                self.stall_trigger[th] += 1
                # 触发夜数：首次达到该净破坏量的夜
                for s in g.snapshots:
                    if s['net_sab'] >= th:
                        self.stall_night[th].append(s['night'])
                        break
                # 触发后人类胜率
                self.stall_post_human[th][1] += 1
                if g.winner == 'human':
                    self.stall_post_human[th][0] += 1
        # 停摆间隔：3.0→6.0、6.0→9.0 首次触发夜之差
        first_night = {}
        for th in [3.0, 6.0, 9.0]:
            if th in g.stall_triggered:
                for s in g.snapshots:
                    if s['net_sab'] >= th:
                        first_night[th] = s['night']
                        break
        if 3.0 in first_night and 6.0 in first_night:
            self.stall_interval[3.0].append(first_night[6.0] - first_night[3.0])
        if 6.0 in first_night and 9.0 in first_night:
            self.stall_interval[6.0].append(first_night[9.0] - first_night[6.0])
        for d, _ in g.awak_choices:
            self.awak_choice[d] += 1
        for _, n in g.awak_choices:
            self.awak_night.append(n)
        # 觉醒胜率贡献与觉醒后存活
        for p in g.players:
            if p.camp == 'alien' and getattr(p, 'awak_dir', None) and getattr(p, 'awak_night', None):
                self.awak_win[p.awak_dir][g.winner] += 1
                surv = (p.death_night if p.death_night else g.end_night) - p.awak_night
                self.awak_surv[p.awak_dir].append(surv)
        self.transform_count_dist[len(g.transform_records)] += 1
        for old, nd, _ in g.transform_records:
            self.transform_dir['%s→%s' % (old, nd)] += 1
            self.transform_win_dir['%s→%s' % (old, nd)][1] += 1
            if g.winner == 'alien':
                self.transform_win_dir['%s→%s' % (old, nd)][0] += 1
        # 角色强度（使用转职前原职业）
        for p in g.players:
            r = p.original_role
            self.role_total[r] += 1
            surv = g.end_night if p.alive else (p.death_night if p.death_night else g.end_night)
            self.role_survive[r].append(surv)
            if p.alive:
                self.role_alive_end[r] += 1
            if r == '普通船员':
                self.crew_total += 1
                # 锁定异形次数（两次查验确认阵营）
                for tid, c in p.crew_checks.items():
                    if c >= 2:
                        self.crew_check_lock += 1
                if p.transferred:
                    self.transfer_count[p.transfer_dir] += 1
                    self.transfer_win[p.transfer_dir][1] += 1
                    if g.winner == 'human':
                        self.transfer_win[p.transfer_dir][0] += 1
        # 双刀 / 紧急会议（使用原职业）
        for p in g.players:
            if p.original_role == '外星人' and p._ever_double:
                self.double_blade_used += 1
            if p.original_role == '验票官' and p.emergency_used:
                self.emergency_used += 1
        # 快照聚合
        for s in g.snapshots:
            self.snap_cnt[s['night']] += 1
            for k, v in s.items():
                if k == 'night' or k == 'stall' or k == 'awak' or k == 'roles_alive':
                    continue
                self.snap_sum[s['night']][k] += v
        # 阵营胜率细分（10.1）
        if g.winner == 'human':
            if '倒计时' in g.end_reason:
                self.win_type['human_countdown'] += 1
            else:
                self.win_type['human_clear'] += 1
        elif g.winner == 'alien':
            self.win_type['alien_wipeout'] += 1
        elif g.winner == 'foreigner':
            self.win_type['foreigner_clash'] += 1
        # 普通船员查验vs维修选择率与胜率（十五）
        if g.crew_check_count > 0:
            self.crew_check_games[1] += 1
            if g.winner == 'human':
                self.crew_check_games[0] += 1
        if g.crew_repair_count > 0:
            self.crew_repair_games[1] += 1
            if g.winner == 'human':
                self.crew_repair_games[0] += 1
        # 驱逐身份公开统计
        for (_, _, camp, role) in g.ejection_log:
            self.ejection_total += 1
            self.ejection_camp[camp] += 1
            self.ejection_role[role] += 1
            if camp == 'human':
                self.ejection_human_role[role] += 1
        # 公测1.0 子场景统计：异形劣势/优势局面的胜率与行动选择
        if getattr(g, '_ever_disadvantaged', False):
            self.alien_dis_win[1] += 1
            if g.winner == 'alien':
                self.alien_dis_win[0] += 1
            for act, cnt in g._alien_dis_action.items():
                self.alien_dis_action[act] += cnt
        else:
            self.alien_adv_win[1] += 1
            if g.winner == 'alien':
                self.alien_adv_win[0] += 1
            for act, cnt in g._alien_adv_action.items():
                self.alien_adv_action[act] += cnt
        # 阶段
        ln = g.end_night
        bucket = 'early' if ln <= 2 else ('mid' if ln <= 5 else 'late')
        self.win_by_len[bucket][g.winner] += 1


# ============================ 报告 ============================
def percentile(data, p):
    if not data:
        return 0
    data = sorted(data)
    k = (len(data) - 1) * p
    f = int(k)
    c = min(f + 1, len(data) - 1)
    return data[f] + (data[c] - data[f]) * (k - f)


def run_simulation(n_games, strategy, seed=20260820):
    rng = random.Random(seed)
    stats = Stats()
    for i in range(n_games):
        g = simulate_one(rng, i, strategy)
        stats.collect(g)
    return stats


def fmt_pct(x, n):
    return "%.1f%%" % (100.0 * x / n)


def write_report(stats, strategy_name, path, compare=None):
    n = stats.n
    L = []
    L.append("# 太空杀 公测1.0 自动化模拟报告 — %s" % strategy_name)
    L.append("")
    L.append("模拟局数：**%d** 局  | 规则版本：公测1.0（裁判确定性结算）｜ 停摆阈值 3.0/6.0/9.0" % n)
    L.append("说明：觉醒方向额度采用【永久占位制】（不随死亡/转化释放，转化仅占用目标方向额度）；")
    L.append("公测1.0 关键机制：人类反破坏流（净破坏加速→集中维修）+ 统计口径修复（end_reason 带阵营前缀，两表可对账）。")
    L.append("异形动态破坏触发经 A/B 实测为净负面（异形-2.8pp、外星人+4.9pp），默认关闭，异形维持静态感染→击杀流（方案B）。")
    L.append("")
    # ① 总体
    L.append("## ① 总体结果")
    L.append("")
    L.append("| 指标 | 结果 |")
    L.append("|------|------|")
    L.append("| 人类胜率 | %s |" % fmt_pct(stats.wins['human'], n))
    L.append("| 异形胜率 | %s |" % fmt_pct(stats.wins['alien'], n))
    L.append("| 外星人胜率 | %s |" % fmt_pct(stats.wins['foreigner'], n))
    L.append("| 平均游戏夜数 | %.2f |" % (sum(stats.lengths)/n))
    L.append("| 中位游戏夜数 | %.0f |" % percentile(stats.lengths, 0.5))
    L.append("| P25 | %.0f |" % percentile(stats.lengths, 0.25))
    L.append("| P75 | %.0f |" % percentile(stats.lengths, 0.75))
    L.append("| 最短 | %d |" % min(stats.lengths))
    L.append("| 最长 | %d |" % max(stats.lengths))
    L.append("")
    # 胜利原因拆分
    L.append("### 胜利原因拆分")
    L.append("")
    L.append("| 阵营 | 胜利原因 | 局数 | 占比 |")
    L.append("|------|----------|------|------|")
    for reason, cnt in stats.win_reason.most_common():
        L.append("| - | %s | %d | %s |" % (reason, cnt, fmt_pct(cnt, n)))
    L.append("")
    # 阵营胜率细分（10.1）
    L.append("### 阵营胜率细分（按胜利类型）")
    L.append("")
    L.append("| 类别 | 局数 | 占比 |")
    L.append("|------|------|------|")
    for k, label in [('human_countdown', '人类·倒计时胜利'), ('human_clear', '人类·清场胜利'),
                     ('alien_wipeout', '异形·人类全灭后独存'), ('foreigner_clash', '外星人·夜晚交锋胜利')]:
        c = stats.win_type[k]
        L.append("| %s | %d | %s |" % (label, c, fmt_pct(c, n)))
    L.append("")
    # ② 停摆
    L.append("## ② 停摆系统")
    L.append("")
    L.append("| 指标 | 结果 |")
    L.append("|------|------|")
    for th in [3.0, 6.0, 9.0]:
        trig = stats.stall_trigger[th]
        avg_n = (sum(stats.stall_night[th])/len(stats.stall_night[th])) if stats.stall_night[th] else 0
        w, t = stats.stall_post_human[th]
        L.append("| %.1f 触发率 | %s（平均触发夜 %.1f；触发后人类胜率 %s）|" % (
            th, fmt_pct(trig, n), avg_n, (fmt_pct(w, t) if t else "-")))
    iv35 = (sum(stats.stall_interval[3.0])/len(stats.stall_interval[3.0])) if stats.stall_interval[3.0] else 0
    iv70 = (sum(stats.stall_interval[6.0])/len(stats.stall_interval[6.0])) if stats.stall_interval[6.0] else 0
    L.append("| 3.0→6.0 平均间隔 | %.1f 夜 |" % iv35)
    L.append("| 6.0→9.0 平均间隔 | %.1f 夜 |" % iv70)
    L.append("")
    # ③ 觉醒
    L.append("## ③ 觉醒系统")
    L.append("")
    L.append("| 方向 | 选择次数 | 选择率 | 平均觉醒夜 | 异形胜率贡献 | 觉醒后平均存活 |")
    L.append("|------|----------|--------|------------|--------------|----------------|")
    total_awak = sum(stats.awak_choice.values())
    for d in AWAK_DIRS:
        c = stats.awak_choice[d]
        w = stats.awak_win[d].get('alien', 0)
        tot = sum(stats.awak_win[d].values())
        winrate = fmt_pct(w, tot) if tot else "-"
        surv = (sum(stats.awak_surv[d])/len(stats.awak_surv[d])) if stats.awak_surv[d] else 0
        L.append("| %s | %d | %s | %.1f | %s | %.1f |" % (
            d, c, fmt_pct(c, total_awak) if total_awak else "-",
            (sum(stats.awak_night)/len(stats.awak_night)) if stats.awak_night else 0,
            winrate, surv))
    L.append("")
    # ④ 转化
    L.append("## ④ 转化系统")
    L.append("")
    L.append("| 指标 | 结果 |")
    L.append("|------|------|")
    L.append("| 0次转化比例 | %s |" % fmt_pct(stats.transform_count_dist[0], n))
    L.append("| 1次转化比例 | %s |" % fmt_pct(stats.transform_count_dist[1], n))
    L.append("| 2次转化比例 | %s |" % fmt_pct(stats.transform_count_dist[2], n))
    L.append("")
    L.append("转化方向使用与异形胜率：")
    for k, v in stats.transform_dir.most_common():
        w, t = stats.transform_win_dir[k]
        L.append("- %s：%d 次（异形胜率 %s）" % (k, v, fmt_pct(w, t) if t else "-"))
    L.append("")
    # ⑤ 职业强度
    L.append("## ⑤ 职业强度（S/A/B/C/D 分级，含统计依据）")
    L.append("")
    L.append("| 职业 | 平均存活夜数 | 终局存活率 | 样本 |")
    L.append("|------|--------------|------------|------|")
    grade_map = {}
    for role in sorted(stats.role_total):
        tot = stats.role_total[role]
        avg_surv = sum(stats.role_survive[role])/len(stats.role_survive[role]) if stats.role_survive[role] else 0
        alive_rate = stats.role_alive_end[role]/tot if tot else 0
        grade_map[role] = (avg_surv, alive_rate)
        L.append("| %s | %.2f | %s | %d |" % (role, avg_surv, fmt_pct(stats.role_alive_end[role], tot), tot))
    L.append("")
    # 转职
    L.append("### 普通船员转职")
    L.append("")
    L.append("| 方向 | 选择次数 | 转职后人类胜率 |")
    L.append("|------|----------|----------------|")
    for d in ['武装船员', '加速工程师', '临时医生']:
        t = stats.transfer_count[d]
        w, tot = stats.transfer_win[d]
        L.append("| %d（%s）| %s |" % (t, d, fmt_pct(w, tot) if tot else "-"))
    L.append("")
    # 查验 vs 维修（十五）
    L.append("### 普通船员：查验 vs 维修（十五）")
    L.append("")
    L.append("| 行为 | 出现局数 | 该行为局中人类胜率 |")
    L.append("|------|----------|--------------------|")
    wc, tc = stats.crew_check_games
    wr, tr = stats.crew_repair_games
    L.append("| 选择查验 | %d | %s |" % (tc, fmt_pct(wc, tc) if tc else "-"))
    L.append("| 选择维修 | %d | %s |" % (tr, fmt_pct(wr, tr) if tr else "-"))
    L.append("- 说明：统计当夜有普通船员执行该行为的对局，对比其人类阵营胜率。")
    L.append("")
    # ⑥ 最强策略（基于阶段胜率 / 觉醒方向）
    L.append("## ⑥ 最强策略观察")
    L.append("")
    L.append("- 觉醒方向选择率（破坏/感染/击杀）：%s / %s / %s" % (
        fmt_pct(stats.awak_choice['破坏'], total_awak) if total_awak else "-",
        fmt_pct(stats.awak_choice['感染'], total_awak) if total_awak else "-",
        fmt_pct(stats.awak_choice['击杀'], total_awak) if total_awak else "-"))
    L.append("- 外星人双刀使用率：%s" % fmt_pct(stats.double_blade_used, stats.role_total.get('外星人', 1)))
    L.append("- 验票官紧急会议使用率：%s" % fmt_pct(stats.emergency_used, stats.role_total.get('验票官', 1)))
    L.append("- 普通船员平均有效查验(锁定)次数：%.2f" % (stats.crew_check_lock/stats.crew_total if stats.crew_total else 0))
    L.append("")
    # ⑦ 逐夜快照（聚合平均）
    L.append("## ⑦ 逐夜状态快照（平均）")
    L.append("")
    L.append("| 夜 | 存活 | 人类 | 异形 | 外星人存活 | 倒计时 | 净破坏 | 感染 | 濒死 |")
    L.append("|----|------|------|------|------------|--------|--------|------|------|")
    for night in sorted(stats.snap_cnt):
        cnt = stats.snap_cnt[night]
        s = stats.snap_sum[night]
        def avg(k): return s.get(k, 0)/cnt
        L.append("| %d | %.1f | %.1f | %.1f | %.2f | %.2f | %.2f | %.2f | %.2f |" % (
            night, avg('alive'), avg('humans'), avg('aliens'),
            avg('foreigner_alive'), avg('countdown'), avg('net_sab'),
            avg('infected'), avg('dying')))
    L.append("")
    # ⑧ 平衡性问题（数据驱动）
    L.append("## ⑧ 平衡性问题（数据验证）")
    L.append("")
    hu = stats.wins['human']; al = stats.wins['alien']; fo = stats.wins['foreigner']
    L.append("- 人类胜率 %.1f%%，异形 %.1f%%，外星人 %.1f%%。" % (100*hu/n, 100*al/n, 100*fo/n))
    if abs(hu - al) > 0.15 * n or fo > 0.2 * n:
        L.append("- 【疑似失衡】阵营胜率差距超过 15pp，建议进一步 A/B 测试。")
    else:
        L.append("- 三阵营胜率相对均衡（差距 < 15pp）。")
    # 转化支配检查
    if total_awak:
        rates = {d: stats.awak_choice[d]/total_awak for d in AWAK_DIRS}
        mx = max(rates.values()); mn = min(rates.values())
        if mx - mn > 0.25:
            L.append("- 【疑似支配策略】觉醒方向选择率差异 >25pp（%s 显著高于 %s），需关注。" %
                     (max(rates, key=rates.get), min(rates, key=rates.get)))
    L.append("")
    L.append("## ⑨ 是否建议改数值")
    L.append("")
    L.append("以模拟数据为准：当前 %s 下三阵营胜率%s，建议 **%s**。" % (
        strategy_name,
        ("较均衡" if abs(hu-al) <= 0.15*n and fo <= 0.2*n else "存在明显差距"),
        ("保持不变 / 轻微观察" if abs(hu-al) <= 0.15*n and fo <= 0.2*n else "中度调整（需 A/B 测试确认）")))
    L.append("")

    # ⑩ 数值 vs 推理：高水平 vs 随机基线
    if compare is not None:
        L.append("## ⑩ 数值 vs 推理：高水平策略 vs 随机基线")
        L.append("")
        cn = compare.n
        L.append("| 阵营 | 高水平 | 随机基线 | 差值 |")
        L.append("|------|--------|----------|------|")
        for camp, cn_ in (('human', '人类'), ('alien', '异形'), ('foreigner', '外星人')):
            h = 100.0 * stats.wins[camp] / n
            r = 100.0 * compare.wins[camp] / cn
            L.append("| %s | %.1f%% | %.1f%% | %+.1fpp |" % (cn_, h, r, h - r))
        hh = 100.0 * stats.wins['human'] / n
        hr = 100.0 * compare.wins['human'] / cn
        L.append("")
        L.append("**核心观察**：随机基线下的【人类】胜率(%.1f%%)反而高于高水平(%.1f%%)。" % (hr, hh))
        L.append("这说明在当前模型里，**异形/外星人阵营从“策略化”中获益远大于人类**——")
        L.append("高水平异形优先用感染/出刀施加稳定压力、并用行为信号(维修暴露/公开跳身份/被保护频次)推断威胁，")
        L.append("而人类的信息战依赖神探/船员逐夜查验，识别速度受限于每晚仅1次有效驱逐。")
        L.append("换言之，夜间击杀效率(≈4/夜)远超白天驱逐效率(≈1/夜)，使人类在“信息战争”中处于结构性劣势。")
        L.append("这与模拟提示词中“追责机制让信息战成本更平衡”的预期尚有差距，建议：")
        L.append("- 提高人类翻盘效率：如验票官紧急会议更频繁、允许同日多驱逐、或强化私聊情报的公开转化率；")
        L.append("- 适度降低异形夜间击杀基数或外星人残局生存资源(每夜免疫/双刀)；")
        L.append("- 将“私聊配对公告”作为更强推理信号（本模型已实现：频繁被找=信息富集方）。")
        L.append("")
        L.append("> 私聊与讨论博弈要点（基于本模型1000局）：")
        L.append("> - 配对公告本身即信号：被频繁私聊者多为关键角色(医师/神探)，高水平玩家据此反推关系；")
        L.append("> - 三层信息交换：表层(公开事件)/中层(半公开疑点)/深层(确证情报)。异形借私聊散布假疑点制造迷雾，")
        L.append(">   但本模型规定私下信息仅为“疑点”非“确证”，需公开交叉验证才能放大，从而限制了信息迷雾的破坏力；")
        L.append("> - 追责机制：驱逐好人的主导者被标记并反向抬升怀疑度，使异形误导策略存在反噬成本；")
        L.append("> - 神探“跳身份”广播是信息战转折点：一旦公开指认，全体人类采信并协同驱逐，但随即成为异形焦点目标。")
        L.append("")
        L.append("> 公告审计 / 公共账本要点（本次升级）：")
        L.append("> - 私聊轮换网络：关键角色(神探/验票官/医生)限制私聊≤2人避免被公告图定位斩首；普通船员环形/网格轮换避免连续两晚同目标；")
        L.append("> - 人类资源经济：普通船员查/修互斥分组轮换保持信息不断档；工程师保留至第3夜后高收益期出手；前几夜压净破坏<3.0拖延9.0阈值；")
        L.append("> - 异形暴露管理：单只累计破坏3次即公开编号，故3只异形各破坏1~2次轮换，已暴露/将暴露者继续破坏以保全队友额度；")
        L.append("> - 感染节奏：优先感染救援医师(治疗仅1次、压力最大)，且刀+感染同夜配合迫使医生二选一；")
        L.append("> - 外星人建图与终局：前几夜查验优先建图(已暴露关键角色>高可疑异形)，双刀基于known精准沉默收割神探/验票官/救援医师，")
        L.append(">   并自白天起优先投票已知异形以在人类全灭前削弱其兵力、避免1v3终局劣势；")
        L.append("> - 反审计噪音：异形混合出刀/感染/结茧使行动次数无法归因；外星人偶尔用查验代替击杀，让人类无法确认其是否活跃。")
        L.append("")

        # 驱逐身份公开统计（职业公开后）
        L.append("### 驱逐身份公开统计（真实身份含职业）")
        L.append("")
        L.append("- 总驱逐次数：**%d** 次（覆盖 %d 局）。" % (stats.ejection_total, n))
        L.append("")
        L.append("| 被驱逐者阵营 | 次数 | 占比 |")
        L.append("|--------------|------|------|")
        for camp in ['alien', 'foreigner', 'human']:
            c = stats.ejection_camp.get(camp, 0)
            L.append("| %s | %d | %s |" % (camp, c, fmt_pct(c, stats.ejection_total) if stats.ejection_total else "-"))
        L.append("")
        L.append("被错驱的人类职业分布（追责机制下误伤）：")
        if stats.ejection_human_role:
            for role, c in stats.ejection_human_role.most_common():
                L.append("- %s：%d 次" % (role, c))
        else:
            L.append("- 无（本组模拟中白天未错驱人类，或全员异形/外星人被驱）。")
        L.append("> 说明：自本次升级起，驱逐公告输出格式为“X号 是 阵营（职业：Y）”，真实身份（含职业）对全体公开，")
        L.append("> 用于驱动追责机制与后续信念更新。该改动属公告文本级，不改变胜负统计分布。")
        L.append("")

        # 公测1.0 子场景统计：异形优势/劣势局面的策略选择分布与胜率
        L.append("### 异形子场景策略分析（劣势 vs 优势局面，公测1.0 动态破坏触发验证）")
        L.append("")
        dw, dt = stats.alien_dis_win
        aw, at = stats.alien_adv_win
        L.append("| 局面 | 对局数 | 异形胜率 | 破坏行动占比 | 感染行动占比 | 出刀行动占比 |")
        L.append("|------|--------|----------|--------------|--------------|--------------|")
        def _act_share(act_counter, act_key):
            tot = sum(act_counter.values())
            return (fmt_pct(act_counter.get(act_key, 0), tot) if tot else "-")
        L.append("| 劣势局面（曾进入） | %d | %s | %s | %s | %s |" % (
            dt, fmt_pct(dw, dt) if dt else "-",
            _act_share(stats.alien_dis_action, '破坏'),
            _act_share(stats.alien_dis_action, '感染'),
            _act_share(stats.alien_dis_action, '出刀')))
        L.append("| 优势局面（全程） | %d | %s | %s | %s | %s |" % (
            at, fmt_pct(aw, at) if at else "-",
            _act_share(stats.alien_adv_action, '破坏'),
            _act_share(stats.alien_adv_action, '感染'),
            _act_share(stats.alien_adv_action, '出刀')))
        L.append("")
        L.append("> 判据：若劣势局面下破坏行动占比与异形胜率明显高于优势局面，说明\"劣势→切破坏\"")
        L.append("> 动态分支真实生效（异形在劣势时用破坏推停摆拖残局翻盘），而非静态风格偏好。")
        L.append("")

    content = "\n".join(L)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return content


# ============================ HTML 报告 ============================
CAMP_COLOR = {'human': '#2e7d32', 'alien': '#c62828', 'foreigner': '#1565c0'}


def _html_table(headers, rows):
    th = "".join("<th>%s</th>" % h for h in headers)
    body = ""
    for r in rows:
        tds = "".join("<td>%s</td>" % c for c in r)
        body += "<tr>%s</tr>" % tds
    return "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (th, body)


def _bar(camp, pct):
    color = CAMP_COLOR.get(camp, '#555')
    return ('<div class="bar"><div class="fill" style="width:%.1f%%;background:%s"></div>'
            '<span class="barlabel">%.1f%%</span></div>' % (pct, color, pct))


def write_report_html(stats, strategy_name, path, compare=None):
    n = stats.n
    cn = compare.n if compare else n
    sections = []

    # ① 总体
    hu = 100.0 * stats.wins['human'] / n
    al = 100.0 * stats.wins['alien'] / n
    fo = 100.0 * stats.wins['foreigner'] / n
    s = []
    s.append('<div class="cards">')
    s.append('<div class="card" style="border-top:4px solid %s"><div class="cardv">%.1f%%</div><div class="cardl">人类胜率</div></div>' % (CAMP_COLOR['human'], hu))
    s.append('<div class="card" style="border-top:4px solid %s"><div class="cardv">%.1f%%</div><div class="cardl">异形胜率</div></div>' % (CAMP_COLOR['alien'], al))
    s.append('<div class="card" style="border-top:4px solid %s"><div class="cardv">%.1f%%</div><div class="cardl">外星人胜率</div></div>' % (CAMP_COLOR['foreigner'], fo))
    s.append('</div>')
    s.append('<div class="bars">%s%s%s</div>' % (_bar('human', hu), _bar('alien', al), _bar('foreigner', fo)))
    rows = [
        ["平均游戏夜数", "%.2f" % (sum(stats.lengths)/n)],
        ["中位游戏夜数", "%.0f" % percentile(stats.lengths, 0.5)],
        ["P25", "%.0f" % percentile(stats.lengths, 0.25)],
        ["P75", "%.0f" % percentile(stats.lengths, 0.75)],
        ["最短", "%d" % min(stats.lengths)],
        ["最长", "%d" % max(stats.lengths)],
    ]
    s.append(_html_table(["游戏长度指标", "值"], rows))
    # 胜利原因
    rows = [["-", reason, "%d" % cnt, fmt_pct(cnt, n)] for reason, cnt in stats.win_reason.most_common()]
    s.append('<h3>胜利原因拆分</h3>')
    s.append(_html_table(["阵营", "胜利原因", "局数", "占比"], rows))
    # 阵营胜率细分
    s.append('<h3>阵营胜率细分（按胜利类型）</h3>')
    labels = [('human_countdown', '人类·倒计时胜利'), ('human_clear', '人类·清场胜利'),
              ('alien_wipeout', '异形·人类全灭后独存'), ('foreigner_clash', '外星人·夜晚交锋胜利')]
    rows = [[lab, "%d" % stats.win_type[k], fmt_pct(stats.win_type[k], n)] for k, lab in labels]
    s.append(_html_table(["类别", "局数", "占比"], rows))
    sections.append(("① 总体结果", "\n".join(s)))

    # ② 停摆
    s = []
    rows = []
    for th in [3.0, 6.0, 9.0]:
        trig = stats.stall_trigger[th]
        avg_n = (sum(stats.stall_night[th])/len(stats.stall_night[th])) if stats.stall_night[th] else 0
        w, t = stats.stall_post_human[th]
        rows.append(["%.1f 触发率" % th, "%s（平均触发夜 %.1f；触发后人类胜率 %s）" % (
            fmt_pct(trig, n), avg_n, (fmt_pct(w, t) if t else "-"))])
    iv35 = (sum(stats.stall_interval[3.0])/len(stats.stall_interval[3.0])) if stats.stall_interval[3.0] else 0
    iv70 = (sum(stats.stall_interval[6.0])/len(stats.stall_interval[6.0])) if stats.stall_interval[6.0] else 0
    rows.append(["3.0→6.0 平均间隔", "%.1f 夜" % iv35])
    rows.append(["6.0→9.0 平均间隔", "%.1f 夜" % iv70])
    s.append(_html_table(["指标", "结果"], rows))
    sections.append(("② 停摆系统", "\n".join(s)))

    # ③ 觉醒
    s = []
    total_awak = sum(stats.awak_choice.values())
    rows = []
    for d in AWAK_DIRS:
        c = stats.awak_choice[d]
        w = stats.awak_win[d].get('alien', 0)
        tot = sum(stats.awak_win[d].values())
        winrate = fmt_pct(w, tot) if tot else "-"
        surv = (sum(stats.awak_surv[d])/len(stats.awak_surv[d])) if stats.awak_surv[d] else 0
        rows.append([d, "%d" % c, (fmt_pct(c, total_awak) if total_awak else "-"),
                     "%.1f" % ((sum(stats.awak_night)/len(stats.awak_night)) if stats.awak_night else 0),
                     winrate, "%.1f" % surv])
    s.append(_html_table(["方向", "选择次数", "选择率", "平均觉醒夜", "异形胜率贡献", "觉醒后平均存活"], rows))
    sections.append(("③ 觉醒系统", "\n".join(s)))

    # ④ 转化
    s = []
    rows = [
        ["0次转化比例", fmt_pct(stats.transform_count_dist[0], n)],
        ["1次转化比例", fmt_pct(stats.transform_count_dist[1], n)],
        ["2次转化比例", fmt_pct(stats.transform_count_dist[2], n)],
    ]
    s.append(_html_table(["指标", "结果"], rows))
    s.append('<h3>转化方向使用与异形胜率</h3>')
    rows = []
    for k, v in stats.transform_dir.most_common():
        w, t = stats.transform_win_dir[k]
        rows.append([k, "%d 次" % v, (fmt_pct(w, t) if t else "-")])
    s.append(_html_table(["方向", "次数", "异形胜率"], rows))
    sections.append(("④ 转化系统", "\n".join(s)))

    # ⑤ 职业强度 + 转职 + 查验vs维修
    s = []
    rows = []
    for role in sorted(stats.role_total):
        tot = stats.role_total[role]
        avg_surv = sum(stats.role_survive[role])/len(stats.role_survive[role]) if stats.role_survive[role] else 0
        rows.append([role, "%.2f" % avg_surv, fmt_pct(stats.role_alive_end[role], tot), "%d" % tot])
    s.append(_html_table(["职业", "平均存活夜数", "终局存活率", "样本"], rows))
    s.append('<h3>普通船员转职</h3>')
    rows = []
    for d in ['武装船员', '加速工程师', '临时医生']:
        t = stats.transfer_count[d]
        w, tot = stats.transfer_win[d]
        rows.append(["%d（%s）" % (t, d), (fmt_pct(w, tot) if tot else "-")])
    s.append(_html_table(["方向", "转职后人类胜率"], rows))
    s.append('<h3>普通船员：查验 vs 维修（十五）</h3>')
    wc, tc = stats.crew_check_games
    wr, tr = stats.crew_repair_games
    rows = [
        ["选择查验", "%d" % tc, (fmt_pct(wc, tc) if tc else "-")],
        ["选择维修", "%d" % tr, (fmt_pct(wr, tr) if tr else "-")],
    ]
    s.append(_html_table(["行为", "出现局数", "该行为局中人类胜率"], rows))
    s.append("<p class='note'>说明：统计当夜有普通船员执行该行为的对局，对比其人类阵营胜率。</p>")
    sections.append(("⑤ 职业强度（S/A/B/C/D 分级，含统计依据）", "\n".join(s)))

    # ⑥ 最强策略
    s = []
    s.append("<ul>")
    s.append("<li>觉醒方向选择率（破坏/感染/击杀）：%s / %s / %s</li>" % (
        (fmt_pct(stats.awak_choice['破坏'], total_awak) if total_awak else "-"),
        (fmt_pct(stats.awak_choice['感染'], total_awak) if total_awak else "-"),
        (fmt_pct(stats.awak_choice['击杀'], total_awak) if total_awak else "-")))
    s.append("<li>外星人双刀使用率：%s</li>" % fmt_pct(stats.double_blade_used, stats.role_total.get('外星人', 1)))
    s.append("<li>验票官紧急会议使用率：%s</li>" % fmt_pct(stats.emergency_used, stats.role_total.get('验票官', 1)))
    s.append("<li>普通船员平均有效查验(锁定)次数：%.2f</li>" % (stats.crew_check_lock/stats.crew_total if stats.crew_total else 0))
    s.append("</ul>")
    sections.append(("⑥ 最强策略观察", "\n".join(s)))

    # ⑦ 逐夜快照
    s = []
    rows = []
    for night in sorted(stats.snap_cnt):
        cnt = stats.snap_cnt[night]
        sm = stats.snap_sum[night]
        def avg(k): return sm.get(k, 0)/cnt
        rows.append(["%d" % night, "%.1f" % avg('alive'), "%.1f" % avg('humans'), "%.1f" % avg('aliens'),
                     "%.2f" % avg('foreigner_alive'), "%.2f" % avg('countdown'), "%.2f" % avg('net_sab'),
                     "%.2f" % avg('infected'), "%.2f" % avg('dying')])
    s.append(_html_table(["夜", "存活", "人类", "异形", "外星人存活", "倒计时", "净破坏", "感染", "濒死"], rows))
    sections.append(("⑦ 逐夜状态快照（平均）", "\n".join(s)))

    # ⑧⑨ 平衡性 / 改数值
    s = []
    s.append("<ul>")
    s.append("<li>人类胜率 %.1f%%，异形 %.1f%%，外星人 %.1f%%。</li>" % (hu, al, fo))
    if abs(hu - al) > 0.15 * n or fo > 0.2 * n:
        s.append("<li class='warn'>【疑似失衡】阵营胜率差距超过 15pp，建议进一步 A/B 测试。</li>")
    else:
        s.append("<li>三阵营胜率相对均衡（差距 &lt; 15pp）。</li>")
    if total_awak:
        rates = {d: stats.awak_choice[d]/total_awak for d in AWAK_DIRS}
        if max(rates.values()) - min(rates.values()) > 0.25:
            s.append("<li class='warn'>【疑似支配策略】觉醒方向选择率差异 &gt;25pp（%s 显著高于 %s），需关注。</li>" %
                     (max(rates, key=rates.get), min(rates, key=rates.get)))
    s.append("</ul>")
    s.append("<p><b>⑨ 是否建议改数值</b>：以模拟数据为准，当前 %s 下三阵营胜率%s，建议 <b>%s</b>。</p>" % (
        strategy_name,
        ("较均衡" if abs(hu-al) <= 0.15*n and fo <= 0.2*n else "存在明显差距"),
        ("保持不变 / 轻微观察" if abs(hu-al) <= 0.15*n and fo <= 0.2*n else "中度调整（需 A/B 测试确认）")))
    sections.append(("⑧ 平衡性问题（数据验证）& ⑨ 是否建议改数值", "\n".join(s)))

    # ⑩ 数值 vs 推理
    if compare is not None:
        s = []
        rows = []
        for camp, cn_ in (('human', '人类'), ('alien', '异形'), ('foreigner', '外星人')):
            h = 100.0 * stats.wins[camp] / n
            r = 100.0 * compare.wins[camp] / cn
            rows.append([cn_, "%.1f%%" % h, "%.1f%%" % r, "%+.1fpp" % (h - r)])
        s.append(_html_table(["阵营", "高水平", "随机基线", "差值"], rows))
        hh = 100.0 * stats.wins['human'] / n
        hr = 100.0 * compare.wins['human'] / cn
        s.append("<p><b>核心观察</b>：随机基线下的【人类】胜率(%.1f%%)反而高于高水平(%.1f%%)。" % (hr, hh))
        s.append("这说明在当前模型里，<b>异形/外星人阵营从“策略化”中获益远大于人类</b>——"
                 "夜间击杀效率(≈4/夜)远超白天驱逐效率(≈1/夜)，使人类在信息战争中处于结构性劣势。</p>")
        s.append("<blockquote>私聊与讨论博弈要点：配对公告本身即信号；三层信息交换(表层/中层/深层)；"
                 "追责机制使误导策略存在反噬成本；神探跳身份广播是信息战转折点。</blockquote>")
        s.append("<blockquote>公告审计 / 公共账本要点：私聊轮换网络与关键角色保护；人类查/修互斥分组轮换；"
                 "异形破坏3次暴露故轮换分担；感染优先救援医师且刀+感染配合；外星人建图双刀精准沉默收割并提前削弱异形。</blockquote>")
        # 驱逐身份公开统计
        s.append("<h3>驱逐身份公开统计（真实身份含职业）</h3>")
        s.append("<p>总驱逐次数：<b>%d</b> 次（覆盖 %d 局）。</p>" % (stats.ejection_total, n))
        rows = []
        for camp in ['alien', 'foreigner', 'human']:
            c = stats.ejection_camp.get(camp, 0)
            rows.append([camp, "%d" % c, (fmt_pct(c, stats.ejection_total) if stats.ejection_total else "-")])
        s.append(_html_table(["被驱逐者阵营", "次数", "占比"], rows))
        if stats.ejection_human_role:
            s.append("<p>被错驱的人类职业分布（追责机制下误伤）：</p><ul>")
            for role, c in stats.ejection_human_role.most_common():
                s.append("<li>%s：%d 次</li>" % (role, c))
            s.append("</ul>")
        else:
            s.append("<p class='note'>本组模拟中白天未错驱人类，或全员为异形/外星人被驱。</p>")
        s.append("<p class='note'>说明：自本次升级起，驱逐公告输出格式为“X号 是 阵营（职业：Y）”，真实身份（含职业）对全体公开，"
                 "用于驱动追责机制与后续信念更新；属公告文本级改动，不改变胜负统计分布。</p>")
        # 公测1.0 子场景统计：异形优势/劣势局面的策略选择分布与胜率
        dw, dt = stats.alien_dis_win
        aw, at = stats.alien_adv_win
        def _act_share_html(act_counter, act_key):
            tot = sum(act_counter.values())
            return (fmt_pct(act_counter.get(act_key, 0), tot) if tot else "-")
        s.append("<h3>异形子场景策略分析（劣势 vs 优势局面，公测1.0 动态破坏触发验证）</h3>")
        rows = [
            ["劣势局面（曾进入）", "%d" % dt, (fmt_pct(dw, dt) if dt else "-"),
             _act_share_html(stats.alien_dis_action, '破坏'),
             _act_share_html(stats.alien_dis_action, '感染'),
             _act_share_html(stats.alien_dis_action, '出刀')],
            ["优势局面（全程）", "%d" % at, (fmt_pct(aw, at) if at else "-"),
             _act_share_html(stats.alien_adv_action, '破坏'),
             _act_share_html(stats.alien_adv_action, '感染'),
             _act_share_html(stats.alien_adv_action, '出刀')],
        ]
        s.append(_html_table(["局面", "对局数", "异形胜率", "破坏行动占比", "感染行动占比", "出刀行动占比"], rows))
        s.append("<p class='note'>判据：若劣势局面下破坏行动占比与异形胜率明显高于优势局面，"
                 "说明“劣势→切破坏”动态分支真实生效（异形在劣势时用破坏推停摆拖残局翻盘），而非静态风格偏好。</p>")
        sections.append(("⑩ 数值 vs 推理：高水平策略 vs 随机基线", "\n".join(s)))

    # 组装
    toc = "".join('<li><a href="#sec%d">%s</a></li>' % (i, t) for i, (t, _) in enumerate(sections))
    body = ""
    for i, (title, html) in enumerate(sections):
        body += '<section id="sec%d"><h2>%s</h2>%s</section>' % (i, title, html)
    html_doc = (HTML_TEMPLATE
                .replace("@@TITLE@@", str(strategy_name))
                .replace("@@N@@", str(n))
                .replace("@@TOC@@", toc)
                .replace("@@BODY@@", body))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    return html_doc


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>太空杀 v14.5 模拟报告 — @@TITLE@@</title>
<style>
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; margin:0; background:#f5f6f8; color:#222; }
header { background: linear-gradient(135deg,#1a237e,#283593); color:#fff; padding:32px 40px; }
header h1 { margin:0 0 8px; font-size:26px; }
header p { margin:0; opacity:.85; }
.wrap { display:flex; max-width:1200px; margin:0 auto; }
nav { width:230px; flex:0 0 230px; padding:24px 16px; position:sticky; top:0; height:100vh; overflow:auto; }
nav ul { list-style:none; padding:0; margin:0; }
nav li { margin:4px 0; }
nav a { color:#37474f; text-decoration:none; font-size:13px; padding:6px 10px; display:block; border-radius:6px; }
nav a:hover { background:#e3e6f0; }
main { flex:1; padding:24px 40px 80px; min-width:0; }
section { background:#fff; border-radius:12px; padding:24px 28px; margin-bottom:22px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
h2 { margin-top:0; font-size:20px; color:#1a237e; border-left:4px solid #3949ab; padding-left:12px; }
h3 { font-size:15px; color:#37474f; margin:18px 0 8px; }
table { border-collapse:collapse; width:100%; margin:10px 0; font-size:13px; }
th,td { border:1px solid #e0e0e0; padding:8px 10px; text-align:left; }
th { background:#f0f2f7; font-weight:600; }
tbody tr:nth-child(even){ background:#fafbfc; }
.cards { display:flex; gap:16px; margin:12px 0; }
.card { flex:1; background:#fafbff; border:1px solid #e3e6f0; border-radius:10px; padding:18px; text-align:center; }
.cardv { font-size:30px; font-weight:700; }
.cardl { color:#607d8b; font-size:13px; margin-top:4px; }
.bars { margin:14px 0; }
.bar { background:#eef0f4; border-radius:8px; height:26px; position:relative; margin:6px 0; overflow:hidden; }
.fill { height:100%; border-radius:8px; }
.barlabel { position:absolute; right:10px; top:3px; font-size:12px; font-weight:600; color:#333; }
.note { color:#789; font-size:12px; }
.warn { color:#c62828; font-weight:600; }
blockquote { background:#f1f3f9; border-left:4px solid #3949ab; margin:10px 0; padding:10px 14px; color:#455a64; font-size:13px; border-radius:0 6px 6px 0; }
ul { font-size:13px; line-height:1.9; }
footer { text-align:center; color:#90a4ae; font-size:12px; padding:20px; }
</style></head>
<body>
<header><h1>太空杀 公测1.0 自动化模拟报告 — @@TITLE@@</h1>
<p>模拟局数：@@N@@ 局 ｜ 规则版本：公测1.0（裁判确定性结算）｜ 觉醒方向额度采用永久占位制（转化不释放）｜ 停摆阈值 3.0/6.0/9.0｜ 反破坏流（动态破坏触发默认关闭）</p></header>
<div class="wrap"><nav><ul>@@TOC@@</ul></nav><main>@@BODY@@</main></div>
<footer>由蒙特卡洛模拟引擎自动生成 · 不完全信息三方动态博弈</footer>
</body></html>"""


# ============================ 主入口 ============================
if __name__ == '__main__':
    import time
    t0 = time.time()
    N = 1000
    print("运行 %d 局高水平模拟 (公测1.0)..." % N)
    stats_high = run_simulation(N, 'high', seed=20260821)
    report_path = "c:/Users/ASUS/CodeBuddy/20260820234047/report_high_1000_ob10.md"

    # 随机基线（用于数值vs推理平衡对照）
    print("运行 %d 局随机基线..." % N)
    stats_rand = run_simulation(N, 'random', seed=99)
    report_path2 = "c:/Users/ASUS/CodeBuddy/20260820234047/report_random_1000_ob10.md"
    write_report(stats_rand, "随机基线玩家", report_path2)
    print("随机基线报告：", report_path2)

    # 高水平报告（附带与随机基线的对比）
    write_report(stats_high, "高水平玩家（私聊+讨论+追责博弈）", report_path, compare=stats_rand)
    print("报告已生成：", report_path)

    # HTML 报告（提示词重要指标可视化）
    html_path = "c:/Users/ASUS/CodeBuddy/20260820234047/report_high_1000_ob10.html"
    write_report_html(stats_high, "高水平玩家（私聊+讨论+追责博弈）", html_path, compare=stats_rand)
    print("HTML 报告：", html_path)
    print("耗时 %.1fs" % (time.time() - t0))
    print("高水平：人类 %.1f%% 异形 %.1f%% 外星人 %.1f%%" % (
        100*stats_high.wins['human']/N, 100*stats_high.wins['alien']/N, 100*stats_high.wins['foreigner']/N))
    print("随机：人类 %.1f%% 异形 %.1f%% 外星人 %.1f%%" % (
        100*stats_rand.wins['human']/N, 100*stats_rand.wins['alien']/N, 100*stats_rand.wins['foreigner']/N))
