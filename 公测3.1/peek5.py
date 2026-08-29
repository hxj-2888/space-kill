# -*- coding: utf-8 -*-
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
s = io.open('太空杀_公测3.1_模拟代码.py', encoding='utf-8').read()
i = s.find('def ai_pick_kill_target')
print(s[i:i + 1400])
