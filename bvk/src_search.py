import json, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
from .common import CACHE, get, have, http, llm, page_text, save_doc

YEARS = range(2015, 2027)
VK = re.compile(r'Bundesverdienstkreuz|Verdienstorden der Bundesrepublik|Verdienstkreuz (am Bande|1\. Klasse)|Großes Verdienstkreuz|Verdienstmedaille')
STATES = {'BW': ['*.baden-wuerttemberg.de'], 'BY': ['*.bayern.de'], 'BE': ['berlin.de'], 'BB': ['*.brandenburg.de'], 'HB': ['*.bremen.de'],
          'HH': ['hamburg.de'], 'HE': ['*.hessen.de'], 'MV': ['regierung-mv.de'], 'NI': ['*.niedersachsen.de'], 'NW': ['*.nrw.de', '*.nrw'],
          'RP': ['*.rlp.de'], 'SL': ['saarland.de'], 'SN': ['*.sachsen.de'], 'ST': ['*.sachsen-anhalt.de'], 'SH': ['schleswig-holstein.de'], 'TH': ['*.thueringen.de']}
PHRASES = ['Bundesverdienstkreuz verliehen', 'Verdienstkreuz am Bande überreicht', 'Verdienstkreuz 1. Klasse', 'Verdienstmedaille des Verdienstordens', 'Verdienstorden der Bundesrepublik Deutschland ausgezeichnet']
REGIONS_Q = '''PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?l WHERE { ?k wdt:P440 ?key ; rdfs:label ?l . FILTER(STRLEN(?key) = 5) FILTER(LANG(?l) = "de") FILTER NOT EXISTS { ?k wdt:P576 [] } }'''
COST = 0.007 + 0.0002
lock = threading.Lock()

def regions():
    p = CACHE / 'regions.json'
    if not p.exists():
        rs = get('https://qlever.dev/api/wikidata', params={'query': REGIONS_Q}, headers={'Accept': 'application/sparql-results+json'}).json()['results']['bindings']
        p.write_text(json.dumps(sorted({re.sub(r'^(Landkreis|Kreis|Stadtkreis|Regionalverband) ', '', r['l']['value']) for r in rs}), ensure_ascii=False))
    return json.loads(p.read_text())

def queries(kind):
    if kind == 'states': return [(f'{ph} {y}', d) for d in STATES.values() for ph in PHRASES for y in YEARS]
    if kind == 'local': return [(f'Bundesverdienstkreuz {r} {y}', None) for r in regions() for y in YEARS]
    raise SystemExit('kind: states|local')

def search(q, domains):
    plug = {'id': 'web', 'engine': 'exa', 'max_results': 10, **({'include_domains': domains} if domains else {})}
    r = llm([{'role': 'user', 'content': f'Suche: {q}. Antworte nur mit OK.'}], plugins=[plug], max_tokens=5)
    return [a['url_citation'] for a in r['choices'][0]['message'].get('annotations') or [] if a.get('type') == 'url_citation']

def one(q, domains, done):
    n = 0
    for c in search(q, domains):
        url = c['url'].split('#')[0]
        if have(url): continue
        try: title, date, text = page_text(http.get(url, timeout=20).raise_for_status())
        except Exception: title, date, text = c.get('title', ''), '', c.get('content', '')
        if VK.search(text or ''):
            save_doc(url, text, 'search', title=title or c.get('title', ''), date=date, query=q); n += 1
    with lock, done.open('a') as f: f.write(json.dumps([q, domains]) + '\n')
    return n

def run(kind, confirm=None):
    done = CACHE / f'search_{kind}_done.jsonl'
    seen = {l for l in done.read_text().splitlines()} if done.exists() else set()
    todo = [(q, d) for q, d in queries(kind) if json.dumps([q, d]) not in seen]
    print(f'{len(todo)} queries, est. ${len(todo) * COST:.0f}')
    if confirm != 'yes': return print(f'rerun with: python -m bvk fetch search {kind} yes')
    n = 0
    with ThreadPoolExecutor(16) as ex:
        for i, f in enumerate([ex.submit(one, q, d, done) for q, d in todo]):
            try: n += f.result()
            except Exception as e: print('ERR', todo[i][0], e, file=sys.stderr)
            print(f'{i + 1}/{len(todo)} new docs={n}', end='\r')
    print()
