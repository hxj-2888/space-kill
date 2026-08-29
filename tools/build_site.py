#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_site.py — 太空杀静态站生成器
把 公测2.0 的 规则.docx 与三篇胜利线（剧情）docx 转成 site/ 下的静态 HTML。
只用标准库 + python-docx；只收录「剧情 / 规则」，其余文档（调试、模拟、策略）不入站。
用法: python tools/build_site.py
"""
import html
import os
import re
import sys

import docx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, '公测2.0')
OUT = os.path.join(ROOT, 'site')

DOCS = [
    # (docx 文件, 输出文件名, 栏目, 短标题, 副标题)
    ('规则.docx', 'rules.html', 'rules', '游戏规则', '三阵营对抗 · 公测 2.0 正式规则'),
    ('人类胜利线.docx', 'story-human.html', 'story', '星途归航 · 人类胜利线', '剧情 · 最终版'),
    ('外星人胜利线.docx', 'story-alien.html', 'story', '星途归航 · 外星人胜利线', '剧情 · 修订版'),
    ('异形胜利线.docx', 'story-xeno.html', 'story', '星途归航 · 异形胜利线', '剧情'),
]

RE_CHAPTER = re.compile(r'^第[0-9一二三四五六七八九十百零两]+[章节篇部回]')
RE_SUB = re.compile(r'^\d+\.\d+[^0-9]')
RE_SECTION = re.compile(r'^[一二三四五六七八九十]+、')
HR_SET = {'---', '———', '————', '***', '***'}


def is_short_label(text):
    """无标点结尾的短行视为小节标题（如「前情提要」「尾声」）。"""
    t = text.strip()
    if len(t) > 30:
        return False
    if t.startswith(('“', '"', '「', '『')):  # 对话行不是标题
        return False
    if t.endswith(('。', '！', '？', '；', '，', '、', '：', '"', '”')):
        return False
    return True


def docx_to_fragment(path):
    """docx → (title, body_html)。启发式：首行为 h1，章节/短标签行转标题。"""
    d = docx.Document(path)
    title = ''
    body = []
    first = True
    for p in d.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        if first:
            title = text
            body.append('<h1>' + html.escape(text) + '</h1>')
            first = False
            continue
        if text in HR_SET:
            body.append('<hr>')
            continue
        if RE_CHAPTER.match(text) or RE_SUB.match(text) or RE_SECTION.match(text):
            body.append('<h2>' + html.escape(text) + '</h2>')
            continue
        if is_short_label(text):
            body.append('<h2>' + html.escape(text) + '</h2>')
            continue
        body.append('<p>' + html.escape(text) + '</p>')
    return title, '\n'.join(body)


PAGE_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · 太空杀</title>
<meta name="description" content="{desc}">
<style>
:root {{ --bg:#0a0a0f; --card:#141420; --line:#252535; --text:#e0e0ea; --muted:#8888a0; --accent:#818cf8; }}
* {{ margin:0; padding:0; box-sizing:border-box }}
body {{ background:var(--bg); color:var(--text); font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; line-height:1.9 }}
nav {{ position:sticky; top:0; z-index:10; display:flex; align-items:center; gap:14px; padding:14px 22px; background:rgba(10,10,15,.92); backdrop-filter:blur(8px); border-bottom:1px solid var(--line) }}
nav .brand {{ font-weight:700; letter-spacing:.02em; color:#fff; text-decoration:none; margin-right:auto }}
nav a.tab {{ color:var(--muted); text-decoration:none; font-size:14px; padding:5px 12px; border-radius:999px; transition:.15s }}
nav a.tab:hover {{ color:#fff }}
nav a.tab.on {{ color:#fff; background:var(--line) }}
.wrap {{ max-width:52rem; margin:0 auto; padding:48px 22px 96px }}
.kicker {{ font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:var(--accent); margin-bottom:10px }}
h1 {{ font-size:clamp(26px,4.6vw,38px); letter-spacing:-.02em; margin-bottom:28px; color:#fff }}
h2 {{ font-size:20px; color:#fff; margin:44px 0 14px; padding-left:12px; border-left:3px solid var(--accent) }}
p {{ margin:12px 0; color:#c9c9d9; font-size:16px }}
hr {{ border:none; border-top:1px solid var(--line); margin:32px 0 }}
.foot {{ margin-top:64px; padding-top:20px; border-top:1px solid var(--line); color:var(--muted); font-size:13px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap }}
.foot a {{ color:var(--accent); text-decoration:none }}
</style>
</head>
<body>
<nav>
  <a class="brand" href="index.html">🚀 太空杀 · 星途归航</a>
  <a class="tab{on_story}" href="story-human.html">剧情</a>
  <a class="tab{on_rules}" href="rules.html">规则</a>
</nav>
<div class="wrap">
{body}
<div class="foot"><span>太空杀 · 三阵营身份博弈 · 公测 2.0</span><span><a href="https://github.com/hxj-2888/space-kill" rel="noopener" target="_blank">GitHub</a></span></div>
</div>
</body>
</html>
"""

INDEX_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>太空杀 · 星途归航 — 剧情与规则</title>
<meta name="description" content="太空杀：15 人三阵营（人类 / 异形 / 外星人）身份博弈桌游的剧情与规则。">
<style>
:root {{ --bg:#0a0a0f; --card:#141420; --line:#252535; --text:#e0e0ea; --muted:#8888a0; --accent:#818cf8 }}
* {{ margin:0; padding:0; box-sizing:border-box }}
body {{ background:var(--bg); color:var(--text); font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; line-height:1.8;
  background-image:radial-gradient(1200px 500px at 70% -10%, rgba(99,102,241,.14), transparent), radial-gradient(900px 420px at 10% 110%, rgba(124,58,237,.10), transparent) }}
.wrap {{ max-width:64rem; margin:0 auto; padding:72px 22px 96px }}
.kicker {{ font-size:12px; letter-spacing:.2em; text-transform:uppercase; color:var(--accent) }}
h1 {{ font-size:clamp(30px,5.4vw,46px); letter-spacing:-.02em; color:#fff; margin:12px 0 14px }}
.sub {{ color:var(--muted); max-width:46rem }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); gap:18px; margin-top:44px }}
.card {{ display:block; background:var(--card); border:1px solid var(--line); border-radius:20px; padding:24px 22px; text-decoration:none; color:var(--text); transition:.2s }}
.card:hover {{ transform:translateY(-3px); border-color:var(--accent); box-shadow:0 12px 32px rgba(99,102,241,.15) }}
.card .tag {{ font-size:12px; color:var(--accent); letter-spacing:.14em; text-transform:uppercase }}
.card h2 {{ font-size:19px; color:#fff; margin:8px 0 6px }}
.card p {{ color:var(--muted); font-size:14px }}
.foot {{ margin-top:56px; color:var(--muted); font-size:13px }}
.foot a {{ color:var(--accent); text-decoration:none }}
</style>
</head>
<body>
<div class="wrap">
  <div class="kicker">Space Kill · 公测 2.0</div>
  <h1>太空杀 · 星途归航</h1>
  <p class="sub">15 人三阵营（人类 11 / 异形 3 / 外星人 1）身份博弈桌游。这里收录官方剧情（三条胜利线）与正式规则。</p>
  <div class="grid">
    <a class="card" href="story-human.html"><div class="tag">剧情</div><h2>人类胜利线</h2><p>星途归航 · 最终版——信天翁号的二十昼夜。</p></a>
    <a class="card" href="story-alien.html"><div class="tag">剧情</div><h2>外星人胜利线</h2><p>星途归航 · 修订版——船体深处的低语。</p></a>
    <a class="card" href="story-xeno.html"><div class="tag">剧情</div><h2>异形胜利线</h2><p>寄生、觉醒与破壳之夜。</p></a>
    <a class="card" href="rules.html"><div class="tag">规则</div><h2>游戏规则 v1.2</h2><p>三阵营对抗 · 正式发布版全部条款与注释。</p></a>
  </div>
  <div class="foot"> <a href="https://github.com/hxj-2888/space-kill" rel="noopener" target="_blank">GitHub 仓库</a></div>
</div>
</body>
</html>
"""


def build():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(INDEX_TMPL)
    for src_name, out_name, kind, short, sub in DOCS:
        path = os.path.join(SRC, src_name)
        title, body = docx_to_fragment(path)
        on_story = ' on' if kind == 'story' else ''
        on_rules = ' on' if kind == 'rules' else ''
        page = PAGE_TMPL.format(
            title=short, desc=sub, body=body,
            on_story=on_story, on_rules=on_rules,
        )
        out = os.path.join(OUT, out_name)
        with open(out, 'w', encoding='utf-8') as f:
            f.write(page)
        print('%-22s -> site/%s  (%d paras)' % (src_name, out_name, body.count('<p>')))
    print('SITE_BUILD_OK -> site/')


if __name__ == '__main__':
    sys.exit(build())
