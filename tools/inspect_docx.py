import docx, os
base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '公测2.0')
for name, start in [('规则.docx', 100), ('人类胜利线.docx', 200), ('异形胜利线.docx', 400)]:
    d = docx.Document(os.path.join(base, name))
    print('===', name, 'sample from', start)
    for p in d.paragraphs[start:start + 22]:
        bold = all((r.bold or r.font.bold) for r in p.runs) if p.runs else False
        print(('B' if bold else ' ') + '|' + p.text[:70])
    print()
