# -*- coding: utf-8 -*-
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
s = io.open('../公测3.0/太空杀_公测3.0_模拟代码.py', encoding='utf-8').read()
i = s.find('def step2_check_patrol')
print(s[i:i + 1900])
i = s.find('def step3_bodyguard')
print(s[i:i + 400])
