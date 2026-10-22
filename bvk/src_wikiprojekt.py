import time, urllib.parse
from .common import get, save_doc
from .src_dewiki import API, wikitext

def run():
    titles, cont = [], {}
    while True:
        r = get(API, params=dict(action='query', list='allpages', apnamespace=4, apprefix='WikiProjekt Bundesverdienstkreuz/', aplimit=500, format='json', **cont)).json()
        titles += [x['title'] for x in r['query']['allpages']]
        if 'continue' not in r: break
        cont = r['continue']
    titles = [t for t in titles if t.count('/') == 2 and t.split('/')[1].isdigit() and int(t.split('/')[1]) >= 2014]
    print(len(titles), 'month pages')
    for i in range(0, len(titles), 50):
        for t, wt in wikitext(titles[i:i + 50]).items():
            save_doc(f"https://de.wikipedia.org/wiki/{urllib.parse.quote(t.replace(' ', '_'))}", wt, 'wikiprojekt', title=t)
        time.sleep(1)
