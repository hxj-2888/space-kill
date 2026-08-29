# -*- coding: utf-8 -*-
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')
f = 'verify_suppress.py'
lines = [l for l in io.open(f, encoding='utf-8').read().split('\n')
         if 'S1a' not in l]
io.open(f, 'w', encoding='utf-8', newline='').write('\n'.join(lines))
print('placeholder removed')
