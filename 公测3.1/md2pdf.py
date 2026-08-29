# -*- coding: utf-8 -*-
"""Markdown → PDF 转换器（与 md2docx.py 配套，标题/表格/列表/粗体/代码/引用）。

用法：python md2pdf.py <输入.md> <输出.pdf> <文档标题>
依赖：reportlab（中文字体优先使用微软雅黑 / 黑体，缺失时回退 STSong-Light CID 字体）
"""
import io
import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether)

# ---------------- 中文字体注册 ----------------
FONT_CANDIDATES = [
    (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\msyhbd.ttc', 'MSYH'),
    (r'C:\Windows\Fonts\simhei.ttf', r'C:\Windows\Fonts\simhei.ttf', 'SIMHEI'),
    (r'C:\Windows\Fonts\simsun.ttc', r'C:\Windows\Fonts\simsun.ttc', 'SIMSUN'),
]
_FONT, _FONT_BOLD = 'STSong-Light', 'STSong-Light'
for _reg, _bold, _name in FONT_CANDIDATES:
    try:
        pdfmetrics.registerFont(TTFont(_name, _reg, subfontIndex=0))
        pdfmetrics.registerFont(TTFont(_name + '-B', _bold, subfontIndex=0))
        _FONT, _FONT_BOLD = _name, _name + '-B'
        break
    except Exception:
        continue
if _FONT == 'STSong-Light':
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))


def esc(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def inline(text):
    """**粗体** 与 `代码` → PDF 内联标记。"""
    text = esc(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`([^`]+)`', r'<font face="Courier">\1</font>', text)
    return text


def build_styles():
    base = ParagraphStyle('body', fontName=_FONT, fontSize=9.5, leading=15,
                          alignment=TA_LEFT, spaceAfter=4)
    return {
        'title': ParagraphStyle('title', parent=base, fontName=_FONT_BOLD, fontSize=17,
                                leading=24, spaceAfter=10, textColor=colors.HexColor('#1a237e')),
        'h1': ParagraphStyle('h1', parent=base, fontName=_FONT_BOLD, fontSize=13.5,
                             leading=20, spaceBefore=12, spaceAfter=6,
                             textColor=colors.HexColor('#1a237e')),
        'h2': ParagraphStyle('h2', parent=base, fontName=_FONT_BOLD, fontSize=11.5,
                             leading=17, spaceBefore=9, spaceAfter=5,
                             textColor=colors.HexColor('#283593')),
        'h3': ParagraphStyle('h3', parent=base, fontName=_FONT_BOLD, fontSize=10.5,
                             leading=16, spaceBefore=7, spaceAfter=4),
        'body': base,
        'bullet': ParagraphStyle('bullet', parent=base, leftIndent=12, bulletIndent=2,
                                 spaceAfter=2),
        'quote': ParagraphStyle('quote', parent=base, leftIndent=12, fontSize=9,
                                textColor=colors.HexColor('#546e7a')),
        'cell': ParagraphStyle('cell', parent=base, fontSize=8.5, leading=12, spaceAfter=0),
        'cellb': ParagraphStyle('cellb', parent=base, fontName=_FONT_BOLD, fontSize=8.5,
                                leading=12, spaceAfter=0),
    }


def make_table(rows, styles, widths=None):
    data = []
    for i, row in enumerate(rows):
        st = styles['cellb'] if i == 0 else styles['cell']
        data.append([Paragraph(inline(c), st) for c in row])
    t = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#c7cbd8')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8ecf7')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7f8fc')]),
    ]))
    return t


def convert(md_path, pdf_path, title):
    lines = io.open(md_path, encoding='utf-8').read().split('\n')
    styles = build_styles()
    content_width = A4[0] - 32 * mm

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(colors.HexColor('#8a94a6'))
        canvas.drawString(16 * mm, 12 * mm, title)
        canvas.drawRightString(A4[0] - 16 * mm, 12 * mm, '第 %d 页' % doc.page)
        canvas.restoreState()

    doc = BaseDocTemplate(pdf_path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                          topMargin=16 * mm, bottomMargin=18 * mm, title=title)
    frame = Frame(doc.leftMargin, doc.bottomMargin, content_width,
                  A4[1] - doc.topMargin - doc.bottomMargin, id='f')
    doc.addPageTemplates([PageTemplate(id='all', frames=[frame], onPage=on_page)])

    story = [Paragraph(inline(title), styles['title'])]
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        # 表格
        if s.startswith('|') and i + 1 < len(lines) and re.match(r'^\|[\s\-|:]+\|$', lines[i + 1].strip()):
            header = [c.strip() for c in s.strip('|').split('|')]
            rows = [header]
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith('|'):
                rows.append([c.strip() for c in lines[j].strip().strip('|').split('|')])
                j += 1
            ncol = max(len(r) for r in rows)
            rows = [r + [''] * (ncol - len(r)) for r in rows]
            w = content_width / ncol
            story.append(Spacer(1, 3))
            story.append(make_table(rows, styles, [w] * ncol))
            story.append(Spacer(1, 6))
            i = j
            continue
        mo = re.match(r'^(#{1,4})\s+(.*)', s)
        if mo:
            lv = min(len(mo.group(1)), 3)
            story.append(Paragraph(inline(mo.group(2)), styles['h%d' % lv]))
            i += 1
            continue
        if s.startswith('>'):
            story.append(Paragraph(inline(s.lstrip('> ').strip()), styles['quote']))
            i += 1
            continue
        mo = re.match(r'^[-*]\s+(.*)', s)
        if mo:
            story.append(Paragraph(inline(mo.group(1)), styles['bullet'], bulletText='•'))
            i += 1
            continue
        mo = re.match(r'^(\d+)\.\s+(.*)', s)
        if mo:
            story.append(Paragraph('%s. %s' % (mo.group(1), inline(mo.group(2))), styles['bullet']))
            i += 1
            continue
        story.append(Paragraph(inline(s), styles['body']))
        i += 1

    doc.build(story)
    print('PDF:', pdf_path)


if __name__ == '__main__':
    convert(sys.argv[1], sys.argv[2], sys.argv[3])
