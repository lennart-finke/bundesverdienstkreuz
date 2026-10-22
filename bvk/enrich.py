import functools, json, re, urllib.parse
from collections import Counter, defaultdict
from tenacity import retry, stop_after_attempt, wait_exponential
from .common import CACHE, DATA, MON, UA, docs, h, http

WQ = 'https://qlever.dev/api/wikidata'
PRE = ('PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> '
       'PREFIX skos: <http://www.w3.org/2004/02/skos/core#> PREFIX p: <http://www.wikidata.org/prop/> PREFIX ps: <http://www.wikidata.org/prop/statement/> PREFIX pq: <http://www.wikidata.org/prop/qualifier/> PREFIX wikibase: <http://wikiba.se/ontology#> '
       'PREFIX psv: <http://www.wikidata.org/prop/statement/value/> ')
PEOPLE_Q = ('SELECT ?p ?b ?prec ?d ?g ?h ?l WHERE { VALUES ?p { %s } OPTIONAL { ?p p:P569/psv:P569 ?bv . ?bv wikibase:timeValue ?b ; wikibase:timePrecision ?prec } '
            'OPTIONAL { ?p wdt:P570 ?d } OPTIONAL { ?p wdt:P21 ?g } OPTIONAL { ?p wdt:P31 ?h FILTER(?h = wd:Q5) } OPTIONAL { ?p rdfs:label ?l FILTER(LANG(?l) IN ("de","mul")) } }')
GENDER = {'Q6581097': 'm', 'Q6581072': 'w', 'Q2449503': 'm', 'Q1052281': 'w'}  # incl. trans man/woman
NOBLE_G = {'freiherr': 'm', 'graf': 'm', 'freifrau': 'w', 'gräfin': 'w'}
NAME_G = {**dict.fromkeys(['marion', 'inge', 'heike', 'hanna', 'uta', 'ursel', 'simone'], 'w'), **dict.fromkeys(['max', 'boris', 'giesbert'], 'm')}  # names Wikidata marks ambiguous but German usage doesn't
FEM = re.compile(r'\b[A-ZÄÖÜ]\w*(erin|orin|istin|antin|entin|eurin|ärztin|ologin|änderin|frau|ndin)\b')
# residence -> municipality (AGS), state, country
GEM_Q = ('SELECT ?g ?ags ?l ?t WHERE { ?g p:P439 ?s . ?s ps:P439 ?ags . MINUS { ?s wikibase:rank wikibase:DeprecatedRank } FILTER NOT EXISTS { ?s pq:P582 [] } FILTER NOT EXISTS { ?g wdt:P576 [] } '
         '{ ?g rdfs:label ?l BIND(0 AS ?t) } UNION { ?g skos:altLabel ?l BIND(1 AS ?t) } FILTER(LANG(?l) IN ("de", "mul")) }')
POP_Q = 'SELECT ?g ?n ?d WHERE { ?g wdt:P439 [] ; p:P1082 ?s . ?s ps:P1082 ?n . OPTIONAL { ?s pq:P585 ?d } FILTER NOT EXISTS { ?g wdt:P576 [] } }'
SUB_Q = 'SELECT ?l ?ags WHERE { ?x wdt:P131 ?g . ?g wdt:P439 ?ags . ?x wdt:P31/wdt:P279* wd:Q486972 ; rdfs:label ?l FILTER(LANG(?l) IN ("de", "mul")) }'  # settlements inside a municipality
KREIS_Q = 'SELECT ?key ?l WHERE { ?k wdt:P440 ?key ; rdfs:label ?l . FILTER(STRLEN(?key) = 5) FILTER(LANG(?l) IN ("de", "mul")) FILTER NOT EXISTS { ?k wdt:P576 [] } }'
LAND_Q = ('SELECT ?c ?l ?t WHERE { VALUES ?type { wd:Q3624078 wd:Q15634554 } ?c wdt:P31 ?type . FILTER NOT EXISTS { ?c wdt:P576 [] } { ?c rdfs:label ?l FILTER(LANG(?l) IN ("de", "mul")) BIND(0 AS ?t) } '
          'UNION { ?c skos:altLabel ?l FILTER(LANG(?l) IN ("de", "mul")) BIND(1 AS ?t) } UNION { ?c wdt:P298 ?l BIND(1 AS ?t) } }')
STATES = {'01': 'Schleswig-Holstein', '02': 'Hamburg', '03': 'Niedersachsen', '04': 'Bremen', '05': 'Nordrhein-Westfalen', '06': 'Hessen', '07': 'Rheinland-Pfalz', '08': 'Baden-Württemberg',
          '09': 'Bayern', '10': 'Saarland', '11': 'Berlin', '12': 'Brandenburg', '13': 'Mecklenburg-Vorpommern', '14': 'Sachsen', '15': 'Sachsen-Anhalt', '16': 'Thüringen'}
LANDNAME = {'Königreich Dänemark': 'Dänemark', 'Königreich der Niederlande': 'Niederlande', 'Vereinigte Staaten': 'USA', 'Volksrepublik China': 'China'}
LANDEXTRA = {'dänemark': 'Dänemark', 'niederlande': 'Niederlande', 'holland': 'Niederlande', 'großbritannien': 'Vereinigtes Königreich', 'england': 'Vereinigtes Königreich',
             'schottland': 'Vereinigtes Königreich', 'wales': 'Vereinigtes Königreich', 'nordirland': 'Vereinigtes Königreich', 'russischeföderation': 'Russland'}
# foreign cities the lists name without a country ("Kieven, Elisabeth, Rom", "Dressler, Gerd, Mexiko-Stadt"); their German namesakes are villages or hamlets
CITIES = {'wien': 'Österreich', 'salzburg': 'Österreich', 'graz': 'Österreich', 'innsbruck': 'Österreich', 'prag': 'Tschechien', 'rom': 'Italien', 'mailand': 'Italien',
          'paris': 'Frankreich', 'london': 'Vereinigtes Königreich', 'brüssel': 'Belgien', 'luxemburg': 'Luxemburg', 'warschau': 'Polen', 'krakau': 'Polen', 'budapest': 'Ungarn',
          'bukarest': 'Rumänien', 'moskau': 'Russland', 'kiew': 'Ukraine', 'madrid': 'Spanien', 'lissabon': 'Portugal', 'athen': 'Griechenland', 'zürich': 'Schweiz', 'genf': 'Schweiz',
          'basel': 'Schweiz', 'bern': 'Schweiz', 'jerusalem': 'Israel', 'telaviv': 'Israel', 'newyork': 'USA', 'washington': 'USA', 'washingtondc': 'USA', 'mexikostadt': 'Mexiko', 'lima': 'Peru', 'tokio': 'Japan'}
ABBR = [(r'\ba\.\s*d\.\s*', 'an der '), (r'\bi\.\s*d\.\s*', 'in der '), (r'\bo\.\s*d\.\s*', 'ob der '), (r'\bv\.\s*d\.\s*', 'vor der '), (r'\ba\.\s*', 'am '), (r'\bi\.\s*', 'im '), (r'\bb\.\s*', 'bei '), (r'\bst\.\s*', 'sankt ')]

@retry(stop=stop_after_attempt(5), wait=wait_exponential(10, max=120), reraise=True)
def sparql(q, cache):
    p = CACHE / cache
    if not p.exists():
        r = http.post(WQ, data={'query': PRE + q}, headers={'Accept': 'text/tab-separated-values', 'User-Agent': UA}, timeout=300); r.raise_for_status()
        p.write_text(r.text)
    return [[c.strip('"<>') for c in l.split('\t')] for l in p.read_text().splitlines()[1:]]

def lab(v): return v.rsplit('"@', 1)[0]

def expand(s):
    s = s.casefold()
    for a, b in ABBR: s = re.sub(a, b, s)
    return s

def pkey(s): return re.sub(r'[\W\d_]', '', expand(s))

def base(s): return re.split(r'\s*[(/,]|\s+(?:an der|am|im|in der|in|an|bei|ob der|vor der|unter|auf der)\s+', expand(s), maxsplit=1)[0]  # "Radolfzell am Bodensee" -> "radolfzell"

def gemeinden():
    """Current German municipalities from Wikidata: AGS -> name, population, labels."""
    pop = {}
    for g, n, d in sparql(POP_Q, 'wd_gemeinde_pop.tsv'):
        d = d[:10] if d[:1].isdigit() else ''  # unknown date -> blank node IRI
        if d >= pop.get(g, (0, ''))[1]: pop[g] = (int(float(n.split('"')[0])), d)
    new = int(max(d for _, d in pop.values())[:4])
    gs = {}
    for g, a, l, t in sparql(GEM_Q, 'wd_gemeinden.tsv'):
        if g in pop and pop[g][1][:4] >= str(new - 3):  # merged municipalities often lack P576 but stop getting population figures
            x = gs.setdefault(a.split('"')[0], {'name': None, 'pop': pop[g][0], 'labels': []})
            if t == '0' and (not x['name'] or l.endswith('@de')): x['name'] = lab(l)  # prefer de over mul label
            x['labels'].append(lab(l))
    return gs

def locator():
    """residence -> (country, state, AGS of the municipality)."""
    gs = gemeinden()
    ix = [defaultdict(set) for _ in range(5)]  # label, alias, base name, first part of a hyphenated name, settlement inside municipality -> AGS
    for a, x in gs.items():
        for l in x['labels']: ix[0 if l == x['name'] else 1][pkey(l)].add(a); ix[2][pkey(base(l))].add(a)
        if '-' in x['name'] and len(pre := x['name'].split('-')[0]) >= 5 and ' ' not in pre: ix[3][pkey(pre)].add(a)  # "Dessau" is Dessau-Roßlau, not the hamlet in Burggen
    for l, a in sparql(SUB_Q, 'wd_ortsteile.tsv'):
        if a in gs: ix[4][pkey(lab(l))].add(a)
    hint = defaultdict(set)  # district or state named in the residence, e.g. "Hirschaid, Landkreis Bamberg"
    for k, l in sparql(KREIS_Q, 'wd_kreise.tsv'): hint[pkey(re.sub(r'^(Landkreis|Kreis|Stadtkreis|Regionalverband) ', '', lab(l)))].add(k)
    for k, n in STATES.items(): hint[pkey(n)].add(k)
    for r, k in (('Westfalen', '05'), ('Westf.', '05'), ('Ostwestfalen', '05'), ('Oberbayern', '09'), ('Franken', '09'), ('Oberpfalz', '09'), ('Allgäu', '09')): hint[pkey(r)].add(k)  # regions named after a slash or in brackets
    rows = sparql(LAND_Q, 'wd_staaten.tsv')
    name = {c: LANDNAME.get(lab(l), lab(l)) for c, l, t in sorted(rows, key=lambda r: r[1].endswith('@de')) if t == '0'}
    alias = defaultdict(set)
    for c, l, _ in rows:
        if c in name and (k := pkey(lab(l))): alias[k].add(name[c])  # skip aliases without letters (e.g. flag emoji)
    land = {k: min(v) for k, v in alias.items() if len(v) == 1} | {pkey(lab(l)): name[c] for c, l, t in rows if t == '0' and c in name} | LANDEXTRA  # ambiguous aliases ("Kongo") dropped

    def locate(s):
        parts = [x for x in re.split(r'\s*[(),/]\s*', s) if x]
        if (c := next((land[k] for x in parts[::-1] if (k := pkey(x)) in land), None)) and c != 'Deutschland': return c, None, None
        if parts and (c := CITIES.get(pkey(parts[-1]))) and len(parts) <= 2: return c, None, None  # "Rom", "Monsignore, Prag"
        if pkey(s) not in ix[0] and (st := next((n for n in STATES.values() if pkey(n) == pkey(s)), None)): return 'Deutschland', st, None  # residence is a state, not Berlin/Hamburg/Bremen
        s = re.split(r',?\s+(?:OT|ST|Ortsteil|Stadtteil)\.?\s+', s)[0]
        head, *rest = re.split(r'\s*[,/]\s*', s)
        paren = re.findall(r'\((.*?)\)', s)
        hk = set().union(*(hint.get(pkey(re.sub(r'^(Landkreis|Kreis|Lkr\.|Lk\.|LK)\s*', '', x)), set()) for x in rest + paren))
        for d in ix:
            for v in [s, head, re.sub(r'\s*\(.*?\)', '', head), *paren, *rest[::-1], head.split('-')[0]]:
                if (k := pkey(v)) and (c := d.get(k)):
                    if d is ix[1]: c = c | ix[3].get(k, set())  # an alias of a village ("Dessau" in Burggen) against the town it names (Dessau-Roßlau)
                    if d is ix[0] and (b := {a for a in ix[2].get(k, ()) if pkey(base(gs[a]['name'])) == k}):  # the exact label may be a village while the town goes by "Halle (Saale)", "Halle (Westf.)"; not an alias ("Nußbaum" in Neulingen)
                        if hk and not {a for a in c if a[:5] in hk or a[:2] in hk}: c = {a for a in b if a[:5] in hk or a[:2] in hk} or c  # "Halle/Westfalen"
                        elif not hk and (o := sorted(b | c, key=lambda a: -gs[a]['pop'])) and o[0] not in c and gs[o[0]]['pop'] >= 10 * gs[o[1]]['pop']: c = {o[0]}  # "Halle" = Halle (Saale)
                    c = sorted({a for a in c if a[:5] in hk or a[:2] in hk} or c, key=lambda a: -gs[a]['pop'])
                    if len(c) == 1 or gs[c[0]]['pop'] >= 10 * gs[c[1]]['pop']: return 'Deutschland', STATES[c[0][:2]], c[0]  # "Münster" = the city, not Münster (Hessen)
                    return ('Deutschland', STATES[c[0][:2]], None) if len({a[:2] for a in c}) == 1 else (None, None, None)  # same name in several states
        return None, None, None
    return functools.lru_cache(maxsize=None)(locate)

def places(ps):
    locate = locator()
    for p in ps: p['country'], p['state'], p['ags'] = locate(p['residence'] or '')

_locate = None

def municipality(residence):
    """AGS of the German municipality a residence lies in ("Gresaubach" and "Lebach" are both Lebach); None if unresolved, abroad or not cached."""
    global _locate
    if not residence or not (CACHE / 'wd_gemeinden.tsv').exists(): return None
    _locate = _locate or locator()
    return _locate(residence)[2]

def given_names():
    """Given name -> genders ('m', 'w', 'u' = unisex) from Wikidata."""
    names = {}
    for n, t in sparql('SELECT ?n ?t WHERE { VALUES ?t { wd:Q12308941 wd:Q11879590 wd:Q3409032 } ?g wdt:P31 ?t . ?g rdfs:label ?n FILTER(LANG(?n) IN ("de","en","mul")) }', 'given_names.tsv'):
        names.setdefault(lab(n).casefold(), set()).add({'Q12308941': 'm', 'Q11879590': 'w'}.get(t.rsplit('/', 1)[1], 'u'))
    return names

def wd_people(qs):
    """QID -> born (only day or year precision; century/decade values are dropped), died, gender, human, first tokens of labels. Cached per batch."""
    qs, out = sorted(set(qs)), {}
    for i in range(0, len(qs), 500):
        batch = qs[i:i + 500]
        for q, b, prec, d, g, hu, l in sparql(PEOPLE_Q % ' '.join(f'wd:{q}' for q in batch), f'wd_people_{h(" ".join(batch))[:12]}.tsv'):
            x = out.setdefault(q.rsplit('/', 1)[1], {'labels': set(), 'human': False})
            if l: x['labels'].add(l.split('"@')[0].split()[0].casefold())
            if b[:1] in '12' and prec.isdigit() and int(prec) >= 9 and 'born' not in x: x['born'] = b[:10] if int(prec) >= 11 else b[:4]
            if d[:1] in '12': x['died'] = min(x.get('died', '9999'), d[:10])
            if g: x['gender'] = GENDER.get(g.rsplit('/', 1)[1], 'd')
            if hu: x['human'] = True
    return out

def press_age(surname):
    """'Almut Opolka (50)', 'der 74-jährige Lehrer Peter Fehse'; not 'als 19-Jähriger kam Icek Ostrowicz' (1947), 'zum 25-jährigen Jubiläum holte Markus Müller',
    'die 30-jährige Tätigkeit Ekkehard Palandts': only capitalised words between, none of them a span of time or a genitive of the surname."""
    last = re.escape(surname)
    return re.compile(last + r'\b\W{0,3}\((\d{2})\)|(?<![Aa]ls )(?<!mit )(?<![Zz]um )\b(\d{2})[- ][Jj]ährigen?r?\s+'
                      r'(?:(?:von|van|de|zu|ten|ter)\s+|(?![\w-]*(?:keit|schaft|ung|zeit|jubiläum|dienst|arbeit|engagement)\b)[A-ZÄÖÜ][\w.-]*\s+){0,3}?' + last + r'\b')  # "der 57-jährige Autohändler van Neer"

def run(people=None):
    ps = people or json.loads((DATA / 'bvk.json').read_text())
    names, wd = given_names(), wd_people(p['wikidata'] for p in ps if p['wikidata'])
    D = {d['url']: d for _, d in docs() if d['src'] in ('dewiki', 'search')}
    host = lambda u: urllib.parse.urlsplit(u).hostname
    stock = {k for k, n in Counter((host(u), d['date']) for u, d in D.items() if d['date']).items() if n >= 10}  # one date on many pages of a site: not a publication date
    for p in ps:
        ss = [s for a in p['awards'] for s in a['sources']]
        w = wd.get(p['wikidata'], {})
        if w and p['name'].split()[0].casefold() not in w['labels']: w = {}  # QID likely belongs to someone else (e.g. spouse)
        born, bsrc = (w['born'], 'wikidata') if w.get('born') and w['born'][:1] in '12' else (None, None)
        if not born:
            for s in ss:
                if s['via'] == 'dewiki' and s['url'] in D and (m := re.search(r'\(\*\s*(?:(\d{1,2})\.\s*(\w+)\s+)?(1[89]\d\d|20\d\d)', D[s['url']]['text'][:3000])):
                    born = f'{m[3]}-{MON[m[2]]:02d}-{int(m[1]):02d}' if m[2] in MON else m[3]; bsrc = 'dewiki'; break
        if not born and ' und ' not in p['name']:
            age = press_age(p['name'].split()[-1])
            for a, s in ((a, s) for a in p['awards'] for s in a['sources']):
                d = D.get(s['url'])
                if d and d['src'] == 'search' and (m := age.search(d['text'])):
                    y = int(m2[0]) if (m2 := re.search(r'\b(?:19|20)\d\d\b', s['published'] or d['date'] or '')) else None  # page dates also come as "Tue, 12 Mar 2019"
                    if not y or y > a['year'] + 2 or (y < a['year'] and (host(s['url']), d['date']) in stock):  # a report on this award, re-dated years later ("Almut Opolka (50)" from 2016, dated 2022)
                        y = int((a['date'] or '')[:4] or a['year'])  # or under a date a site gives all its pages (2019-09-05 on Saxon pages about 2016 and 2021)
                    born, bsrc = str(y - int(m[1] or m[2])), 'press-age'; break  # ±1 year
        p['born'], p['born_source'] = born, bsrc
        for a in p['awards']:
            b = born
            a['age'] = (int(a['date'][:4]) - int(b[:4]) - ((a['date'][5:10] < b[5:10]) if len(b) == 10 else 0)) if b and a['date'] else (a['year'] - int(b[:4]) if b else None)
        if any(not 18 <= a['age'] <= 110 for a in p['awards'] if a['age'] is not None):  # wrong QID / misparsed age
            p['born'] = p['born_source'] = None
            for a in p['awards']: a['age'] = None
        p['gender'], p['gender_source'] = (w['gender'], 'wikidata') if w.get('gender') else (None, None)
    given = lambda p: [t.casefold() for t in p['name'].split()[:-1] if not re.search(r'\.$', t)]
    prior = {}
    for p in ps:
        if p['gender_source'] == 'wikidata' and given(p): prior.setdefault(given(p)[0], Counter())[p['gender']] += 1
    def by_name(n):
        c = names.get(n) or names.get(n.split('-')[0]) or set()
        if len(c) == 1 and 'u' not in c: return next(iter(c))
        if (k := prior.get(n)) and sum(k.values()) >= 3 and k.most_common(1)[0][1] / sum(k.values()) >= .8: return k.most_common(1)[0][0]
    for p in ps:
        if p['gender'] or ' und ' in p['name']: continue
        g = next((NOBLE_G[t] for t in given(p) if t in NOBLE_G), None)
        g = g or next((x for t in given(p) if (x := NAME_G.get(t) or by_name(t))), None)  # in name order: "Herbert Marion Pichler" is a man
        src = 'first-name' if g else None
        if not g and p['occupation'] and FEM.search(p['occupation']): g, src = 'w', 'occupation'
        p['gender'], p['gender_source'] = g, src
    places(ps)
    if not people: (DATA / 'bvk.json').write_text(json.dumps(ps, ensure_ascii=False, indent=1))
    print('born', Counter(p['born_source'] for p in ps).most_common(), 'gender', Counter((p['gender'], p['gender_source']) for p in ps).most_common())
    print('place', Counter('abroad' if p['country'] not in (None, 'Deutschland') else 'municipality' if p['ags'] else 'state only' if p['state'] else 'unresolved' if p['residence'] else 'no residence' for p in ps).most_common())
