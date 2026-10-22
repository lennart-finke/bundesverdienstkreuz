"""Second LLM pass over the press, Wikipedia and ceremony pages already attached to a record. It asks once per person and page for the fields
the first extraction left empty, and replaces quotes that do not name the person with a verbatim sentence of the page that does.
Values only fill empty fields; a date must be readable in the page. Answers are cached per person, page and extracted quote in cache/repair/."""
import datetime, json, re, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from .common import CACHE, DATA, MODEL, MONTHS, docs, h, llm, write
from . import enrich, merge

DIR = CACHE / 'repair'; DIR.mkdir(parents=True, exist_ok=True)
FIELDS = ('occupation', 'reason', 'date', 'place', 'presented_by')
S = lambda: {'type': ['string', 'null']}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['same_award', *FIELDS], 'properties': {'same_award': {'type': 'boolean'}, **{f: S() for f in FIELDS}}}
PROMPT = '''The page below reports that {name}{res} received the Verdienstorden der Bundesrepublik Deutschland ({grade}, {year}). Answer from the page only; null when it does not say.
- same_award: false if the page does not report this award for this person (another person, a state order, an earlier or other award, a nomination).
- occupation: the person's profession or role as stated, e.g. "Vorsitzende des Heimatvereins".
- reason: 1-2 German sentences summarising the merits the award was given for.
- date: ISO date (YYYY-MM-DD) of the conferral or handover, only if the page gives the day; resolve relative dates ("am Freitag") only against the publication date; if it is "unbekannt", null.
- place: where it was handed over; presented_by: who handed it over, e.g. "Landrat X", "Bundespräsident Frank-Walter Steinmeier".

Title: {title}
URL: {url}
Published: {published}
---
{text}'''
AWARD = re.compile(r'Verdienst|Orden|ausgezeichnet|geehrt|verliehen|überreicht|Auszeichnung|Ehrung', re.I)
COST = 0.004  # USD per question, measured on a trial batch

def pages():
    return {d['url']: d for _, d in docs() if d['src'] in ('search', 'dewiki') or (d['src'] == 'bpr' and 'Bekanntgabe-Ordensverleihung' not in d['url'])}

def mentions(text, name): return [m.start() for m in re.finditer(r'\b' + re.escape(name.split()[-1]) + r'\b', text, re.I)]

def excerpt(text, name, width=1500, cap=8000):  # the passages around each mention of the surname
    spans = []
    for i in mentions(text, name):
        if spans and i - width <= spans[-1][1]: spans[-1][1] = i + width
        else: spans.append([max(0, i - width), i + width])
    return ' … '.join(text[a:b] for a, b in spans)[:cap]

ABBR = {'dr', 'prof', 'st', 'nr', 'ca', 'bzw', 'hl', 'abs', 'art', 'bd', 'ggf', 'inkl', 'jh', 'vgl', 'usw', 'evtl', 'mio', 'mrd', 'z.b', 'u.a', 'e.v', 'sen', 'jun', 'gen', 'em', 'h.c', 'med', 'phil'}

def sentences(text):  # not at "12. Dezember", "Dr. Muster", "M. Muster"
    out, start = [], 0
    for m in re.finditer(r'[.!?](?=\s+["„A-ZÄÖÜ])|\n+', text):
        w = (re.search(r'(\S*)$', text[start:m.start()])[1]).casefold()
        if m[0] == '.' and (w.isdigit() or w in ABBR or len(w) == 1): continue
        out.append(text[start:m.end()].strip()); start = m.end()
    return [s for s in out + [text[start:].strip()] if s]

def quote_for(text, name, quote):  # a verbatim sentence naming the person, preferably one about the award
    sur = name.split()[-1]
    if quote and re.search(r'\b' + re.escape(sur) + r'\b', quote, re.I): return None
    ss = [s for s in sentences(text) if len(s) >= 15 and re.search(r'\b' + re.escape(sur) + r'\b', s, re.I)]
    s = next((s for s in ss if AWARD.search(s)), None)  # not a caption or the "Wikipedia-Artikel: …" header
    if not s or len(s) <= 400: return s
    i = re.search(r'\b' + re.escape(sur) + r'\b', s, re.I).start()
    return s[max(0, i - 200):i + 200].strip()

def readable(date, text, published, name=''):
    """The day and month are written in the page next to the person or the award (not a birthday elsewhere), followed by the year or on a page published that year."""
    try: d = datetime.date.fromisoformat(date)
    except (TypeError, ValueError): return False
    m, near = MONTHS[d.month - 1], AWARD.pattern + (f'|\\b{re.escape(name.split()[-1])}\\b' if name else '')
    for x in re.finditer(rf'(?<!\d)0?{d.day}\.\s*(?:{m}|{m[:3]}\.|0?{d.month}\.)\s*(\d{{4}})?', text):
        if re.search(near, text[max(0, x.start() - 250):x.end() + 250], re.I) and (x[1] == str(d.year) or (not x[1] and (published or '')[:4] == str(d.year))): return True
    return False

def jobs(people, D):
    out = {}
    for p in people:
        for a in p['awards']:
            if all((p if f == 'occupation' else a)[f] for f in FIELDS): continue
            for s in a['sources']:
                if s.get('extracted_by') in ('parser', None) or s['url'] not in D or not mentions(D[s['url']]['text'], p['name']): continue
                out[h(f"{p['id']}|{s['url']}|{s.get('extraction_quote') or s.get('quote') or ''}")] = (p, a, s)
    return out

def ask(key, p, a, d):
    res = f" ({p['residence']})" if p['residence'] else ''
    msg = PROMPT.format(name=p['name'], res=res, grade=a['grade'], year=a['year'], title=d['title'], url=d['url'], published=d.get('date') or 'unbekannt', text=excerpt(d['text'], p['name']))
    r = llm([{'role': 'user', 'content': msg}], SCHEMA, temperature=0)
    out = {**json.loads(r['choices'][0]['message']['content']), 'model': MODEL, 'provider': r.get('provider'), 'cost': (r.get('usage') or {}).get('cost'), 'url': d['url'], 'name': p['name']}
    write(DIR / f'{key}.json', out)
    return out

def short(v, n): return v if v and len(v) <= n and not re.search(r'Bundesverdienstkreuz|Verdienstorden', v) else None

def apply(people, D, answers):
    n = Counter()
    for p in people:
        for a in p['awards']:
            listed = min((s['published'] for s in a['sources'] if s.get('extracted_by') == 'parser' and s.get('published')), default=None)
            for s in a['sources']:
                if s.get('extracted_by') in ('parser', None) or s['url'] not in D: continue
                d, q0 = D[s['url']], s.get('extraction_quote') or s.get('quote')
                r = answers.get(h(f"{p['id']}|{s['url']}|{q0 or ''}"))
                if (q := quote_for(d['text'], p['name'], s.get('quote'))): s.update(extraction_quote=q0, quote=q, quote_verified=True); n['quote'] += 1
                if not r or not r['same_award']: continue
                filled = []
                if (v := short(r['occupation'], 150)) and not p['occupation']: p['occupation'] = v; filled.append('occupation')
                if (v := r['reason']) and not a['reason'] and len(v) <= 600 and not merge.PLACEHOLDER.search(v): a['reason'] = v; filled.append('reason')
                pb, v = short(r['presented_by'], 150), r['date'] if readable(r['date'], d['text'], d.get('date'), p['name']) else None
                if v and listed and (datetime.date.fromisoformat(listed[:10]) - datetime.date.fromisoformat(v)).days > 300: v = None  # a year before the list announced it
                if pb and (merge.out_of_office(pb, v) if v else merge.out_of_office(pb, year=a['year'])): pb = v = None  # "Ministerpräsident Bouffier" in 2026: date or presenter is wrong
                if v and not a['date']: a['date'] = v; filled.append('date')
                if pb and not a['presented_by']: a['presented_by'] = pb; filled.append('presented_by')
                if (v := short(r['place'], 150)) and not a['place']: a['place'] = v; filled.append('place')
                if filled: s['repaired'] = filled; s['repaired_by'] = r['model'] + (f" via {r['provider']}" if r['provider'] else ''); n.update(filled)
    return n

def run(confirm=None, limit=None):
    people, D = json.loads((DATA / 'bvk.json').read_text()), pages()
    js = jobs(people, D)
    todo = [k for k in js if not (DIR / f'{k}.json').exists()][:int(limit) if limit else None]
    print(f'{len(js)} person/page pairs with empty fields, {len(todo)} to ask {MODEL}, est. ${len(todo) * COST:.0f}')
    if todo and confirm != 'yes': print('applying cached answers only; to ask the rest: python -m bvk repair yes'); todo = []  # a merge must not lose the answers it already has
    err = 0
    with ThreadPoolExecutor(16) as ex:
        for i, f in enumerate([ex.submit(ask, k, js[k][0], js[k][1], D[js[k][2]['url']]) for k in todo]):
            try: f.result()
            except Exception as e: err += 1; print('ERR', js[todo[i]][2]['url'], e, file=sys.stderr)
            print(f'{i + 1}/{len(todo)} err={err}', end='\r')
    if todo: print()
    answers = {k: json.loads((DIR / f'{k}.json').read_text()) for k in js if (DIR / f'{k}.json').exists()}
    print('cost of answers so far: $%.2f' % sum(float(x.get('cost') or 0) for x in answers.values()))
    n = apply(people, D, answers)
    enrich.run(people)
    (DATA / 'bvk.json').write_text(json.dumps(people, ensure_ascii=False, indent=1))
    print('quotes replaced', n.pop('quote', 0), '| fields filled', dict(n), '| answers', len(answers), 'not about this award', sum(not x['same_award'] for x in answers.values()))
