# -*- coding: utf-8 -*-
"""补一条没同步上的感染抑制名词解释。"""
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = '../公测3.0/太空杀_公测3.0_规则.md'
s = io.open(f, encoding='utf-8').read()
old = "使用后死亡夜延后 1 夜，但当夜失去全部主动行动能力（不进入沉默、不影响白天投票）。"
new = "使用后死亡夜延后 1 夜，但当夜失去**全部主动行动能力（含查验、巡逻、保护等所有夜间技能）**（不进入沉默、不影响白天投票）。"
if old in s:
    s = s.replace(old, new, 1)
    io.open(f, 'w', encoding='utf-8', newline='').write(s)
    print('patched')
else:
    print('pattern variants:', s.count('失去全部主动行动能力'), s.count('失去当夜主动行动'))
