import re, json
t = open('leapspace.txt', encoding='utf-8').read()
i = t.index('## References')
lines = [l[2:].strip() for l in t[i:].split('\n') if l.startswith('- ')]
refs = []
for n, l in enumerate(lines, 1):
    m = re.search(r'(https?://doi\.org/(\S+))$', l)
    doi = m.group(2) if m else None
    url = m.group(1) if m else (re.search(r'(https?://\S+)$', l).group(1) if re.search(r'(https?://\S+)$', l) else None)
    body = l[:m.start()].strip() if m else (l[:l.rindex('http')].strip() if 'http' in l else l)
    ym = re.search(r'\((\d{4})\)', body)
    year = int(ym.group(1)) if ym else None
    authors = body[:ym.start()].strip() if ym else ''
    rest = body[ym.end():].strip() if ym else body
    parts = [p.strip() for p in rest.rsplit('.', 2)]
    refs.append({'id': n, 'authors': authors, 'year': year, 'raw_title_venue': rest, 'doi': doi, 'url': url})
json.dump(refs, open('refs.json','w'), ensure_ascii=False, indent=1)
print('parsed:', len(refs), '| with DOI:', sum(1 for r in refs if r['doi']), '| no DOI:', [r['id'] for r in refs if not r['doi']])
