import datetime, difflib, itertools, json, re, unicodedata, urllib.parse
from collections import Counter, defaultdict
from .common import CACHE, DATA, EXT, GRADES, docs, h, iso_date
from . import enrich
from .official import valid_list
from .identity import NICK, clean_name, name_key, identity_matches, ROLES, publisher, split_name, tokens

MIN_YEAR = 2015
RANK = [g for g in GRADES.values() if g]  # lowest grade first
TITLES = r'\b(dr|prof|med|phil|rer|nat|jur|h\.?\s?c|dipl|ing|mult|pd)\b\.?|\b(von|van|der|de)\b'

def norm(n):
    n = unicodedata.normalize('NFKD', n.casefold().replace('’', "'")).encode('ascii', 'ignore').decode()
    return ' '.join(re.sub(TITLES, ' ', re.sub(r'[^a-z\s.-]', ' ', n)).replace('.', ' ').split())

SKIP = re.compile(r'ordenstraeger\.de|diebewertung\.de/(bundespraesidialamt)?bekanntgabe-von-verleihungen|wikipedia\.org/wiki/(Wikipedia:WikiProjekt|Liste_von_Tr)|Bekanntgabe-Ordensverleihung')  # copies of the official lists
# pages listing several honours (e.g. stmi.bayern.de "Orden und Ehrungen"): the award named last before a person is the one they got
STATE = re.compile(r'Kommunale[nr]? Verdienstmedaille|Ehrenzeichen des (Bayerischen )?(Ministerpräsidenten|Freistaat)|Verdienstorden des (Landes|Freistaat)|Landesverdienstorden|'
                   r'(Bayerische|Niedersächsische|Sächsische|Thüringer|Hessische|Berliner|Brandenburgische|Hamburgische|Saarländische|Rheinland-Pfälzische|Schleswig-Holsteinische)[nr]? Verdienst(orden|medaille)|'
                   r'Verdienstmedaille des Landes|Landesehrennadel|Ehrennadel des Landes|Staatsmedaille|Ehrenbrief des Landes|Verfassungsmedaille|Dankurkunde')
FED = re.compile(r'Bundesverdienst|Verdienstorden der Bundesrepublik|Verdienstkreuz (am Bande|1\. Klasse)|Verdienstmedaille des Verdienstordens|Großes Verdienstkreuz')
FEDERAL = re.compile(r'Bundesverdienst|Bundesrepublik|Bundespräsident')  # state orders share grade names ("Verdienstkreuz 1. Klasse des Niedersächsischen Verdienstordens")
LEAD = re.compile(r'^((Dr|Prof|med|phil|habil|vet|em|rer|nat|jur|apl|Apl|Drs|Msgr)\.,?\s*|(Professs?or(in)?|Hon\.-?\s?Prof(essor)?\.?|Schwester|Bruder|Pater|Pfarrer(in)?|Pastor(in)?|Frau|Herr|Sir|Dame|Monsignore|Königin|König|Kronprinz(essin)?|Prinz(essin)?)\s+)+')
ROYAL = re.compile(r'König|Kronprinz|Prinz|Fürst|Großherzog|Monarch', re.I)
NOPLACE = {'landkreis', 'kreis', 'gemeinde', 'stadt', 'ortsteil', 'stadtteil', 'deutschland'}
# office terms of people who hand awards over themselves; a press date outside the term comes from a misresolved "am Freitag" or a republished article
TERMS = [('Bundespräsident', 'Joachim Gauck', '2012-03-18', '2017-03-18'), ('Bundespräsident', 'Frank-Walter Steinmeier', '2017-03-19', None),
         ('Ministerpräsident', 'Horst Seehofer', '2008-10-27', '2018-03-13'), ('Ministerpräsident', 'Markus Söder', '2018-03-16', None),
         ('Ministerpräsident', 'Volker Bouffier', '2010-08-31', '2022-05-31'), ('Ministerpräsident', 'Boris Rhein', '2022-05-31', None),
         ('Ministerpräsident', 'Hannelore Kraft', '2010-07-14', '2017-06-27'), ('Ministerpräsident', 'Armin Laschet', '2017-06-27', '2021-10-27'), ('Ministerpräsident', 'Hendrik Wüst', '2021-10-27', None),
         ('Ministerpräsident', 'Stanislaw Tillich', '2008-05-28', '2017-12-13'), ('Ministerpräsident', 'Michael Kretschmer', '2017-12-13', None),
         ('Ministerpräsident', 'Torsten Albig', '2012-06-12', '2017-06-28'), ('Ministerpräsident', 'Daniel Günther', '2017-06-28', None),
         ('Ministerpräsident', 'Erwin Sellering', '2008-10-06', '2017-07-04'), ('Ministerpräsident', 'Manuela Schwesig', '2017-07-04', None),
         ('Ministerpräsident', 'Stephan Weil', '2013-02-19', '2025-05-20'), ('Ministerpräsident', 'Olaf Lies', '2025-05-20', None),
         ('Ministerpräsident', 'Malu Dreyer', '2013-01-16', '2024-07-10'), ('Ministerpräsident', 'Alexander Schweitzer', '2024-07-10', None),
         ('Ministerpräsident', 'Bodo Ramelow', '2014-12-05', '2024-12-12'), ('Ministerpräsident', 'Mario Voigt', '2024-12-12', None),
         ('Ministerpräsident', 'Annegret Kramp-Karrenbauer', '2011-08-10', '2018-03-01'), ('Ministerpräsident', 'Tobias Hans', '2018-03-01', '2022-04-25'),
         ('Ministerpräsident', 'Anke Rehlinger', '2022-04-25', None), ('Regierender Bürgermeister', 'Michael Müller', '2014-12-11', '2021-12-21'),
         ('Regierender Bürgermeister', 'Franziska Giffey', '2021-12-21', '2023-04-27'), ('Regierender Bürgermeister', 'Kai Wegner', '2023-04-27', None),
         ('Erster Bürgermeister', 'Olaf Scholz', '2011-03-07', '2018-03-13'), ('Erster Bürgermeister', 'Peter Tschentscher', '2018-03-28', None)]
OFFICE = {'Bundespräsident': r'Bundespräsident(?:en|in)?', 'Ministerpräsident': r'Ministerpräsident(?:in|en)?',
          'Regierender Bürgermeister': r'Regierende[rn]?\s+Bürgermeister(?:in)?(?:\s+von\s+Berlin)?', 'Erster Bürgermeister': r'Erste[rn]?\s+Bürgermeister(?:in)?'}
PRESENTERS = [(re.compile(OFFICE[o] + r'\s+(?:Dr\.\s+)?(?:' + re.escape(n.rsplit(' ', 1)[0]) + r'\s+)?' + re.escape(n.rsplit(' ', 1)[1]) + r'\b'), s, e, 180 if o == 'Bundespräsident' else 60) for o, n, s, e in TERMS]

def out_of_office(presented_by, date=None, year=None):
    """The named presenter's term as (start year, end year) if the date (or the whole year) lies outside it; a Bundespräsident's conferral may be handed over months after the term."""
    first, last = (datetime.date.fromisoformat(date),) * 2 if date else (datetime.date(year, 1, 1), datetime.date(year, 12, 31))
    for rx, start, end, grace in PRESENTERS:
        for m in rx.finditer(presented_by or ''):
            if re.search(r'ehemalig|früher|Alt-', presented_by[max(0, m.start() - 25):m.start()]) or re.match(r'\s*a\.\s?D\.', presented_by[m.end():]): continue
            s, e = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end) if end else None
            if last < s - datetime.timedelta(days=30) or (e and first > e + datetime.timedelta(days=grace)): return s.year, e.year if e else max(s.year, last.year)
    return None

def corrections():
    """Reviewed source-level corrections: 'drop' a republished duplicate report or a superseded entry, 'undate' a misresolved date, 'fix' a misread
    entry ('set' name, residence or Wikidata item). An entry with 'name' applies to that record of the page(s) only, otherwise to the whole page."""
    p, out = DATA / 'source_corrections.json', defaultdict(list)
    for x in json.loads(p.read_text()) if p.exists() else []:
        for u in x.get('urls') or [x['url']]: out[u].append(x)
    return out

def correction(fixes, url, name):
    return next((x for x in fixes.get(url, ()) if x.get('name') == name), None) or next((x for x in fixes.get(url, ()) if not x.get('name')), None)

PLACEHOLDER = re.compile(r'(im|das) (Dokument|Text)|(im|dem) (Dokument|Artikel|Text) nicht|nicht näher (beschrieben|erläutert|genannt|ausgeführt)|(werden|sind|wird) (im \w+ )?nicht (genannt|angegeben|erwähnt|näher)|nicht zu entnehmen|nicht ersichtlich|(Seite|Text|Artikel|Dokument|Quelle) nennt kein|keine (ausdrückliche|nähere|konkrete) Begründung|keinen (ausdrücklichen )?Begründungstext')
MERIT = re.compile(r'\b(für|als|wegen|um die|um den|um das)\b|Engagement|Einsatz|Verdienste? um|Wirken|Leistung|Arbeit|Förderung|Gründ')

def clean_reason(r):  # drop "die Verdienste werden im Dokument nicht näher beschrieben"; a remainder that only restates the award is no reason
    if not r or not PLACEHOLDER.search(r): return r
    rest = ' '.join(c for c in re.split(r'(?<=[.;])\s+', r) if not PLACEHOLDER.search(c)).strip(' ;,')
    return (rest if rest.endswith(('.', '!')) else rest + '.') if MERIT.search(rest) else None

def sanitize(a, fix=None):
    """Dates a press or Wikipedia record cannot support: year-only statements turned into 1 January, malformed dates, dates outside the presenter's term.
    Such a record keeps its year, but a misresolved one may no longer override a list estimate. A reason that only says none is given is no reason."""
    if fix == 'drop': return None
    if a.get('reason') and PLACEHOLDER.search(a['reason']): a = {**a, 'reason': clean_reason(a['reason'])}
    d, why = a['date'], 'reviewed' if fix == 'undate' else None
    if not d and not why:  # "Bundespräsident Gauck" in a report dated 2026 is no award of 2025
        return {**a, 'year': min(max(a['year'], span[0]), span[1]), 'year_estimated': True} if a['year'] and (span := out_of_office(a.get('presented_by'), year=a['year'])) else a
    a = {**a, 'date': None, 'year': a['year'] or (int(d[:4]) if d and d[:4].isdigit() else None)}
    if why: return {**a, 'year_estimated': True}
    try:
        if not re.fullmatch(r'\d{4}-\d\d-\d\d', d) or not datetime.date.fromisoformat(d): return a
    except ValueError: return a  # "2020-12-XX", "2021-02-30"
    if d.endswith('-01-01') and not re.search(r'(?<!\d)0?1\.\s*(Januar|0?1\.)|Neujahr', a.get('quote') or ''): return a  # "2015: Bundesverdienstkreuz" is a year, not New Year's Day; "31. Januar" is not the 1st
    if span := out_of_office(a.get('presented_by'), d): return {**a, 'year': min(max(a['year'] or span[1], span[0]), span[1]), 'year_estimated': True}
    return {**a, 'date': d, 'year': int(d[:4])}  # the date's own year, not a second guess beside it (2020 with 2023-03-17)

def qn(s): return re.sub(r'\W+', ' ', s or '').lower()

def clean(n): return re.sub(r'\s*\([^)]*\)$', '', re.sub(r'(\w)- (\w)', r'\1-\2', LEAD.sub('', n.strip()))).strip()  # leftover titles, "Ernst- Christoph", "(Komponist)" disambiguation

def not_a_name(n, occupation, qid):
    if re.match(r'((König|Kronprinz|Prinz|Fürst|Großherzog)(in|essin)?\s+(der|von|des|zu)|(Der|Die|Das|der|die|das|des)\s)\b', n): return True  # "König der Niederlande", "Der Herr der Muttenthalbahn", "der Niederlande"
    if re.search(r'\bund\b(?! von| zu)|&|[\[\]|]', n): return True  # "Chemikerin und Journalistin"; couples are split before
    if re.search(r'\b(Ehepaar|Eheleute|Geschwister|Familie|Unbekannte?[rs]?|Heimatdichter)\b', n): return True  # "Ehepaar Christoph", "Unbekanntes Würzburger Ehepaar", "Kronacher Heimatdichter"
    return len(tokens(n)) < 2 and not qid and not ROYAL.search(occupation or '')  # surname only, "Pianist", "Anonym", "Freiherr von Schimmelmann"; monarchs go by one name

def couple(n):  # "Beate und Serge Klarsfeld"
    return [f'{m[1]} {m[3]}', f'{m[2]} {m[3]}'] if (m := re.match(r'^(\S+) und (\S+) (\S+)$', n)) else [n]

def last_honour(s):
    return max([(m.end(), 'state') for m in STATE.finditer(s)] + [(m.end(), 'fed') for m in FED.finditer(s)], default=(0, None))[1]

def state_honour(text, a):
    """A press record is a state honour if the page names only state orders, if its quote names only one (or both without saying who got which),
    or if the last award named before the person in the text is one."""
    q = a['quote'] or ''
    if not STATE.search(text): return False
    if not FEDERAL.search(text): return True  # only a state order is named as such
    if STATE.search(q) or FED.search(q):
        if not (STATE.search(q) and FED.search(q)): return bool(STATE.search(q))
        if re.search(r'beziehungsweise|bzw\.|oder', q) or last_honour(q) == 'state': return True  # "mit dem Bundesverdienstkreuz beziehungsweise dem Ehrenzeichen": unknown who got which
    i = next((i for n in (a['name'], a['name'].split()[-1]) if (i := text.find(n)) >= 0), -1)
    return i >= 0 and last_honour(text[:i]) == 'state' and not FED.search(text[i:i + 300])

def within(a, b):  # every given name of a is in b; an initial ("M.") matches a name with that letter
    return all(x in b or (len(x) == 1 and any(y.startswith(x) for y in b)) for x in a)

def same_given(a, b, loose=False):
    ra, rb = (' '.join(x).replace('-', ' ') for x in (a, b))
    if a and b and difflib.SequenceMatcher(None, ra, rb).ratio() >= .85: return True  # "Willi" / "Willli" before nicknames are expanded
    a, b = [NICK.get(x, x) for x in a], [NICK.get(x, x) for x in b]
    ja, jb = (' '.join(x).replace('-', ' ') for x in (a, b))
    if not a or not b or ja == jb or within(a, b) or within(b, a): return True
    fa, fb = a[0], b[0]
    if fa != fb and '-' not in fa + fb and min(len(fa), len(fb)) >= 4 and (fa.startswith(fb) or fb.startswith(fa)): return True  # Inge / Ingeborg
    if min(len(a), len(b)) == 1 and min(len(fa), len(fb)) >= 4 and difflib.SequenceMatcher(None, fa, fb).ratio() >= (.8 if loose else .85): return True  # Edeltraud / Edeltraut Marion; Dunja / Dunya only between list transcriptions
    return difflib.SequenceMatcher(None, ja, jb).ratio() >= .85  # typos: Roldand / Roland

NONPLACE = {norm(s) for s in (*enrich.STATES.values(), 'Deutschland')} - {'berlin', 'hamburg', 'bremen'}  # "Malu Dreyer (Rheinland-Pfalz)" names no municipality; the city states do

def same_place(a, b):
    wa, wb = ({re.sub(r'([aou])e', r'\1', w)[:5] for w in norm(x or '').replace('-', ' ').split() if len(w) > 3 and w not in NOPLACE} if norm(x or '') not in NONPLACE else set() for x in (a, b))  # "Oesterdeichstrich" / "Österdeichstrich"
    return not wa or not wb or bool(wa & wb) or bool((m := enrich.municipality(a)) and m == enrich.municipality(b))  # "Gresaubach" lies in Lebach

def title_match(name, title):  # a name extracted from a Wikipedia article is its subject, not a spouse or colleague
    n, t = tokens(name), tokens(re.sub(r'\s*\(.*?\)', '', title))
    return bool(t) and t[-1] in n and (len(t) == 1 or bool(set(t[:-1]) & set(n[:-1])) or same_given(n[:-1], t[:-1]))

def official(r): return r['source'].get('extracted_by') == 'parser'

def weight(r): return 10 if official(r) else 2 if r['source']['via'] in ('dewiki', 'wikidata') else 1  # grade votes

def records():
    wd = json.loads((CACHE / 'wikidata.json').read_text()) if (CACHE / 'wikidata.json').exists() else []
    nonhuman_path = CACHE / 'wikidata_nonhuman.json'
    nonhuman = set(json.loads(nonhuman_path.read_text())) if nonhuman_path.exists() else {'Q57584800'}
    wd = [x for x in wd if x['qid'] not in nonhuman]
    labels = defaultdict(list)
    for x in wd:
        labels[x['qid']].extend([x['name'] or '', urllib.parse.unquote((x['dewiki'] or '').rsplit('/wiki/', 1)[-1]).replace('_', ' ')])
    qid = {urllib.parse.unquote(x['dewiki'].rsplit('/wiki/', 1)[1]).replace('_', ' '): x['qid'] for x in wd if x['dewiki']}
    fixes = corrections()
    for k, d in docs():
        p = EXT / f'{k}.json'
        if not p.exists() or (d['src'] == 'search' and SKIP.search(d['url'])): continue
        if (d['src'] == 'bundesanzeiger' or (d['src'] == 'bpr' and 'Bekanntgabe-Ordensverleihung' in d['url'])) and not valid_list(d['text']): continue
        e, txt = json.loads(p.read_text()), qn(d['text'])
        for a in e['awards']:
            fix = correction(fixes, d['url'], a['name'])
            if fix and fix['action'] == 'drop' and e['model'] == 'parser': continue
            if fix and fix['action'] == 'fix': a = {**a, **{k: v for k, v in fix['set'].items() if k != 'qid'}}
            if e['model'] != 'parser' and not (a := sanitize(a, fix and fix['action'])): continue
            y = a['year'] or (int(a['date'][:4]) if a['date'] else None)
            estimated = a.get('year_estimated', e['model'] == 'parser')
            boundary = estimated and (a.get('announced') or '')[:4] >= str(MIN_YEAR)
            if not (y and (y >= MIN_YEAR or boundary) and (name := clean_name(clean(a['name'])))) or name.casefold() in {x.casefold() for x in ROLES} or (e['model'] != 'parser' and (re.match(r'^\S+ (aus|des) ', name) or state_honour(d['text'], a))): continue  # "Geoökologe aus Bayern" from speeches
            src = {'url': a.get('official') or d['url'], 'title': d['title'], 'published': a.get('announced') or iso_date(d['date']), 'quote': a['quote'], 'via': d['src'],  # page dates also come as "Tue Oct 13", "07:30"
                   'extracted_by': e['model'] + (f" via {e['provider']}" if e['provider'] else '')}
            if d.get('collected_via'): src['collected_via'] = d['collected_via']
            if a.get('official'): src['mirror'] = d['url']
            src['quote_verified'] = bool(a['quote']) and qn(a['quote'])[:80] in txt
            for n in couple(name):
                ident = (d.get('qid') if title_match(n, d['title']) else None) if d['src'] == 'dewiki' else qid.get(a.get('article'))
                piped = (d['src'] == 'wikiprojekt' and a.get('article') and ' und ' not in (a['quote'] or '') and re.search(r'\[\[[^\]|]+\|[^\]]+\]\]', a['quote'] or '')
                         and split_name(re.sub(r'\s*\(.*?\)', '', a['article']))[1] == split_name(n)[1])  # "[[Roland Kaiser|Ronald Kaiser]]": the WikiProjekt editors tied the entry to the article
                if ident in nonhuman or (ident and not piped and not any(identity_matches(n, label) for label in labels[ident])): ident = None
                if fix and fix['action'] == 'fix' and fix['set'].get('qid'): ident = fix['set']['qid']  # reviewed: a later list entry of someone who moved ("Ruth Weiss", Lüdinghausen 2015, Skørping 2024)
                src['publisher'] = publisher(src.get('mirror') or src['url'])
                yield {**a, 'name': n, 'year': y, 'year_estimated': estimated, 'qid': ident, 'source': src}
    for x in wd:
        if x['date'] and x['date'][:4].isdigit() and int(x['date'][:4]) >= MIN_YEAR and x['name']:
            yield dict(name=clean(x['name']), grade=x['grade'] or 'unbekannt', date=x['date'] if not x['date'].endswith('-01-01') else None,
                       year=int(x['date'][:4]), year_estimated=False, place=None, presented_by=None, occupation=x['occupation'] or x['desc'], residence=None,
                       reason=None, qid=x['qid'], source={'url': f"https://www.wikidata.org/wiki/{x['qid']}", 'title': x['name'], 'published': None, 'quote': None, 'via': 'wikidata', 'publisher': 'wikidata'})

def check_qids(rs):
    """Drop Wikidata links that contradict the record: person dead or under 16 / over 105 at the award, not a human,
    or (list entries linked to an article) the item's own award statements rule this award out (same grade in another year,
    another grade the same year, a higher grade earlier). Wikidata-only records of non-humans are dropped."""
    st = defaultdict(list)
    for x in json.loads((CACHE / 'wikidata.json').read_text()) if (CACHE / 'wikidata.json').exists() else []:
        if x['grade'] and x['date'] and x['date'][:4].isdigit(): st[x['qid']].append((x['grade'], int(x['date'][:4])))
    info = enrich.wd_people(r['qid'] for r in rs if r['qid'])
    def ok(r, i):
        if not i.get('human', True): return False
        if r['source']['via'] == 'wikidata': return True
        y, d = r['year'], r['date'] or ''
        if (died := i.get('died')) and (d[:10] > died if len(d) >= 10 else y > int(died[:4])): return False
        if (b := i.get('born')) and not 16 <= y - int(b[:4]) <= 105: return False
        if official(r) and r['grade'] != 'unbekannt':
            for g, wy in st[r['qid']]:
                if (g == r['grade'] and abs(wy - y) > 1) or (g != r['grade'] and abs(wy - y) <= 1) or (RANK.index(g) > RANK.index(r['grade']) and wy < y): return False
        return True
    out = []
    for r in rs:
        if r['qid'] and not ok(r, info.get(r['qid'], {})):
            if r['source']['via'] == 'wikidata': continue  # its own item is not a person
            r['qid'] = None
        if official(r) or not not_a_name(r['name'], r['occupation'], r['qid']): out.append(r)
    return out

def close(a, r):  # reported within a year, or handed over up to two years after the list announced it
    return abs(a['year'] - r['year']) <= 1 or any(x.get('announced') and int(x['announced'][:4]) - 1 <= y['year'] <= int(x['announced'][:4]) + 2 for x, y in ((a, r), (r, a)))

def same_award(a, r): return close(a, r) and (a['grade'] == r['grade'] or 'unbekannt' in (a['grade'], r['grade']))

def upgrade(a, b):  # can a and b be two successive awards of one person? Grades only go up, and not within a year
    if 'unbekannt' in (a['grade'], b['grade']) or abs(a['year'] - b['year']) < 2: return False
    lo, hi = sorted((a, b), key=lambda x: x['year'])
    return RANK.index(hi['grade']) > RANK.index(lo['grade'])

def first(*v): return next((x for x in v if x), None)

def new_person(key): return dict(id=None, name=None, titles=None, wikidata=None, occupation=None, residence=None, awards=[], _key=key, _recs=[])

def promoted(x, r):  # a later list names the same person with a higher grade, given names written more or less fully: "Margot Anni Friedländer" 2023, "Margot Friedländer" 2025
    gx, gr = split_name(x['name'])[0], split_name(r['name'])[0]
    return bool(x['residence'] and r['residence'] and same_place(x['residence'], r['residence']) and (within(gx, gr) or within(gr, gx)) and upgrade(x, r))

def listed_apart(recs, r):  # one list names both as separate entries: "Templin, Wolfgang" (Verdienstkreuz 1. Klasse) and "Templin, Wolfgang Peter" (am Bande), October 2016
    return official(r) and any(official(x) and (x['source']['url'], x['source']['via']) == (r['source']['url'], r['source']['via']) and x['source']['quote'] != r['source']['quote'] for x in recs)

def fits(p, r):  # can record r belong to person p (same name bucket)?
    if r['qid'] and p['wikidata'] and r['qid'] != p['wikidata']: return False
    if listed_apart(p['_recs'], r): return False
    if not same_given(split_name(p['name'])[0], split_name(r['name'])[0]): return False
    if official(r) and (lists := [x for x in p['_recs'] if official(x)]) and not any(x.get('announced') == r.get('announced') or split_name(x['name'])[0] == split_name(r['name'])[0] or promoted(x, r) for x in lists):
        return False  # "Hans Müller" and "Hans-Peter Müller" in two different lists are two people
    other = [x for x in p['_recs'] if official(x) and x['residence']]
    res = [x['residence'] for x in (other if official(r) and other else p['_recs']) if x['residence']]  # a list entry is compared with list entries only
    if not res or (r['residence'] and any(same_place(r['residence'], x) for x in res)): return True
    if not r['residence']: return bool(r['qid'] and r['qid'] == p['wikidata']) or any(same_award(a, r) for a in p['awards'])  # placeless record: only with a matching award or QID
    if official(r) and other:  # list entries in different places are different people,
        return bool(r['qid'] and r['qid'] == p['wikidata'] and all(upgrade(x, r) for x in other))  # unless Wikidata ties a later, higher award to them (moved)
    return any(same_award(a, r) for a in p['awards'])  # press residences are noisy

def pick(ps, r):  # among fitting people prefer one whose residence matches
    c = [p for p in ps if fits(p, r)]
    return next((p for p in c if r['residence'] and any(same_place(r['residence'], x['residence']) for x in p['_recs'] if x['residence'])), c[0] if c else None)

def add(p, r):
    p['_recs'].append(r)
    for f, v in (('name', r['name']), ('wikidata', r['qid']), ('occupation', r['occupation']), ('residence', r['residence']), ('titles', r.get('titles'))): p[f] = first(p[f], v)
    if official(r): p['name'] = r['name']
    w = weight(r)
    # each grade is conferred only once per person; within a year, a conflicting grade from a non-list source is the same award, not a second one
    a = next((a for a in p['awards'] if a['grade'] == r['grade'] != 'unbekannt'), None) or next((a for a in p['awards'] if close(a, r) and (
        r['grade'] in (a['grade'], 'unbekannt') or a['grade'] == 'unbekannt' or min(a['_w'], w) < 10)), None)
    if not a:
        a = dict(grade=r['grade'], date=None, year=r['year'], year_estimated=r.get('year_estimated', False), announced=None, place=None, presented_by=None, reason=None, sources=[], _votes=Counter(), _w=0); p['awards'].append(a)
    if r['grade'] != 'unbekannt': a['_votes'][r['grade']] += w
    a['_w'], a['grade'] = max(a['_w'], w), a['_votes'].most_common(1)[0][0] if a['_votes'] else 'unbekannt'
    if a.get('year_estimated') and not r.get('year_estimated'):
        a['year'], a['year_estimated'] = r['year'], False
    a['announced'] = first(a['announced'], r.get('announced'))
    if r['date'] and not a['date']: a['date'], a['year'], a['year_estimated'] = r['date'], r['year'], False
    a['place'], a['presented_by'] = first(a['place'], r['place']), first(a['presented_by'], r['presented_by'])
    if r['reason'] and len(r['reason']) > len(a['reason'] or ''): a['reason'] = r['reason']
    if source_key(r['source']) not in {source_key(s) for s in a['sources']}: a['sources'].append(r['source'])

def order(r): return (r['qid'] is None, r['year'], not official(r), r['source']['via'] == 'bundesanzeiger')

def same_surname(x, y):  # "Schwenk" / "Schwenk-Anger", "Hass" / "Hase", "Hoppe-Waßmuth" / "Humpe-Waßmuth"; not "Müller-Schmidt" / "Weber-Schmidt"
    a, b = split_name(x['name'])[1], split_name(y['name'])[1]
    return bool(a and b) and (a == b or set(a.split('-')) <= set(b.split('-')) or set(b.split('-')) <= set(a.split('-')) or difflib.SequenceMatcher(None, a, b).ratio() >= .7)

def days(a, b): return abs((datetime.date.fromisoformat(a[:10]) - datetime.date.fromisoformat(b[:10])).days)

def complementary(x, y):
    """Two list-backed records no single source names twice: one entry transcribed differently by the BPR page, the Bundesanzeiger and the
    WikiProjekt mirror ("Hass" / "Hase", "Bernhard Bachof" / "Bernhard Wilhelm Hugo Rudolf Bachof", "Gummersbach" / "Gummbersbach")."""
    rx, ry = ([r for r in p['_recs'] if official(r) and r.get('announced')] for p in (x, y))
    if not rx or not ry or {r['source']['via'] for r in rx} & {r['source']['via'] for r in ry}: return False
    (gx, lx), (gy, ly) = split_name(x['name']), split_name(y['name'])
    if not (gx and gy and same_given(gx, gy, loose=True) and same_surname(x, y)): return False
    place, near = same_place(x['residence'], y['residence']), difflib.SequenceMatcher(None, norm(x['name']), norm(y['name'])).ratio() >= .9
    if not (place or near): return False
    return any(a['grade'] == b['grade'] and (days(a['announced'], b['announced']) <= 45 or (place and lx == ly and days(a['announced'], b['announced']) <= 366)) for a in rx for b in ry)  # one grade is conferred once

def same_person(x, y, names, common=frozenset()):  # across name buckets: 'qid', 'transcription' (two renderings of one list entry), 'fuzzy' (nickname, typo, hyphenation) or None
    ox, oy = ([a for a in p['awards'] if a['_w'] == 10] for p in (x, y))  # awards backed by an official list
    if any(listed_apart(x['_recs'], r) for r in y['_recs']): return None
    if x['wikidata'] and y['wikidata']:  # but list entries in different places are namesakes sharing a wiki link unless they are successive upgrades
        return 'qid' if x['wikidata'] == y['wikidata'] and (same_place(x['residence'], y['residence']) or all(upgrade(a, b) for a in ox for b in oy)) else None
    (gx, _), (gy, _) = split_name(x['name']), split_name(y['name'])
    gen = [names.get(NICK.get(f := p['name'].split()[0].casefold(), f), set()) or names.get(f, set()) for p in (x, y)]  # "Bruni" is Brunhilde
    if ({'m'}, {'w'}) in ((gen[0], gen[1]), (gen[1], gen[0])): return None
    if ox and oy and complementary(x, y): return 'transcription'
    if not gx or not gy or not same_given(gx, gy) or not same_place(x['residence'], y['residence']) or not same_surname(x, y): return None
    if not any(close(a, b) for a in x['awards'] for b in y['awards']): return None
    if ox and oy:  # two list entries: only a different transcription of the same entry
        return 'transcription' if any(a['announced'] == b['announced'] and a['grade'] == b['grade'] for a in ox for b in oy) and difflib.SequenceMatcher(None, norm(x['name']), norm(y['name'])).ratio() >= .85 else None
    if not (x['residence'] and y['residence']) and split_name(x['name'])[1] in common:  # a placeless report of a common surname needs the first given name: "Rudi Müller" is not "Hans-Rudolf Müller", but "Rebecca Horn" is "Heidemarie Rebecca Horn"
        fx, fy = (NICK.get(g[0], g[0]) for g in (gx, gy))
        if fx != fy and difflib.SequenceMatcher(None, fx, fy).ratio() < .85: return None
    return 'fuzzy'

def regroup(people, names):
    up = list(range(len(people)))
    qid = {i: p['wikidata'] for i, p in enumerate(people)}
    off = {i: any(a['_w'] == 10 for a in p['awards']) for i, p in enumerate(people)}  # group contains an official list entry
    def find(i):
        while up[i] != i: up[i] = up[up[i]]; i = up[i]
        return i
    def join(i, j, how):
        a, b = find(i), find(j)
        if a == b or (qid[a] and qid[b] and qid[a] != qid[b]) or (how == 'fuzzy' and off[a] and off[b]): return  # never chain two list entries via a press record
        up[b], qid[a], off[a] = a, qid[a] or qid[b], off[a] or off[b]
    ix = defaultdict(list)
    for i, p in enumerate(people):
        l = split_name(p['name'])[1]
        lists = [r for r in p['_recs'] if official(r) and r.get('announced')]
        months = {f'g:{r["grade"]}:{m}' for r in lists for m in (r['announced'][:7], (datetime.date.fromisoformat(r['announced'][:7] + '-01') + datetime.timedelta(days=31)).isoformat()[:7])
                  } if lists and len({r['source']['via'] for r in lists}) < 3 else set()  # a list entry missing from one source may sit under a misspelt surname in another
        for k in ({f'q:{p["wikidata"]}'} if p['wikidata'] else set()) | {f'l:{x}' for x in {l, *l.split('-')} if x} | months: ix[k].append(i)
    common = {s for s, n in Counter(split_name(p['name'])[1] for p in people).items() if n > 25}
    for v in ix.values():
        for i, j in itertools.combinations(v, 2):
            if (how := same_person(people[i], people[j], names, common)): join(i, j, how)
    first_names = defaultdict(list)
    for i, p in enumerate(people):
        if (g := split_name(p['name'])[0]): first_names[g[0]].append(i)
    for i, p in enumerate(people):  # monarchs known by one name: "Mathilde" -> the one "Mathilde d'Udekem d'Acoz" with the same award
        if not split_name(p['name'])[0] and ROYAL.search(p['occupation'] or ''):
            c = [j for j in first_names[split_name(p['name'])[1]] if any(same_award(a, b) for a in p['awards'] for b in people[j]['awards'])]
            if len(c) == 1: join(c[0], i, 'qid')
    groups = defaultdict(list)
    for i, p in enumerate(people): groups[find(i)].append(p)
    out = []
    for g in groups.values():
        if len(g) == 1: out.append(g[0]); continue
        p = new_person(g[0]['_key'])
        for r in sorted((r for x in g for r in x['_recs']), key=order): add(p, r)
        out.append(p)
    return out

def fold(p):
    """An award of unknown grade known only from press or Wikipedia, beside an award the lists announce, is that award: a later handover,
    a re-dated or misdated report ("Düzen Tekkal (43) ist am 30. September … geehrt worden" read as 2018), not a second, unlisted one.
    Its sources, reason, place and presenter join the listed award closest in year; its date and year do not."""
    listed = [a for a in p['awards'] if a['_w'] == 10]
    for u in [a for a in p['awards'] if a['grade'] == 'unbekannt' and a['_w'] < 10] if listed else []:
        t = min(listed, key=lambda a: abs(a['year'] - u['year']))
        t['sources'] += [s for s in u['sources'] if source_key(s) not in {source_key(x) for x in t['sources']}]
        if u['reason'] and len(u['reason']) > len(t['reason'] or ''): t['reason'] = u['reason']
        t['place'], t['presented_by'] = first(t['place'], u['place']), first(t['presented_by'], u['presented_by'])
        p['awards'].remove(u)

def source_key(s):
    return (s['url'], s['via'], s.get('mirror'))

def preserve_ids(people, previous):
    # Exact shared source excerpts identify unchanged people across residence/name corrections.
    index = defaultdict(set)
    for p in previous:
        for a in p['awards']:
            for s in a['sources']:
                for q in {s.get('quote'), s.get('extraction_quote')} - {None}: index[(s['url'], q)].add(p['id'])  # repair may have replaced the extracted quote
    names = defaultdict(set)
    for p in previous: names[(norm(p['name']), p['wikidata'])].add(p['id'])
    annotation_path = DATA / 'party.json'
    annotated = {x['id'] for x in json.loads(annotation_path.read_text())} if annotation_path.exists() else set()
    candidates = []
    for p in people:  # a unique shared excerpt, else a unique name and QID, else the excerpt match with a party annotation, else the first excerpt match
        ids = set().union(*(index.get((s['url'], s.get('quote')), set()) for a in p['awards'] for s in a['sources']))
        named, preferred = names.get((norm(p['name']), p['wikidata']), set()), ids & annotated
        candidates.append(next(iter(ids)) if len(ids) == 1 else next(iter(named)) if len(named) == 1 else next(iter(preferred)) if len(preferred) == 1 else min(ids, default=None))
    counts = Counter(candidates)
    for p, ident in zip(people, candidates):
        if ident and counts[ident] == 1: p['id'] = ident
    used = set()
    for p in people:
        if p['id'] in used:
            p['id'] = h(p['id'] + p['name'] + (p['residence'] or '') + str(p['awards']))[:12]
        used.add(p['id'])

def repair_annotation_ids(people, previous):
    path = DATA / 'party.json'
    if not path.exists(): return
    annotations = json.loads(path.read_text())
    current = {p['id']: p for p in people}
    index = defaultdict(set)
    for p in people:
        for a in p['awards']:
            for s in a['sources']:
                if s.get('quote'): index[(s['url'], s['quote'])].add(p['id'])
    old = {p['id']: p for p in previous}
    alias_path = DATA / 'name_aliases.json'
    aliases = json.loads(alias_path.read_text()) if alias_path.exists() else {}
    remapped = []
    for row in annotations:
        if row['id'] not in current:
            p = old.get(row['id'])
            ids = set().union(*(index.get((s['url'], s.get('extraction_quote') or s.get('quote')), set()) for a in p['awards'] for s in a['sources'])) if p else set()
            if len(ids) != 1:
                name = aliases.get(row['name'], row['name'])
                named = {p['id'] for p in people if tokens(name) == tokens(p['name'])}
                if not named: named = {p['id'] for p in people if identity_matches(name, p['name'])}
                ids = ids & named if ids else named
            if len(ids) != 1: raise ValueError(f"Ambiguous party annotation migration: {row['name']}")
            row = {**row, 'id': next(iter(ids)), 'previous_id': row['id']}
        remapped.append(row)
    groups = defaultdict(list)
    for row in remapped: groups[row['id']].append(row)
    consolidated = []
    for rows in groups.values():
        if len({r['party'] for r in rows}) > 1:
            raise ValueError(f"Conflicting party annotations: {[(r['name'], r['party']) for r in rows]}")
        row = rows[0]
        if len(rows) > 1: row = {**row, 'merged_annotations': rows}
        consolidated.append(row)
    path.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2) + '\n')

def run():
    previous = json.loads((DATA / 'bvk.json').read_text()) if (DATA / 'bvk.json').exists() else []
    aliases_path = DATA / 'name_aliases.json'
    aliases = json.loads(aliases_path.read_text()) if aliases_path.exists() else {}
    rs = []
    for r in records():
        r['name'] = aliases.get(r['name'], r['name'])
        if norm(r['name']): rs.append(r)
    by = defaultdict(list)
    for r in check_qids(rs):
        by[name_key(r['name'])].append(r)  # "Hans-Heinrich" and "Hans Heinrich" share a bucket
    people = []
    for key, rs in by.items():
        ps = []
        for r in sorted(rs, key=order):
            if not (p := pick(ps, r)): ps.append(p := new_person(key))
            add(p, r)
        people += ps
    people = regroup(people, enrich.given_names())
    for p in people: fold(p)
    shared = defaultdict(list)
    for p in people:
        if p['wikidata']: shared[p['wikidata']].append(p)
    for ps in shared.values():  # a QID left on several people came from list links to a namesake's article: keep it where Wikipedia/Wikidata itself names the award
        if len(ps) > 1 and len(own := [p for p in ps if any(r['source']['via'] in ('dewiki', 'wikidata') for r in p['_recs'])]) == 1:
            for p in ps:
                if p is not own[0]: p['wikidata'] = None
    for p in people:
        spellings = Counter(r['name'] for r in p['_recs'] if official(r))
        if spellings: p['name'] = max(spellings, key=lambda n: (spellings[n], len(tokens(n)), n == p['name']))  # the spelling most official sources agree on; on a tie the fuller name ("Bernhard Bachof" is shortened)
        for a in p['awards']:  # a list announces conferrals already made: a later press or Wikipedia year is the handover, not the award year
            if not (ann := min((s['published'] for s in a['sources'] if official({'source': s}) and s.get('published')), default=None)): continue
            listed, est = datetime.date.fromisoformat(ann[:10]), (datetime.date.fromisoformat(ann[:10]) - datetime.timedelta(days=120)).year
            if a['date'] and (listed - (d := datetime.date.fromisoformat(a['date']))).days > 300 and not any(
                    s.get('published') and not official({'source': s}) and -30 <= (datetime.date.fromisoformat(s['published'][:10]) - d).days <= 60 for s in a['sources']):
                a['date'], a['year'], a['year_estimated'] = None, est, True  # an undated article whose year was guessed: "Tag der Deutschen Einheit" 2017 for the October 2018 list
            if a['year'] > listed.year: a['year'], a['year_estimated'] = listed.year, True  # at most the listing year; a reported year still beats the 120-day estimate
    for p in people: p['awards'] = [a for a in p['awards'] if a['year'] >= MIN_YEAR]
    people = [p for p in people if p['awards']]
    for p in people:
        p['id'] = h(p.pop('_key') + (p['wikidata'] or p['residence'] or ''))[:12]
        del p['_recs']
        for a in p['awards']: del a['_votes'], a['_w']
    people.sort(key=lambda p: (min(a['year'] for a in p['awards']), p['name']))
    preserve_ids(people, previous)
    repair_annotation_ids(people, previous)
    enrich.run(people)
    (DATA / 'bvk.json').write_text(json.dumps(people, ensure_ascii=False, indent=1))
    stats(people)

def stats(people=None):
    people = people or json.loads((DATA / 'bvk.json').read_text())
    aw = [a for p in people for a in p['awards']]
    print(f'{len(people)} people, {len(aw)} awards')
    print('year ', sorted(Counter(a['year'] for a in aw).items()))
    print('grade', Counter(a['grade'] for a in aw).most_common())
    print('via  ', Counter(s['via'] for a in aw for s in a['sources']).most_common())
    print('with reason', sum(bool(a['reason']) for a in aw), 'with date', sum(bool(a['date']) for a in aw))
