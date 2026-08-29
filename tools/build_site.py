#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_site.py — 太空杀静态站生成器
规则取 公测3.0 的 Markdown（最新正式版），剧情（三条胜利线）取 公测2.0 的 docx，
统一转成 site/ 下的静态 HTML。
只用标准库 + python-docx；只收录「剧情 / 规则」，其余文档（调试、模拟、策略）不入站。
用法: python tools/build_site.py
"""
import html
import os
import re
import sys

import docx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC2 = os.path.join(ROOT, '剧情')
SRC3 = os.path.join(ROOT, '公测3.0')
OUT = os.path.join(ROOT, 'site')

DOCS = [
    # (来源路径, 输出文件名, 栏目, 短标题, 副标题, 转换器)
    (os.path.join('公测3.0', '太空杀_公测3.0_规则.md'), 'rules.html', 'rules',
     '游戏规则', '三阵营对抗 · 公测 3.0 正式规则', 'md'),
    (os.path.join('剧情', '人类胜利线.docx'), 'story-human.html', 'story',
     '星途归航 · 人类胜利线', '剧情 · 最终版', 'docx'),
    (os.path.join('剧情', '外星人胜利线.docx'), 'story-alien.html', 'story',
     '星途归航 · 外星人胜利线', '剧情 · 修订版', 'docx'),
    (os.path.join('剧情', '异形胜利线.docx'), 'story-xeno.html', 'story',
     '星途归航 · 异形胜利线', '剧情', 'docx'),
]

# 平衡性模拟成果（公测3.1 最新策略层升级）——最新版官网展示，取缔旧版模拟文档
SIM31 = [
    # (来源路径, 输出文件名, 短标题, 副标题)
    (os.path.join('公测3.1', 'sim_output', '策略矩阵报告.md'), 'sim31-matrix.html',
     '策略矩阵报告', '18 组合 × 2000 局 · 异形三流派与均衡解'),
    (os.path.join('公测3.1', 'sim_output', '异形流派核验.md'), 'sim31-flows.html',
     '异形流派核验', '击杀 / 破坏 / 感染 · 12/12 行为判据'),
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
.filebox {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 18px; margin:10px 0; text-decoration:none; color:var(--text); display:block }}
.filebox:hover {{ border-color:var(--accent) }}
.filebox .t {{ font-weight:700; color:#fff }}
.filebox .s {{ color:var(--muted); font-size:13px; margin-top:3px }}
.kicker {{ font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:var(--accent); margin-bottom:10px }}
h1 {{ font-size:clamp(26px,4.6vw,38px); letter-spacing:-.02em; margin-bottom:28px; color:#fff }}
h2 {{ font-size:20px; color:#fff; margin:44px 0 14px; padding-left:12px; border-left:3px solid var(--accent) }}
p {{ margin:12px 0; color:#c9c9d9; font-size:16px }}
hr {{ border:none; border-top:1px solid var(--line); margin:32px 0 }}
table {{ border-collapse:collapse; width:100%; margin:18px 0; font-size:14.5px }}
th, td {{ border:1px solid var(--line); padding:8px 12px; text-align:left; vertical-align:top; color:#c9c9d9 }}
th {{ background:#181826; color:#fff; white-space:nowrap }}
ul, ol {{ margin:12px 0 12px 26px; color:#c9c9d9; font-size:16px }}
li {{ margin:6px 0 }}
blockquote {{ margin:18px 0; padding:12px 18px; border-left:3px solid var(--accent); background:#12121e; border-radius:0 10px 10px 0 }}
blockquote p {{ color:var(--muted); font-size:15px }}
code {{ background:#1c1c2c; border:1px solid var(--line); border-radius:5px; padding:1px 6px; font-size:13.5px; color:#a5b4fc }}
pre {{ background:#12121e; border:1px solid var(--line); border-radius:10px; padding:14px; overflow-x:auto; color:#c9c9d9; font-size:13px }}
.foot {{ margin-top:64px; padding-top:20px; border-top:1px solid var(--line); color:var(--muted); font-size:13px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap }}
.foot a {{ color:var(--accent); text-decoration:none }}
</style>
</head>
<body>
<nav>
  <a class="brand" href="index.html">🚀 太空杀 · 星途归航</a>
  <a class="tab{on_story}" href="story-human.html">剧情</a>
  <a class="tab{on_rules}" href="rules.html">规则</a>
  <a class="tab{on_sim}" href="sim31-matrix.html">平衡性</a>
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
  <div class="kicker">Space Kill · 公测 3.0</div>
  <h1>太空杀 · 星途归航</h1>
  <p class="sub">15 人三阵营（人类 11 / 异形 3 / 外星人 1）身份博弈桌游。这里收录官方剧情（三条胜利线）与最新正式规则（公测 3.0）。</p>
  <div class="grid">
    <a class="card" href="story-human.html"><div class="tag">剧情</div><h2>人类胜利线</h2><p>星途归航 · 最终版——信天翁号的二十昼夜。</p></a>
    <a class="card" href="story-alien.html"><div class="tag">剧情</div><h2>外星人胜利线</h2><p>星途归航 · 修订版——船体深处的低语。</p></a>
    <a class="card" href="story-xeno.html"><div class="tag">剧情</div><h2>异形胜利线</h2><p>寄生、觉醒与破壳之夜。</p></a>
    <a class="card" href="rules.html"><div class="tag">规则</div><h2>游戏规则 v3.0</h2><p>三阵营对抗 · 正式发布版全部条款、表格与【消歧】注释。</p></a>
    <a class="card" href="sim31-matrix.html"><div class="tag">平衡性模拟</div><h2>策略矩阵报告（公测 3.1）</h2><p>异形三大流派权重化 · 感染为显式权重 · 均衡解。</p></a>
    <a class="card" href="sim31-flows.html"><div class="tag">平衡性模拟</div><h2>异形流派核验（公测 3.1）</h2><p>击杀 / 破坏 / 感染 · 12/12 行为判据。</p></a>
  </div>
  <div class="foot"> <a href="https://github.com/hxj-2888/space-kill" rel="noopener" target="_blank">GitHub 仓库</a></div>
</div>
</body>
</html>
"""


def md_inline(text):
    """行内 Markdown：转义 + **加粗** + `代码`。"""
    t = html.escape(text, quote=False)
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    return t


def md_to_fragment(path):
    """Markdown → (title, body_html)。支持标题/表格/列表/引用/分隔线/段落。"""
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    title = ''
    out = []
    i = 0
    first = True
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith('```'):  # 代码块（规则文本中无，兜底整块收进 pre）
            i += 1
            block = []
            while i < len(lines) and not lines[i].startswith('```'):
                block.append(lines[i])
                i += 1
            i += 1
            out.append('<pre>' + html.escape('\n'.join(block)) + '</pre>')
            continue
        if line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            text = line.lstrip('#').strip()
            if first:
                title = text
                out.append('<h1>' + md_inline(text) + '</h1>')
                first = False
            else:
                out.append('<h%d>' % min(level + 1, 4) + md_inline(text) + '</h%d>' % min(level + 1, 4))
            i += 1
            continue
        if set(line.strip()) <= {'-', '*'} and len(line.strip()) >= 3:
            out.append('<hr>')
            i += 1
            continue
        if line.lstrip().startswith('|'):  # 表格（下一行是分隔行）
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(set(c) <= {'-', ':', ' '} for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                t = ['<table>', '<tr>' + ''.join('<th>' + md_inline(c) + '</th>' for c in rows[0]) + '</tr>']
                for r in rows[1:]:
                    t.append('<tr>' + ''.join('<td>' + md_inline(c) + '</td>' for c in r) + '</tr>')
                t.append('</table>')
                out.append('\n'.join(t))
            continue
        if line.lstrip().startswith('- '):  # 无序列表
            items = []
            while i < len(lines) and lines[i].lstrip().startswith('- '):
                items.append('<li>' + md_inline(lines[i].lstrip()[2:].strip()) + '</li>')
                i += 1
            out.append('<ul>' + ''.join(items) + '</ul>')
            continue
        if re.match(r'^\d+\.\s', line.lstrip()):  # 有序列表
            items = []
            while i < len(lines) and re.match(r'^\d+\.\s', lines[i].lstrip()):
                items.append('<li>' + md_inline(re.sub(r'^\d+\.\s', '', lines[i].lstrip())) + '</li>')
                i += 1
            out.append('<ol>' + ''.join(items) + '</ol>')
            continue
        if line.lstrip().startswith('>'):  # 引用块
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                quote.append(lines[i].lstrip()[1:].strip())
                i += 1
            out.append('<blockquote><p>' + md_inline(' '.join(q for q in quote if q)) + '</p></blockquote>')
            continue
        if first:
            title = line.strip()
            out.append('<h1>' + md_inline(line.strip()) + '</h1>')
            first = False
            i += 1
            continue
        out.append('<p>' + md_inline(line.strip()) + '</p>')
        i += 1
    return title, '\n'.join(out)


def build():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(INDEX_TMPL)
    for rel, out_name, kind, short, sub, conv in DOCS:
        path = os.path.join(ROOT, rel)
        if conv == 'md':
            title, body = md_to_fragment(path)
        else:
            title, body = docx_to_fragment(path)
        on_story = ' on' if kind == 'story' else ''
        on_rules = ' on' if kind == 'rules' else ''
        on_sim = ''
        page = PAGE_TMPL.format(
            title=short, desc=sub, body=body,
            on_story=on_story, on_rules=on_rules, on_sim=on_sim,
        )
        out = os.path.join(OUT, out_name)
        with open(out, 'w', encoding='utf-8') as f:
            f.write(page)
        print('%-40s -> site/%s  (%d paras)' % (rel, out_name, body.count('<p>')))
    # 平衡性模拟成果页（公测3.1）——最新版，取缔旧模拟
    for rel, out_name, short, sub in SIM31:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print('SKIP(缺文件) %s' % rel)
            continue
        title, body = md_to_fragment(path)
        page = PAGE_TMPL.format(
            title=short, desc=sub, body=body,
            on_story='', on_rules='', on_sim=' on',
        )
        with open(os.path.join(OUT, out_name), 'w', encoding='utf-8') as f:
            f.write(page)
        print('%-40s -> site/%s  (%d paras)' % (rel, out_name, body.count('<p>')))
    print('SITE_BUILD_OK -> site/')


if __name__ == '__main__':
    sys.exit(build())
