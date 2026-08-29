# -*- coding: utf-8 -*-
"""上传安全扫描：秘钥/令牌/PII/绝对路径/账号信息（全工作区，排除 .git）。"""
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
PATTERNS = [
    ('GitHub PAT', re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}')),
    ('OpenAI sk', re.compile(r'sk-[A-Za-z0-9]{20,}')),
    ('AWS AKIA', re.compile(r'AKIA[0-9A-Z]{16}')),
    ('JWT', re.compile(r'eyJ[A-Za-z0-9_-]{20,}\.eyJ')),
    ('通用 api_key/secret 赋值', re.compile(r'(api[_-]?key|secret|passwd|password)\s*[:=]\s*["\'][A-Za-z0-9]{8,}["\']', re.I)),
    ('邮箱', re.compile(r'[A-Za-z0-9._%+-]+@(?:gmail|qq|163|outlook|hotmail)\.[a-z]+')),
    ('本机绝对路径', re.compile(r'[Cc]:[\\/][Uu]sers[\\/]')),
    ('Cloudflare account id', re.compile(r"[0-9a-f]{32}")),
    ('token 赋值', re.compile(r'token\s*[:=]\s*["\'][A-Za-z0-9]{16,}["\']', re.I)),
]
SKIP_EXT = {'.png', '.jpg', '.docx', '.ico', '.woff', '.woff2'}
hits = []
n_files = 0
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', 'node_modules')]
    for fn in files:
        ext = os.path.splitext(fn)[1].lower()
        if ext in SKIP_EXT:
            continue
        p = os.path.join(root, fn)
        n_files += 1
        try:
            s = open(p, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        for name, pat in PATTERNS:
            for mo in pat.finditer(s):
                hits.append((p, name, mo.group(0)[:60]))

print('扫描文件数:', n_files)
if not hits:
    print('OK 未发现秘钥/PII/敏感信息')
else:
    for p, name, frag in hits:
        print('WARN %s | %s | %s' % (p, name, frag))
