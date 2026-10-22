import json, re, time, urllib.parse
from .common import CACHE, GRADES, get, save_doc

API = 'https://de.wikipedia.org/w/api.php'
LISTS = {'Liste von Trägern des Bundesverdienstkreuzes': None,
         'Liste von Trägern des Bundesverdienstkreuzes 1. Klasse': 'Verdienstkreuz 1. Klasse',
         'Liste von Trägern des Bundesverdienstkreuzes am Bande': 'Verdienstkreuz am Bande'}
GN = {g for g in GRADES.values() if g}
VK = re.compile(r'(Bundesverdienst|Verdienst(orden|kreuz|medaille)[^.]{0,80}Bundesrepublik|Verdienstkreuz am Bande|Verdienstkreuz 1\. Klasse|Großes Verdienstkreuz|Verdienstmedaille)')
YR = re.compile(r'\b(20[12]\d)\b')

def wikitext(titles):
    r = get(API, params=dict(action='query', prop='revisions', rvprop='content', rvslots='main', titles='|'.join(titles), redirects=1, format='json', formatversion=2)).json()['query']
    red, norm = ({x['to']: x['from'] for x in r.get(k, [])} for k in ('redirects', 'normalized'))
    return {(t := red.get(p['title'], p['title']), norm.get(t, t))[1]: p['revisions'][0]['slots']['main']['content'] for p in r['pages'] if 'revisions' in p}

def plain(t):
    t = re.sub(r'<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->', '', t, flags=re.S)
    while (n := re.sub(r'\{\{[^{}]*\}\}', '', t)) != t: t = n
    t = re.sub(r'\[\[(?:Datei|File|Bild|Kategorie|Category):[^\]]*\]\]', '', t)
    t = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', t)
    t = re.sub(r'\[https?://\S+ ([^\]]*)\]', r'\1', t)
    return re.sub(r"'{2,}|<[^>]+>", '', t)

def lists():
    out = []
    for page, grade in LISTS.items():
        g = grade
        for l in wikitext([page])[page].splitlines():
            if m := re.match(r'^=+\s*(.*?)\s*=+', l):
                if m[1] in GN: g = m[1]
                elif re.search('abgelehnt|zurückgegeben', m[1]): g = None
            elif g and (m := re.match(r'^\*+\s*\[\[([^\]|]+)(?:\|([^\]]+))?\]\],?\s*(.*)$', l)):
                info = plain(m[3]).strip()
                yp = re.search(r'\(([^()]*)\)\s*$', info)
                out.append(dict(title=m[1].strip(), name=(m[2] or m[1]).strip(), info=info, grade=g,
                                years=[int(y) for y in re.findall(r'\b\d{4}\b', yp[1])] if yp else []))
    (CACHE / 'dewiki_list.json').write_text(json.dumps(out, ensure_ascii=False, indent=0))
    return out

def run():
    ls = lists()
    wd = json.loads((CACHE / 'wikidata.json').read_text()) if (CACHE / 'wikidata.json').exists() else []
    info = {}
    for x in wd:
        if x['dewiki']:
            t = urllib.parse.unquote(x['dewiki'].rsplit('/wiki/', 1)[1]).replace('_', ' ')
            info.setdefault(t, {'qid': x['qid'], 'wd': [], 'list': []})['wd'].append(f"{x['grade'] or 'Verdienstorden'} {x['date'] or ''}".strip())
    for x in ls: info.setdefault(x['title'], {'qid': None, 'wd': [], 'list': []})['list'].append(x)
    dp = CACHE / 'dewiki_done.txt'
    done = set(dp.read_text().splitlines()) if dp.exists() else set()
    titles, n = [t for t in sorted(info) if t not in done], 0
    for i in range(0, len(titles), 50):
        time.sleep(1)
        batch = titles[i:i + 50]
        for t, wt in wikitext(batch).items():
            if t not in info: continue
            lines = [s.strip(' *#:') for l in plain(wt).splitlines() for s in re.split(r'(?<=[.!?])\s+', l)]
            hits = [s for s in lines if VK.search(s)]
            recent = any(y >= 2015 for x in info[t]['list'] for y in x['years']) or any(YR.search(s) and int(YR.search(s)[1]) >= 2015 for s in hits) \
                or any(re.search(r'20(1[5-9]|2\d)', w) for w in info[t]['wd'])
            if not recent: continue
            lead = next((l for l in plain(wt).split('\n\n') if l.strip() and not l.strip().startswith(('|', '{', '=', '['))), '')[:600]
            text = '\n'.join([f'Wikipedia-Artikel: {t}', f'Einleitung: {lead.strip()}',
                              *[f"Wikipedia-Liste: {x['grade'] or 'Stufe unbekannt'} ({', '.join(map(str, x['years']))}); {x['info']}" for x in info[t]['list']],
                              *[f'Wikidata: {w}' for w in info[t]['wd']], 'Relevante Sätze:', *[f'- {s}' for s in hits[:15]]])
            save_doc(f"https://de.wikipedia.org/wiki/{urllib.parse.quote(t.replace(' ', '_'))}", text, 'dewiki', title=t, qid=info[t]['qid'])
            n += 1
        with dp.open('a') as f: f.write('\n'.join(batch) + '\n')
        print(f'{i + 50}/{len(titles)} saved={n}', end='\r')
    print()
