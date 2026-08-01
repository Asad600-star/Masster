import re, xml.etree.ElementTree as ET
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
t=ET.parse('ls_doc/word/document.xml'); r=t.getroot()
body=r.find('w:body',NS)
out=[]
def para_text(p):
    return ''.join(n.text or '' for n in p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
def style(p):
    pPr=p.find('w:pPr',NS)
    if pPr is None: return None,None
    st=pPr.find('w:pStyle',NS)
    num=pPr.find('w:numPr',NS)
    return (st.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') if st is not None else None), (num is not None)
def walk(el, depth=0):
    for child in el:
        tag=child.tag.split('}')[1]
        if tag=='p':
            s,isnum=style(child)
            txt=para_text(child)
            pre=''
            if s and s.startswith('Heading'): pre='#'*int(s[-1] if s[-1].isdigit() else 1)+' '
            elif isnum: pre='- '
            out.append(('  '*depth)+pre+txt)
        elif tag=='tbl':
            out.append(('  '*depth)+'[TABLE]')
            for row in child.findall('w:tr',NS):
                cells=[' '.join(para_text(p) for p in c.findall('w:p',NS)) for c in row.findall('w:tc',NS)]
                out.append(('  '*depth)+'| '+' | '.join(cells)+' |')
            out.append(('  '*depth)+'[/TABLE]')
walk(body)
open('leapspace.txt','w').write('\n'.join(out))
print(len(out),'blocks')
