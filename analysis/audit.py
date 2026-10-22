# Consistency audit of data/bvk.json: flags likely false records (phantom awards, split/merged people, wrong QIDs, garbled names,
# fake-precision dates, wrong places) and summarises missing information. Writes cache/audit.json; no LLM calls.
# uv run python -m analysis.audit
import json, re
from collections import defaultdict
from bvk.common import CACHE, DATA, MONTHS, docs
from bvk.enrich import STATES, base, gemeinden, pkey, sparql
from bvk.merge import RANK, norm
from bvk.official import OFFICIAL as OFF

JOBS = r'^(Pianist|Schauspielerin?|Schriftsteller(in)?|Facharbeiterin?|Chemikerin|Anonym|unbekannt|König(in)? der \w+|Kronprinz)\b'
STATE_ORDER = r'Verdienstorden des Landes|Landesverdienstorden|(Bayerischen|Niedersächsischen|Sächsischen|Thüringer|Hessischen) Verdienstorden|Ehrenzeichen des Freistaat|Landesehrennadel|Staatsmedaille'
MP = {'Günther': '01', 'Albig': '01', 'Kretschmann': '08', 'Kretschmer': '14', 'Tillich': '14', 'Haseloff': '15', 'Schulze': '15', 'Bouffier': '06', 'Rhein': '06', 'Wüst': '05', 'Laschet': '05',
      'Kraft': '05', 'Schwesig': '13', 'Sellering': '13', 'Söder': '09', 'Seehofer': '09', 'Weil': '03', 'Lies': '03', 'Dreyer': '07', 'Schweitzer': '07', 'Woidke': '12', 'Ramelow': '16', 'Voigt': '16',
      'Rehlinger': '10', 'Tschentscher': '02', 'Bovenschulte': '04', 'Wegner': '11', 'Giffey': '11'}

STOP = set('professor professorin graf grafin freiherr freifrau furst furstin prinz sir dame baroness monsignore msgr schwester bruder pater'.split())

def off(a): return any(s['via'] in OFF for s in a['sources'])
def vias(a): return sorted({s['via'] for s in a['sources']})
def key(n): return (t := norm(n).replace('-', ' ').split()) and (t[0][:3], t[-1])

def run():
    ps = json.loads((DATA / 'bvk.json').read_text())
    aw = [(p, a) for p in ps for a in p['awards']]
    text = {d['url']: d['text'] for _, d in docs('search')}
    flags = defaultdict(list)
    def flag(kind, p, a=None, **kw): flags[kind].append({'id': p['id'], 'name': p['name'], 'residence': p['residence'], **({'grade': a['grade'], 'year': a['year'], 'via': vias(a)} if a else {}), **kw})

    # awards: one conferral split into two grades; grade order; dates
    for p in ps:
        for i, a in enumerate(p['awards']):
            for b in p['awards'][i + 1:]:
                if a['grade'] != b['grade'] and 'unbekannt' not in (a['grade'], b['grade']) and abs(a['year'] - b['year']) <= 1:
                    flag('two_grades_within_a_year', p, a, other=(b['grade'], b['year'], vias(b)), both_official=off(a) and off(b))
        known = sorted((a for a in p['awards'] if a['grade'] != 'unbekannt'), key=lambda a: a['date'] or str(a['year']))
        for a, b in zip(known, known[1:]):
            if RANK.index(b['grade']) < RANK.index(a['grade']) and b['year'] - a['year'] > 1: flag('lower_grade_after_higher', p, b, earlier=(a['grade'], a['year']))
    for p, a in aw:
        if a['date'] and not re.fullmatch(r'\d{4}-\d\d-\d\d', a['date']): flag('malformed_date', p, a, date=a['date'])
        elif a['date'] and a['date'].endswith('-01-01') and set(vias(a)) & {'dewiki', 'wikidata'}: flag('year_only_date_as_jan_1', p, a, date=a['date'])
        pb, when = a['presented_by'] or '', a['date'] or f"{a['year']}-07-01"
        if ('Steinmeier' in pb and 'Bundespräsident' in pb and when < '2017-03-19') or ('Gauck' in pb and when > '2017-03-31'): flag('presenter_out_of_office', p, a, presented_by=pb, date=a['date'])
        if not off(a) and re.search(STATE_ORDER, ' '.join(filter(None, [s['quote'] for s in a['sources']] + [a['reason']]))): flag('maybe_state_order', p, a)
        if all(s['via'] == 'search' for s in a['sources']):
            if not any(s.get('quote_verified') for s in a['sources']): flag('press_only_quote_not_in_source', p, a)
            if mixed := [s['url'] for s in a['sources'] if re.search(STATE_ORDER + '|Kommunale Verdienstmedaille|Ehrenzeichen des Bayerischen', text.get(s['url'], ''))]:
                flag('press_only_from_page_listing_state_honours', p, a, urls=mixed)
        if a['reason'] and re.search(r'(im|das) (Dokument|Text)|nicht näher (beschrieben|erläutert|genannt)|(werden|sind) nicht (genannt|angegeben)', a['reason']): flag('reason_is_placeholder', p, a, reason=a['reason'])

    # people: names, residences
    for p in ps:
        n = p['name']
        if re.fullmatch(r'\S+', n) or re.search(JOBS, n) or re.search(r'[\[\]|{}]|\bund\b', n): flag('not_a_full_name', p)
        elif re.search(r'(\w)\1\1|\b(Professs?or|Apl\.|Hon\.-|Drs\.|Schwester|Frau|Herr)\b|- |(Graf|Gräfin|Freiherr) (von|zu)$|\b(von|zu|von den)$', n): flag('garbled_name', p)
        if p['residence'] and re.match(r'(und\b|[a-zäöü(]|\[)', p['residence']): flag('garbled_residence', p)

    # people split into several records: shared QID, official vs other source under a name variant
    q = defaultdict(list)
    for p in ps:
        if p['wikidata']: q[p['wikidata']].append(p)
    for k, v in q.items():
        if len(v) > 1: flag('qid_on_several_records', v[0], qid=k, others=[(x['id'], x['name'], x['residence']) for x in v[1:]])
    ix = defaultdict(list)
    for p, a in aw:
        if off(a) and (k := key(p['name'])): ix[k[1]].append((p, a, k))
    for p, a in aw:
        if off(a) or not (k := key(p['name'])): continue
        m = next(((x, b) for x, b, kx in ix[k[1]] if x['id'] != p['id'] and kx[0] == k[0] and abs(a['year'] - b['year']) <= 1), None)
        if m: flag('non_official_record_matches_official_entry', p, a, match=(m[0]['id'], m[0]['name'], m[0]['residence'], m[1]['grade'], m[1]['year']))
    lists = defaultdict(lambda: defaultdict(list))  # same announcement, grade and residence, one record per transcription
    for p, a in aw:
        v = set(vias(a)) & set(OFF)
        if len(v) == 1: lists[a['announced'], a['grade'], norm(p['residence'] or '')][v.pop()].append(p)
    for v in lists.values():
        for x in v['bpr']:
            for y in v['wikiprojekt']:
                if x['id'] != y['id'] and norm(x['name']).split()[0][:3] == norm(y['name']).split()[0][:3]: flag('bpr_and_wikiprojekt_spelled_differently', x, other=(y['id'], y['name']))

    # several people merged into one record: two distinct entries of the same official list, or official entries with different residences in one year
    for p in ps:
        by = defaultdict(set)
        for a in p['awards']:
            for s in a['sources']:
                if s['via'] in OFF and s.get('extracted_by') == 'parser': by[s['via'], s['published']].add(s['quote'])
        places = [{w[:5] for w in norm(qt.rsplit(']]', 1)[1] if ']]' in qt else ' '.join(qt.split(',')[2:])).split() if len(w) > 3 and w not in STOP}
                  for a in p['awards'] for s in a['sources'] if s['via'] in OFF and s.get('extracted_by') == 'parser' and (qt := s['quote'])]  # not q: that holds the QIDs queried below
        if any(len(v) > 1 for v in by.values()) or any(x and y and not x & y for i, x in enumerate(places) for y in places[i + 1:]):
            flag('namesakes_merged', p, quotes=sorted({x for v in by.values() for x in v}))

    # Wikidata link belongs to someone else: died before the award, surname not in the label, century-precision birth date
    qs = sorted(q)
    death, label = {}, defaultdict(set)
    for i in range(0, len(qs), 500):
        for x, d, l in sparql('SELECT ?p ?d ?l WHERE { VALUES ?p { %s } OPTIONAL { ?p wdt:P570 ?d } OPTIONAL { ?p rdfs:label ?l FILTER(LANG(?l) IN ("de","mul","en")) } }'
                              % ' '.join(f'wd:{x}' for x in qs[i:i + 500]), f'wd_death_{i}.tsv'):
            x = x.rsplit('/', 1)[1]
            if re.match(r'"?[12]\d{3}-', d): death[x] = min(death.get(x, '9999'), d.strip('"')[:10])
            if l: label[x].add(l.rsplit('"@', 1)[0].strip('"'))
    flat = lambda s: re.sub(r'[^a-z]', '', norm(s))
    for p in ps:
        if not (x := p['wikidata']): continue
        if (d := death.get(x)) and any(a['date'] > d if a['date'] else a['year'] > int(d[:4]) for a in p['awards']): flag('qid_person_died_before_award', p, qid=x, died=d)
        if label[x] and not any(flat(p['name'].split()[-1]) in flat(l) for l in label[x]): flag('qid_label_mismatch', p, qid=x, label=sorted(label[x])[0])
        if p['born_source'] == 'wikidata' and re.fullmatch(r'\d\d00', p['born'] or ''): flag('birth_year_is_century', p, born=p['born'])

    # places: bare names resolved to a much smaller namesake, or contradicted by the presenting state premier
    gs, bix = gemeinden(), defaultdict(set)
    for a, x in gs.items():
        for l in x['labels']: bix[pkey(base(l))].add(a)
    for p in ps:
        r = p['residence'] or ''
        if p['country'] == 'Deutschland' and re.fullmatch(r'[\w .-]+', r) and len(c := bix.get(pkey(r), ())) > 1:
            big = max(c, key=lambda a: gs[a]['pop'])
            mine = p['ags'] or next(k for k, v in STATES.items() if v == p['state'])
            if big[:2] != mine[:2] and gs[big]['pop'] >= 5 * gs.get(mine, {'pop': 1})['pop']: flag('place_resolved_to_small_namesake', p, state=p['state'], likely=(gs[big]['name'], STATES[big[:2]]))
        for a in p['awards']:
            if p['state'] and (m := re.search(r'Ministerpräsident(?:in)?\s+(?:Dr\.\s+)?(?:\w+\s+)?([\w-]+)', a['presented_by'] or '')) and m[1] in MP and STATES[MP[m[1]]] != p['state']:
                flag('state_differs_from_presenting_premier', p, a, state=p['state'], premier_state=STATES[MP[m[1]]])

    # missing information
    wp = {re.sub(r'.*/(\d{4})/(\w+)$', r'\1/\2', d['title']) for _, d in docs('wikiprojekt')}
    bpr = {d['url'].rsplit('/', 1)[1][:4] for _, d in docs('bpr') if 'Bekanntgabe-Ordensverleihung' in d['url'] and len(d['text']) > 1000}
    last = max(a['announced'] for _, a in aw if a['announced'])
    gaps = [f'{y}-{m:02d}' for y in range(2015, int(last[:4]) + 1) for m in range(1, 13) if f'{y}-{m:02d}' <= last[:7]
            and f'{y % 100:02d}{m:02d}' not in bpr and f'{y}/{MONTHS[m - 1]}' not in wp]
    missing = {'announcement_months_in_no_source': gaps, 'official_months_only_in_wikiprojekt': [f'{y}-{m:02d}' for y in range(2015, int(last[:4]) + 1) for m in range(1, 13)
               if f'{y}-{m:02d}' <= last[:7] and f'{y % 100:02d}{m:02d}' not in bpr and f'{y}/{MONTHS[m - 1]}' in wp],
               'latest_announcement': last, 'people': len(ps), 'awards': len(aw),
               'person_field_null': {f: sum(p[f] is None for p in ps) for f in ('occupation', 'residence', 'born', 'gender', 'state', 'wikidata')},
               'award_field_null': {f: sum(a[f] is None for _, a in aw) for f in ('date', 'place', 'presented_by', 'reason')},
               'grade_unbekannt': sum(a['grade'] == 'unbekannt' for _, a in aw),
               'residence_unresolved': sum(bool(p['residence']) and not p['country'] for p in ps)}
    (CACHE / 'audit.json').write_text(json.dumps({'missing': missing, 'flags': flags}, ensure_ascii=False, indent=1))
    for k, v in flags.items(): print(f'{len(v):5}  {k}')
    print(json.dumps(missing, ensure_ascii=False))

if __name__ == '__main__': run()
