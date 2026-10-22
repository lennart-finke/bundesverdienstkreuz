import datetime, hashlib, json, os, pathlib, threading, httpx, re
from tenacity import retry, stop_after_attempt, wait_exponential

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE, RAW, EXT, DATA = (ROOT / p for p in ('cache', 'cache/raw', 'cache/ext', 'data'))
for d in (RAW, EXT, DATA): d.mkdir(parents=True, exist_ok=True)
UA = 'bvk-research/0.1 (python-httpx)'
MODEL = os.environ.get('BVK_MODEL', 'z-ai/glm-5.3')
http = httpx.Client(headers={'User-Agent': UA}, timeout=60, follow_redirects=True)

GRADES = {
    'Q10905425': 'Verdienstmedaille',
    'Q10905380': 'Verdienstkreuz am Bande',
    'Q10905334': 'Verdienstkreuz 1. Klasse',
    'Q10905276': 'Großes Verdienstkreuz',
    'Q10905235': 'Großes Verdienstkreuz mit Stern',
    'Q10905171': 'Großes Verdienstkreuz mit Stern und Schulterband',
    'Q10905105': 'Großkreuz',
    'Q10905054': 'Großkreuz in besonderer Ausführung',
    'Q10904959': 'Sonderstufe des Großkreuzes',
    'Q21164': None,
}

def h(s): return hashlib.sha1(s.encode()).hexdigest()

@retry(stop=stop_after_attempt(8), wait=wait_exponential(5, max=180), reraise=True)
def get(url, **kw):
    r = http.get(url, **kw); r.raise_for_status(); return r

def have(url): return (RAW / f'{h(url)}.json').exists()

def write(p, obj):
    t = p.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
    t.write_text(json.dumps(obj, ensure_ascii=False), errors='replace'); os.replace(t, p)

def save_doc(url, text, src, title='', date='', **kw):
    path = RAW / f'{h(url)}.json'
    old = json.loads(path.read_text()) if path.exists() else {}
    methods = sorted(set(old.get('collected_via', [old['src']] if old.get('src') else [])) | {src})
    if re.search(r'^https?://(?:www\.)?bundespraesident\.de/SharedDocs/Berichte/Bekanntgabe-Ordensverleihung/', url): src = 'bpr'
    if old.get('text') != text or old.get('src') != src: (EXT / f'{h(url)}.json').unlink(missing_ok=True)
    write(path, dict(url=url, title=title, date=date, text=text, src=src, collected_via=methods, **kw))

def docs(src=None):
    for p in sorted(RAW.glob('*.json')):
        try: d = json.loads(p.read_text())
        except ValueError: continue
        if src in (None, d['src']): yield p.stem, d

def key():
    if k := os.environ.get('OPENROUTER_API_KEY'): return k
    env = ROOT / '.env'
    if env.exists():
        for l in env.read_text().splitlines():
            if l.startswith('OPENROUTER_API_KEY='): return l.split('=', 1)[1].strip().strip('"\'')
    raise SystemExit('OPENROUTER_API_KEY missing (env or .env)')

@retry(stop=stop_after_attempt(5), wait=wait_exponential(2, max=60), reraise=True)
def llm(messages, schema=None, model=MODEL, **kw):
    body = dict(model=model, messages=messages, reasoning={'effort': 'low'}, **kw)
    if schema: body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'out', 'strict': True, 'schema': schema}}
    r = httpx.post('https://openrouter.ai/api/v1/chat/completions', json=body, headers={'Authorization': f'Bearer {key()}'}, timeout=120)
    r.raise_for_status()
    return r.json()

MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']
MON = {m: i + 1 for i, m in enumerate(MONTHS)}
MON3 = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}

def iso_date(s):
    """'2018-09- 5', '14.09.2015', '01/27/2017', 'Tue, 12 Mar 2019' -> ISO date; None without a complete valid date ('Tue Oct 13', '07:30', '2020-12-XX')."""
    s = (s or '').strip()
    if m := re.search(r'\b(\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})\b', s): s = f'{m[3]}-{MON3.get(m[2].casefold(), 0)}-{m[1]}'
    for p, order in ((r'(\d{4})-(\d{1,2})-\s*(\d{1,2})', 'ymd'), (r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})', 'dmy'), (r'(\d{1,2})/(\d{1,2})/(\d{4})', 'mdy')):
        if m := re.match(p + r'(?!\d)', s):
            v = dict(zip(order, map(int, m.groups())))
            try: return datetime.date(v['y'], v['m'], v['d']).isoformat()
            except ValueError: return None
    return None

def page_text(r):
    ct, url = r.headers.get('content-type', ''), str(r.url)
    if 'pdf' in ct or url.lower().endswith('.pdf'):
        import io, pypdf
        return '', '', '\n'.join(p.extract_text() or '' for p in pypdf.PdfReader(io.BytesIO(r.content)).pages)
    from selectolax.lexbor import LexborHTMLParser as HTMLParser
    t = HTMLParser(r.text)
    title = t.css_first('title').text(strip=True) if t.css_first('title') else ''
    date = next((n.attributes.get(a) for s, a in (('meta[property="article:published_time"]', 'content'), ('meta[name="date"]', 'content'),
                 ('meta[name="DC.date"]', 'content'), ('time[datetime]', 'datetime')) if (n := t.css_first(s))), '') or ''
    for n in t.css('script,style,nav,header,footer,aside,form,noscript'): n.decompose()
    body = t.css_first('article') or t.css_first('main') or t.body
    return title, date[:10], '\n'.join(l.strip().replace('\xad', '') for l in (body.text(separator='\n') if body else '').splitlines() if l.strip())
