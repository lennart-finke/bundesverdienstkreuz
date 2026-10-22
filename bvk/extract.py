import datetime, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from .common import EXT, GRADES, MODEL, MON, docs, llm, write
from .official import valid_list
from .identity import clean_name

G = [g for g in GRADES.values() if g] + ['unbekannt']
GRADE_ALIASES = {'Verdienstkreuz am Band': 'Verdienstkreuz am Bande', 'Verdientmedaille': 'Verdienstmedaille'}

def grade_heading(line):
    line = ' '.join(line.split())
    return line if line in G else GRADE_ALIASES.get(line)

S = lambda: {'type': ['string', 'null']}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['awards'], 'properties': {'awards': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False,
    'required': ['name', 'grade', 'date', 'year', 'place', 'presented_by', 'occupation', 'residence', 'reason', 'quote'],
    'properties': {'name': {'type': 'string'}, 'grade': {'type': 'string', 'enum': G}, 'date': S(), 'year': {'type': ['integer', 'null']},
                   'place': S(), 'presented_by': S(), 'occupation': S(), 'residence': S(), 'reason': S(), 'quote': S()}}}}}
PROMPT = '''Extract every person who RECEIVED the Verdienstorden der Bundesrepublik Deutschland (Bundesverdienstkreuz, any grade, incl. Verdienstmedaille des Verdienstordens) according to the document below.
Rules:
- Exclude state orders (e.g. Bayerischer Verdienstorden, Verdienstorden des Landes NRW), Ehrennadeln, Landesmedaillen, foreign orders, and people only nominated or mentioned.
- name: full name without academic titles. Never substitute a profession or description for an unknown name; omit unnamed recipients. grade: exact grade or "unbekannt".
- date: ISO date (YYYY-MM-DD) of conferral/handover if known, else null. year: the award year; resolve relative dates ("am Freitag") using the publication date.
- place: where handed over; presented_by: who handed it over (e.g. "Bundespräsident Frank-Walter Steinmeier", "Landrat X").
- occupation, residence: as stated. reason: 1-2 German sentences summarising the merits it was awarded for.
- quote: a short verbatim excerpt from the document supporting the award.
- Unknown -> null. No recipients -> empty list.

Title: {title}
URL: {url}
Published: {date}
---
{text}'''
CHUNK = 24000

TITLE = re.compile(r'^(Prof(essor(in)?)?\.?|Dr\.?(-Ing\.|\s?h\.\s?c\.|\s?med\.|\s?phil\.|\s?rer\.\s?nat\.|\s?jur\.)*|em\.|h\.\s?c\.|mult\.|Dipl\.-\S+|PD|Dr\.\s?Dr\.( h\.\s?c\.)?)$')

HONOR = re.compile(r'^(Freifrau|Freiherr|Freiin|Graf|Gräfin|Prinz|Prinzessin|Fürst|Fürstin|Sir|Dame|Msgr\.|Monsignore|Comte|Comtesse|Marquis|Marquise|Conde|Condesa|Conte|Contessa)$')
PARTICLE = re.compile(r'^(von|von der|von dem|von und zu|vom|zu|zur|van|van der|van den|de|del|della|di|da|du|le|la|ten|ter|te|op de|op den)$')  # "Hompel, ten, Michael, …"
TITLE_SEG = re.compile(r'^(((em|emer|apl|Apl)\.\s*)?(Prof|Dr\.|Professor)|Hon\.-?\s?Prof|M\.A\.$|MD$|PhD$)')
NOBLE = re.compile(r'^(.+?)\s+(?:(Graf|Gräfin|Freiherr|Freifrau|Freiin|Fürst|Fürstin|Prinz|Prinzessin|Baron|Baronin|Baroness)\s*)?(von und zu|von der|von dem|von den|von|zu|zur|vom|van der|van den|van|de)?$')  # "Puttkamer von", "Platen-Hallermund Gräfin von"
HONP = re.compile(r'^(Graf|Gräfin|Freiherr|Freifrau|Freiin|Fürst|Fürstin|Prinz|Prinzessin|Comte|Comtesse|Marquis|Marquise)\s+(von und zu|von der|von dem|von|zu|de la|de|du)$')  # "…, Christian, Freiherr von der, …", "Beaumont-Beynac, Comte de, Thierry, …"
LEAD_PARTICLE = re.compile(r'^((?:van|von|de|ten|ter|zu|vom)(?: der| den| dem)?)\s+(.+)$')  # "Thiel, van Jan Hendrik, Potsdam"
# leading residence segments that are titles, styles, stage names or professions: "Professor, Witten", "S.E., Potsdam", "Dr. h.c., Kaarst", "Künstlername: Alfons, Hamburg", "Lehrer, Merseburg"
PLACE_TITLE = re.compile(r'^((Prof\.|Professor(in)?|Dr\.|Dr\.-Ing\.|Hon\.-?\s?Prof\.?|PD|em\.|apl\.|Dipl\.-\S+)(\s.*)?|S\.\s?E\.|I\.\s?E\.|I\.\s?K\.\s?H\.|S\.\s?K\.\s?H\.|Künstlername:.*|genannt\s.*|(Bruder|Schwester|Pater|Frater)(\s.*)?|Dipl\.(\s?[a-zäöü]+\.)+|Monsignore|Msgr\.|Prälat|'
                         r'(Lehrer|Pfarrer|Politiker|Schriftsteller|Journalist|Künstler|Musiker|Schauspieler|Unternehmer|Botschafter|Diplomat|Pastor|Rabbiner|Bischof)(in)?)$')

def clean_place(place, name):
    segs = [s.strip() for s in place.split(',')] if place else []
    words = set(name.split())
    while len(segs) > 1 and (not segs[0] or TITLE.match(segs[0]) or PLACE_TITLE.match(segs[0]) or segs[0] in words or re.match(r'(em|emer|ehem)\.\s', segs[0])):
        segs.pop(0)  # "Christian, Dr., Dresden" repeats the given name; "ehem. Erzieherin, Schweinfurt"
    return re.sub(r'^\(([^()]+)\)$', r'\1', re.sub(r'^(em|emer|ehem|Dipl)\.\s+', '', ', '.join(segs))) or None  # "em. Murnau a. Staffelsee", "Dipl. Wiesenbach", a country alone: "(Ungarn)"

def entry(l, g, ann, src=None):
    l = re.sub(r'</?s>|^\W*\[\[(?=[^\]]*$)', '', l).strip(' |')
    art = None
    if m := re.search(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', l):
        art, pre, post = m[1], l[:m.start()].split(), l[m.end():].lstrip(', ')
        titles = [t for t in pre if TITLE.match(t) or TITLE_SEG.match(t) or t in ('Dr.', 'Professor', 'Professorin', 'Prof.') or re.match(r'^([a-z]{2,6}\.)+$|^E\.h\.$', t) or HONOR.match(t)]  # "Dr. med. habil."
        link = re.sub(r'\s*\([^)]*\)$', '', (m[2] or m[1]).strip())  # drop "(Komponist)" disambiguation
        tail = l[m.end():]
        if sfx := re.match(r'-[^\W\d_]+', post): link, post = link + sfx[0], post[sfx.end():].lstrip(', ')  # "[[Katrin Rohde]]-Eshishiku, Hamburg"
        elif trail := re.match(r'[a-zäöüß]+', tail): link, post = link + trail[0], tail[trail.end():].lstrip(', ')  # MediaWiki link trail: "[[… Altman]]n, Moskau" reads "Altmann"
        elif (cont := re.match(r'\s+([A-ZÄÖÜ][^\s,()]*)\s*,\s*(.+)$', tail)) and not (TITLE.match(cont[1]) or PLACE_TITLE.match(cont[1])):
            link, post = f'{link} {cont[1]}', cont[2]  # surname continues after the link: "[[Traute Lafrenz]] Page, South Carolina (USA)"
        if (gr := re.match(r'^(.+?) (\S+) gr\.$', link)) and (full := re.match(r'^\((Gro(?:ß|ss)e?\s+' + re.escape(gr[2]) + r')\),?\s*(.*)$', post)):
            link, post = f'{gr[1]} {full[1]}', full[2]  # "[[Ursula Holthaus gr.]] (Große Holthaus), Lohne"
        if ' ' not in link and ' ' in m[1]: link = re.sub(r'\s*\([^)]*\)$', '', m[1].strip())  # "[[Beate Klarsfeld|Beate]] und …"
        name = clean_name(' '.join([t for t in pre if t not in titles] + [link]))
        place = clean_place(post, name)
    else:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 3: return None
        last, rest, pre, titles = p[0], p[1:], [], []
        if (m := NOBLE.match(last)) and (m[2] or m[3]):
            last = m[1]; titles += [m[2]] if m[2] else []; pre += [m[3]] if m[3] else []
        while len(rest) > 2 and (PARTICLE.match(rest[0]) or HONOR.match(rest[0]) or HONP.match(rest[0])):  # "Bussche, von dem, Viktoria, ..." / "Chipperfield, Sir, David, ..."
            t = rest.pop(0)
            if m := HONP.match(t): titles.append(m[1]); pre.append(m[2])
            else: (pre if PARTICLE.match(t) else titles).append(t)
        while len(rest) > 2 and TITLE.match(rest[0]): titles.append(rest.pop(0))
        given = re.sub(r'\s*\(Künstlername:[^)]*\)', '', rest.pop(0)).strip()  # "Reichel, Joachim (Künstlername: Achim Reichel), Hamburg"
        if m := LEAD_PARTICLE.match(given): pre.append(m[1]); given = m[2]
        if m := re.match(r'^\S+ gr\. \((Gro(?:ß|ss)e?\s+\S+)\)$', last): last = m[1]  # "Holthaus gr. (Große Holthaus), Ursula, Lohne"
        while rest and (TITLE.match(rest[0]) or TITLE_SEG.match(rest[0]) or HONOR.match(rest[0]) or HONP.match(rest[0])):
            t = rest.pop(0)
            if m := HONP.match(t): titles.append(m[1]); pre.append(m[2])
            else: titles.append(t)
        name = ' '.join([given, *pre, last])
        place = clean_place(', '.join(rest), name)
    while place and ', ' in place and re.match(r'\(.*\)$|(genannt|em\.|emer\.|ehem\.)\s', place.split(', ')[0]): place = place.split(', ', 1)[1]  # "(Schwester Giselhild), Neuenkirchen", "genannt Maruška, Kitzingen"
    y = (ann - datetime.timedelta(days=120)).year
    return dict(name=name, grade=g, date=None, year=y, place=None, presented_by=None, occupation=None, residence=place, reason=None,
                year_estimated=True, quote=l, titles=' '.join(titles) or None, announced=ann.isoformat(), article=art, official=src)

def couple(e):  # "Klarsfeld, Beate und Serge, Paris" -> one record per person
    if not (m := re.match(r'^(\S+) und (\S+) (.+)$', e['name'])): return [e]
    return [{**e, 'name': f'{m[1]} {m[3]}'}, {**e, 'name': f'{m[2]} {m[3]}'}]

def wp_parts(l):  # one WikiProjekt line can hold several recipients: "[[A]], X |[[B]], Y", "[[A|Beate]] und [[B]], Paris"
    out = []
    for x in re.split(r'\s+\|\s*(?=\S)(?![^\[]*\]\])', l):  # not the pipe inside "[[Ursula Schmitt | Ursula Schmitt (Politikerin)]]"
        ys = re.split(r'(?<=\]\])\s+und\s+(?=\[\[)', x)
        place = ys[-1].rsplit(']],', 1)[1] if len(ys) > 1 and ']],' in ys[-1] else None
        out += [y if place is None or ']],' in y else f'{y},{place}' for y in ys]
    return out

def parse_list(d):
    out, g = [], None
    m = re.search(r'Bekanntgabe-Ordensverleihung/(\d{2})(\d{2})(\d{2})?-', d['url'])
    if not valid_list(d['text']): raise ValueError('Invalid official announcement')
    ann = datetime.date(2000 + int(m[1]), int(m[2]), int(m[3] or 1)) if m else datetime.date.fromisoformat(d['date'])
    lines = []
    for l in (l.strip() for l in d['text'].replace('\xad', '').replace('\xa0', ' ').splitlines()):
        prev = lines[-1] if lines else ''
        if prev and grade_heading(f'{prev} {l}'): lines[-1] = f'{prev} {l}'  # heading split over two lines: "Großes" / "Verdienstkreuz"
        elif prev and not grade_heading(prev) and (prev.endswith(('(', ',', '-')) or prev.endswith(('Professor', 'Professorin')) or l.startswith((',', ')', '-'))
                                       or re.match(r'^(med|phil|jur|rer|nat|vet|habil|Ing|mult|h\.\s?c)\.', l) or (len(l) < 25 and l.endswith('.') and ',' not in l)
                                       or (prev.count(',') == 1 and prev.endswith('.') and l.count(',') == 1 and not re.match(r'^(Groß|Sonder|Verdien|Berlin,? den|Die Chefin|Der Chef)', l))):  # "Kappus, Dr." / "Michael, Itzehoe"
            lines[-1] = prev + ('' if l.startswith((',', ')', '-')) or prev.endswith(('(', '-')) else ' ') + l
        else: lines.append(l)
    for l in lines:
        if re.match(r'Berlin,? den|Die Chefin|Der Chef', l): g = None
        elif grade_heading(l): g = grade_heading(l)
        elif ',' not in l and re.match(r'^(Groß|Sonder|Verdien)', l): g = None
        elif l.startswith(('Zusatzinformationen', 'Weitere Informationen')): g = None
        elif g and l.count(',') >= 2 and (e := entry(l, g, ann)): out += couple(e)
    return {'model': 'parser', 'provider': None, 'awards': out}

def parse_wp(d):
    out, g, ann, src = [], None, None, None
    for l in d['text'].splitlines():
        if m := re.match(r'^=+\s*(\d{1,2})\.\s*(\w+)\s+(\d{4})\s*=+', l):
            ann, g, src = datetime.date(int(m[3]), MON[m[2]], int(m[1])), None, None
        elif m := re.search(r'Quelle:<br>\[(\S+)', l): src = m[1].replace('http://', 'https://')
        elif m := re.search(r'font-weight:bold[^>]*>([^<]+)</div>', l): g = grade_heading(m[1])
        elif g and ann and l.strip() and not l.startswith(('{', '|', '<div', '=')):
            out += [x for part in wp_parts(l) if (e := entry(part, g, ann, src)) for x in couple(e)]
    return {'model': 'parser', 'provider': None, 'awards': out}

def one(k, d):
    if d['src'] in ('wikiprojekt', 'bundesanzeiger') or (d['src'] == 'bpr' and 'Bekanntgabe-Ordensverleihung' in d['url']):
        e = parse_wp(d) if d['src'] == 'wikiprojekt' else parse_list(d); write(EXT / f'{k}.json', e); return len(e['awards'])
    out, prov, t = [], set(), d['text']
    for i in range(0, max(len(t), 1), CHUNK):
        r = llm([{'role': 'user', 'content': PROMPT.format(**{**d, 'text': t[i:i + CHUNK + 1000]})}], SCHEMA, temperature=0)
        out += json.loads(r['choices'][0]['message']['content'])['awards']
        prov.add(r.get('provider'))
    write(EXT / f'{k}.json', {'model': MODEL, 'provider': ', '.join(sorted(map(str, prov))), 'awards': out})
    return len(out)

def run(src=None, limit=None):
    todo = [(k, d) for k, d in docs(src) if not (EXT / f'{k}.json').exists()][:int(limit) if limit else None]
    print(f'{len(todo)} docs to extract with {MODEL}')
    n = err = 0
    with ThreadPoolExecutor(16) as ex:
        for i, f in enumerate([ex.submit(one, k, d) for k, d in todo]):
            try: n += f.result()
            except Exception as e: err += 1; print('ERR', todo[i][1]['url'], e, file=sys.stderr)
            print(f'{i + 1}/{len(todo)} awards={n} err={err}', end='\r')
    print()
