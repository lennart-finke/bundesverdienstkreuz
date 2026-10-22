"""Conservative identity normalization; raw source names are always retained."""
import re, unicodedata
from difflib import SequenceMatcher

ACADEMIC = re.compile(r'^(?:(?:hon\.-?\s*)?prof(?:essor(?:in)?)?\.?|professsor|drs?\.?|dres\.|doc\.|phdr\.|phd\.?|csc\.|m\.a\.|apl\.|h\.\s*c\.|ing\.|sr\.|schwester|the rt revd)(?=\s|$)\s*', re.I)
HONORS = {'graf','grafin','freiherr','freifrau','freiin','prinz','prinzessin','furst','furstin','baron','baronin','baroness','comte','sir','dame','konigin','konig','queen','king','prince','princess'}
NICK = {'willi': 'wilhelm', 'willy': 'wilhelm', 'will': 'wilhelm', 'wilma': 'wilhelmine', 'hedi': 'hedwig', 'max': 'maximilian', 'anni': 'anna', 'annie': 'anna', 'bernd': 'bernhard', 'sepp': 'josef', 'jupp': 'josef', 'joe': 'joseph',
        'fritz': 'friedrich', 'gerd': 'gerhard', 'uli': 'ulrich', 'toni': 'anton', 'gabi': 'gabriele', 'gaby': 'gabriele', 'conny': 'cornelia', 'resi': 'theresia', 'kathi': 'katharina', 'alex': 'alexander', 'andi': 'andreas',
        'ulla': 'ursula', 'uschi': 'ursula', 'ursel': 'ursula', 'lilo': 'liselotte', 'elli': 'elisabeth', 'elly': 'elisabeth', 'bruni': 'brunhilde', 'mona': 'monika', 'heidi': 'heidemarie',
        'heiner': 'heinrich', 'jochen': 'joachim', 'achim': 'joachim', 'rudi': 'rudolf', 'siggi': 'siegfried', 'nico': 'nikolaus',
        'ralph': 'ralf', 'detlev': 'detlef', 'claus': 'klaus', 'carl': 'karl', 'christof': 'christoph', 'gunther': 'gunter'}  # nicknames and spelling variants seen in press reports of list entries
PARTICLES = {'von','van','der','den','dem','de','zu','zur','vom','und','del'}
ROLES = {'chemikerin und journalistin','ehemaliger fußballnationalspieler','facharbeiterin','pianist','schauspielerin','schriftsteller'}

def clean_name(name):
    name = name.strip()
    while (s := ACADEMIC.sub('', name)) != name: name = s.strip()
    return name

def tokens(name):
    name = clean_name(name).casefold().translate(str.maketrans({'ß':'ss','ı':'i','ł':'l','ø':'o','đ':'d','’':"'"}))
    name = unicodedata.normalize('NFKD', name).encode('ascii','ignore').decode()
    t = re.findall(r'[a-z]+', name)
    keep = len(t) > 1 and t[-1] in HONORS and t[-2] not in HONORS | PARTICLES  # "Josef Fürst", "Patrick Prinz": the honour word is the surname
    return [x for x in t[:len(t) - keep] if x not in HONORS | PARTICLES] + t[len(t) - keep:]

def split_name(name):
    """Given-name tokens and the surname; a hyphenated surname stays one ("Hoppe-Waßmuth" is not a given name "Hoppe")."""
    t = tokens(name)
    if not t: return [], ''
    words = clean_name(name).split()
    last = tokens(words[-1]) if words else []
    k = len(last) if 1 < len(last) < len(t) and t[-len(last):] == last else 1
    return t[:-k], '-'.join(t[-k:])

def name_key(name):
    given, last = split_name(name)
    return f'{(given or [last])[0]} {last}' if last else ''

def identity_matches(name, reference):
    """Require compatible given AND family names; a spouse's surname alone is insufficient."""
    a,b=([NICK.get(x,x) for x in tokens(n)] for n in (name,reference))
    if not a or not b: return False
    if a==b: return True
    if len(a)<2 or len(b)<2: return a[0]==b[0]  # a monarch's one-word label: "Camilla" / "Camilla Rosemary Shand"
    return (a[0] == b[0] and (a[-1] == b[-1] or set(a)<=set(b) or set(b)<=set(a))) or SequenceMatcher(None,' '.join(a),' '.join(b)).ratio() >= .92

def publisher(url):
    from urllib.parse import urlsplit
    host=(urlsplit(url).hostname or '').removeprefix('www.')
    if host=='bundespraesident.de': return 'bpr'
    if host=='bundesanzeiger.de': return 'bundesanzeiger'
    if host=='de.wikipedia.org': return 'dewiki'
    if host.endswith('.wikipedia.org'): return 'other_wikipedia'
    if host=='wikidata.org': return 'wikidata'
    return 'other'
