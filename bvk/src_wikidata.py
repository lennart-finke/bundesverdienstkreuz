import json
from .common import CACHE, GRADES, get

Q = '''PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/> PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX schema: <http://schema.org/>
SELECT ?p ?name ?desc ?award ?d ?art (GROUP_CONCAT(DISTINCT ?occL; separator="; ") AS ?occ) WHERE {
 VALUES ?award { %s }
 ?p wdt:P31 wd:Q5 ; p:P166 ?st . ?st ps:P166 ?award . OPTIONAL { ?st pq:P585 ?d }
 OPTIONAL { ?p rdfs:label ?name FILTER(LANG(?name) = "de") }
 OPTIONAL { ?p schema:description ?desc FILTER(LANG(?desc) = "de") }
 OPTIONAL { ?art schema:about ?p ; schema:isPartOf <https://de.wikipedia.org/> }
 OPTIONAL { ?p wdt:P106 ?o . ?o rdfs:label ?occL FILTER(LANG(?occL) = "de") }
} GROUP BY ?p ?name ?desc ?award ?d ?art'''

def run():
    out = []
    for q in GRADES:
        rows = get('https://qlever.dev/api/wikidata', params={'query': Q % f'wd:{q}'}, headers={'Accept': 'application/sparql-results+json'}).json()['results']['bindings']
        v = lambda r, k: r[k]['value'] if k in r else None
        for r in rows:
            out.append(dict(qid=v(r, 'p').rsplit('/', 1)[1], name=v(r, 'name'), desc=v(r, 'desc'), occupation=v(r, 'occ') or None,
                            grade=GRADES[q], date=(v(r, 'd') or '')[:10] or None, dewiki=v(r, 'art')))
        print(q, GRADES[q], len(rows))
    (CACHE / 'wikidata.json').write_text(json.dumps(out, ensure_ascii=False, indent=0))
