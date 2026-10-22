"""Collect the live monthly archive first, then fall back to archived snapshots."""
import datetime, re
from urllib.parse import urljoin, urlsplit, urlunsplit
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from .common import CACHE, docs, http, page_text, write
from .official import cached_valid, store_list

BASE = 'https://www.bundespraesident.de/'
INDEX = BASE + 'DE/amt-und-aufgaben/orden-und-ehrungen/verdienstorden/bekanntgabe-der-verleihungen/bekanntgabe-der-verleihungen_node.html'
LIST = re.compile(r'Bekanntgabe-Ordensverleihung/(\d{2})(\d{2})(\d{2})?-Verleihungen\.html$')
CDX = 'https://web.archive.org/cdx/search/cdx?url=bundespraesident.de/&matchType=prefix&filter=statuscode:200&filter=original:.*(Orden|orden|Verdienst|verdienst).*&collapse=urlkey&fl=timestamp,original,mimetype'
CDX2 = 'https://web.archive.org/cdx/search/cdx?url=bundespraesident.de/SharedDocs/Berichte/Bekanntgabe-Ordensverleihung/&matchType=prefix&filter=statuscode:200&collapse=urlkey&fl=timestamp,original,mimetype'

def canonical(url):
    p = urlsplit(url)
    return urlunsplit(('https', 'www.bundespraesident.de', p.path.split(';')[0], '', ''))

def request(url):
    r = http.get(url, timeout=25); r.raise_for_status(); return r

def discover():
    pending, seen, links, failures = [INDEX], set(), set(), []
    while pending:
        url = pending.pop(0)
        if url in seen: continue
        seen.add(url)
        try: tree = HTMLParser(request(url).text)
        except Exception as e: failures.append({'url': url, 'error': str(e)}); continue
        for a in tree.css('a[href]'):
            target = urljoin(BASE, a.attributes['href'])
            if urlsplit(target).hostname != 'www.bundespraesident.de': continue
            clean = canonical(target)
            if (m := LIST.search(clean)) and int(m[1]) >= 15: links.add(clean)
            if target.startswith(INDEX + '?') and 'gtp=' in target and target not in seen: pending.append(target.split('#')[0])
    return links, failures

def snapshots(refresh=False):
    best, errors = {}, []
    for name, url in [('bpr_cdx.txt', CDX), ('bpr_cdx2.txt', CDX2)]:
        path = CACHE / name
        if refresh or not path.exists():
            try:
                r = request(url)
                if not r.text.strip() or '<html' in r.text.lower(): raise ValueError('Invalid archive inventory')
                path.write_text(r.text)
            except Exception as e:
                errors.append({'url': url, 'error': str(e)})
                print('Archive inventory:', e)
        if not path.exists(): continue
        for line in path.read_text().splitlines():
            fields = line.split()
            if len(fields) < 3: continue
            ts, orig = fields[:2]; key = canonical(orig)
            if LIST.search(key): best.setdefault(key, []).append((ts, orig))
    write(CACHE / 'bpr_archive_report.json', {'checked_at': datetime.datetime.now(datetime.UTC).isoformat(), 'refresh_requested': refresh, 'failures': errors, 'urls': len(best)})
    return {u: sorted(set(v), reverse=True) for u, v in best.items()}

def run(refresh=''):
    links, failures = discover()
    archive = snapshots(refresh == 'refresh')
    links.update(archive)
    # Mirrors preserve official URLs even when they are absent from live/archive navigation.
    for _, d in docs('wikiprojekt'):
        links.update(canonical(u) for u in re.findall(r'https?://[^\s\]]+', d['text']) if LIST.search(canonical(u)))
    saved = skipped = 0
    for url in sorted(links):
        m = LIST.search(url)
        if not m or int(m[1]) < 15: continue
        if (2000 + int(m[1]), int(m[2])) > (datetime.date.today().year, datetime.date.today().month): continue
        if cached_valid(url, 'bpr') and refresh != 'refresh': skipped += 1; continue
        attempts = [(url, None)] + [(f'https://web.archive.org/web/{ts}id_/{orig}', f'https://web.archive.org/web/{ts}/{orig}') for ts, orig in archive.get(url, [])[:3]]
        errors = []
        for target, archived in attempts:
            try:
                r = request(target); title, date, text = page_text(r)
                meta = dict(title=title, date=date or f'20{m[1]}-{m[2]}-{m[3] or "01"}', announcement_month=f'20{m[1]}-{m[2]}')
                if archived: meta['archived'] = archived
                store_list(url, text, 'bpr', **meta)
                saved += 1; print('Saved', url, flush=True); break
            except Exception as e: errors.append(str(e))
        else: failures.append({'url': url, 'errors': errors})
    write(CACHE / 'bpr_fetch_report.json', {'checked_at': datetime.datetime.now(datetime.UTC).isoformat(), 'discovered': len(links), 'saved': saved, 'valid_cached': skipped, 'failures': failures})
    print(f'Official lists: {saved} saved, {skipped} valid cached, {len(failures)} failures')
