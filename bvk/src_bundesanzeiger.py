"""Search official Bundesanzeiger notices; retain stable publication URLs and dates."""
import datetime, re, time
from urllib.parse import urljoin
import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from .common import CACHE, UA, docs, write
from .official import cached_valid, store_list

SEARCH = 'https://www.bundesanzeiger.de/pub/de/suche-amtlicher-teil'
TITLE = 'Bekanntgabe von Verleihungen des Verdienstordens'

def notice_text(tree):
    body = tree.css_first('#preview_data')
    if not body: raise ValueError('Missing publication content')
    # Keep inline surname spans attached to the rest of their paragraph.
    for br in body.css('br'): br.replace_with(' ')
    return '\n'.join(' '.join(n.text(separator='', strip=False).split()) for n in body.css('h2,h3,h4,p,.Date'))

def run(start='2015', end=None, refresh=''):
    today = datetime.date.today()
    end = end or today.strftime('%d.%m.%Y')
    known = {d.get('reference'): d['url'] for _, d in docs('bundesanzeiger')}
    saved, skipped, pages, failures, seen_refs = 0, 0, 0, [], set()
    with httpx.Client(headers={'User-Agent': UA}, follow_redirects=True, timeout=30) as client:
        r = client.get(SEARCH); r.raise_for_status()
        form = HTMLParser(r.text).css_first('form.search-form')
        if not form: raise ValueError('Search form missing')
        r = client.post(urljoin(str(r.url), form.attributes['action']), data={
            'fulltext': '', 'publicationtitle': TITLE, 'court_name': 'Bundespräsidialamt',
            'start_date': f'01.01.{int(start)}', 'end_date': end,
            'panelCategories:groupCategories': '999991', 'search-button': 'Suchen'})
        while True:
            r.raise_for_status(); tree = HTMLParser(r.text); pages += 1
            links = [a for a in tree.css('a[href]') if TITLE in a.text()]
            if not links: failures.append({'url': str(r.url), 'error': 'No publication results'}); break
            next_page = next((urljoin(str(r.url), a.attributes['href']) for a in tree.css('a[href]') if 'pager-next' in a.attributes['href']), None)
            new = 0
            for a in links:
                info = a.parent.text(separator=' ', strip=True)
                ref = re.search(r'BAnz AT \d{2}\.\d{2}\.\d{4} B\d+', info)
                date = re.search(r'vom:\s*(\d{2})\.(\d{2})\.(\d{4})', info)
                if not ref or not date: failures.append({'info': info, 'error': 'Missing reference/date'}); continue
                ref = ref[0]
                if ref in seen_refs: continue
                seen_refs.add(ref); new += 1
                if refresh != 'refresh' and ref in known and cached_valid(known[ref]): skipped += 1; continue
                try:
                    page = client.get(urljoin(str(r.url), a.attributes['href'])); page.raise_for_status()
                    doc = HTMLParser(page.text)
                    pdf = next((n.attributes['href'] for n in doc.css('a[href]') if '.pdf' in n.attributes['href'] and 'publication/' in n.attributes['href']), None)
                    if not pdf: raise ValueError('Stable PDF publication URL missing')
                    url = urljoin(str(page.url), pdf).split('?')[0]
                    text = notice_text(doc)
                    published = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', ref)
                    store_list(url, text, 'bundesanzeiger', title=TITLE + ' der Bundesrepublik Deutschland',
                               date=f'{date[3]}-{date[2]}-{date[1]}', announcement_month=f'{date[3]}-{date[2]}',
                               gazette_published=f'{published[3]}-{published[2]}-{published[1]}', reference=ref)
                    saved += 1; print('Saved', ref, flush=True)
                except Exception as e: failures.append({'reference': ref, 'error': str(e)})
                time.sleep(0.1)
            if not next_page or not new: break
            r = client.get(next_page)
    write(CACHE / 'bundesanzeiger_fetch_report.json', {'checked_at': datetime.datetime.now(datetime.UTC).isoformat(), 'pages': pages, 'found': len(seen_refs), 'saved': saved, 'valid_cached': skipped, 'failures': failures})
    print(f'Bundesanzeiger: {saved} saved, {skipped} valid cached, {len(failures)} failures')
