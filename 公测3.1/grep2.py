# -*- coding: utf-8 -*-
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
for f in ('太空杀_公测3.1_模拟代码.py', '../公测3.0/太空杀_公测3.0_模拟代码.py'):
    s = io.open(f, encoding='utf-8').read()
    print('==', f, '==')
    for k in ('def apply_infection', 'dying_cause_camp', 'infection_death_night = self.night',
              'shield', 'INFECTION', "t.infection_death_night = self.night + 2"):
        print('  %-40s' % k, s.count(k))
