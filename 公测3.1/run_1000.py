# -*- coding: utf-8 -*-
import importlib.util
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
os.environ['SIM_N'] = '1000'
spec = importlib.util.spec_from_file_location('m31', '太空杀_公测3.1_模拟代码.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.main()
