# -*- coding: utf-8 -*-
"""规则文本：生化不免疫 + 抑制封锁范围明确。"""
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = '../公测3.0/太空杀_公测3.0_规则.md'
s = io.open(f, encoding='utf-8').read()

pairs = [
    ('| 生化医师 | 治疗额度 **5 次（初始 2 + 第2/3/4 夜各 +1，公测3.1）**；治疗/救援清除感染并赋予抗体；自身免疫异形感染；濒死时只能自救（消耗救援额度） |',
     '| 生化医师 | 治疗额度 **5 次（初始 2 + 第2/3/4 夜各 +1，公测3.1）**；治疗/救援清除感染并赋予抗体；**自身不免疫感染（公测3.1 移除天生抗体）**；濒死时只能自救（消耗救援额度） |'),
    ('| 感染抑制 | 感染者自带的 1 次主动技能：使用后死亡夜延后 1 夜，但当夜失去全部主动行动能力（不进入沉默、不影响白天投票）。 |',
     '| 感染抑制 | 感染者自带的 1 次主动技能：使用后死亡夜延后 1 夜，但当夜失去**全部主动行动能力（含查验、巡逻、保护等所有夜间技能）**（不进入沉默、不影响白天投票）。 |'),
]
cnt = 0
for old, new in pairs:
    if old in s:
        s = s.replace(old, new, 1)
        cnt += 1
    else:
        print('NOT FOUND:', old[:50])
io.open(f, 'w', encoding='utf-8', newline='').write(s)
print('synced %d/%d' % (cnt, len(pairs)))
