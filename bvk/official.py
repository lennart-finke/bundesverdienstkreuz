"""Shared validation and cache handling for official award announcements."""
import datetime, json, re
from .common import RAW, h, save_doc

OFFICIAL = ('bpr', 'wikiprojekt', 'bundesanzeiger')
ERRORS = ('ihre anfrage war unzulässig', 'access denied', 'request rejected', 'seite nicht gefunden', '404 not found')

def valid_list(text):
    low = text.casefold()
    return not any(s in low for s in ERRORS) and bool(re.search(r'Verdienstkreuz|Verdienstmedaille|Großkreuz', text)) and bool(re.search(r'[^\n,]+,\s*[^\n,]+,', text))

def cached_valid(url, src=None):
    path = RAW / f'{h(url)}.json'
    if not path.exists(): return False
    try:
        doc = json.loads(path.read_text())
        return (src is None or doc['src'] == src) and valid_list(doc['text'])
    except (ValueError, KeyError): return False

def store_list(url, text, src, **meta):
    if not valid_list(text): raise ValueError('Not an award list (empty/error response or no recipient rows)')
    save_doc(url, text, src, retrieved=datetime.datetime.now(datetime.UTC).isoformat(), **meta)
