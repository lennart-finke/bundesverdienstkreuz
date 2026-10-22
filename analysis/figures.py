import html, json, re, unicodedata, textwrap
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import matplotlib; matplotlib.use('Agg'); import matplotlib.collections, matplotlib.patches, matplotlib.ticker
import matplotlib.pyplot as plt
import numpy as np
from bvk.common import CACHE, DATA, GRADES, ROOT, get, llm
from bvk.enrich import STATES, gemeinden, sparql

OUT = ROOT / 'figures'; OUT.mkdir(exist_ok=True)
VG = 'https://sgx.geodatenzentrum.de/wfs_vg2500?service=WFS&version=2.0.0&request=GetFeature&outputFormat=application/json&srsName=EPSG:25832'  # BKG district/state outlines 1:2.5M
KREIS = {'06415': '06435'}  # Hanau is kreisfrei since 2026; VG2500 still has it in Main-Kinzig-Kreis
CATS = ['Soziales & Wohlfahrt', 'Kommunalpolitik & Verwaltung', 'Politik (Land/Bund/EU)', 'Sport', 'Kultur & Kunst', 'Wissenschaft & Forschung',
        'Bildung & Jugend', 'Kirche & Religion', 'Gesundheit & Pflege', 'Feuerwehr, Rettung & Katastrophenschutz', 'Umwelt & Naturschutz',
        'Erinnerungskultur & Versöhnung', 'Integration & Migration', 'Wirtschaft & Gewerkschaft', 'Heimat & Brauchtum', 'Internationale Beziehungen', 'Sonstiges', 'Nicht spezifiziert']
CATS_ASK = 'Ordne jede nummerierte Begründung genau einer dieser Kategorien zu (Hauptgrund; "Nicht spezifiziert" wenn kein konkreter Bereich genannt):'
MERIT = ['Ehrenamt', 'Beides', 'Beruf', 'Unklar']
MERIT_ASK = ('Ordne jede nummerierte Auszeichnung genau einer dieser Kategorien zu, je nachdem, wofür die Person hauptsächlich ausgezeichnet wurde '
             '(Ehrenamt = unbezahltes Engagement neben oder nach dem Beruf, z. B. Verein, Initiative, Kirchengemeinde, Feuerwehr, Stiftung, ehrenamtliches Kommunalmandat; '
             'Beruf = Leistungen in der bezahlten Haupttätigkeit, z. B. Forschung, Unternehmen, Kunst, Verwaltung, Berufspolitik, Diplomatie; '
             'Beides = beides etwa gleich gewichtet; Unklar = nicht erkennbar):')
INK, MUTED, GRID, BG = '#303b39', '#686b62', '#deded3', '#fffff8'
S = ['#507a76', '#af654b', '#7d8960', '#ad853e']
PARTIES = {'CDU': '#2b2b2b', 'SPD': '#d71f1d', 'Grüne': '#3a9a3a', 'CSU': '#0570b0', 'FDP': '#e6c200', 'Linke': '#b5236e', 'AfD': '#2fa0d8', 'Freie Wähler': '#f08a00', 'ÖDP': '#d87928'}
PARTY_QID = {'CDU': 'Q49762', 'SPD': 'Q49768', 'CSU': 'Q49763', 'Grüne': 'Q49766', 'FDP': 'Q13124', 'Linke': 'Q49764', 'AfD': 'Q6721203'}  # Freie Wähler: mostly local voter groups, no member count
MEMBERS_Q = 'SELECT ?q ?n ?d WHERE { VALUES ?q { %s } ?q p:P2124 ?s . ?s ps:P2124 ?n ; pq:P585 ?d }' % ' '.join(f'wd:{q}' for q in PARTY_QID.values())
# Quiet, warm editorial styling; party hues retain their established meanings.
plt.rcParams.update({
    'font.family': 'DejaVu Sans', 'font.size': 12, 'text.color': INK,
    'axes.labelcolor': MUTED, 'axes.titleweight': 'normal', 'axes.titlepad': 8,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'xtick.major.size': 0, 'ytick.major.size': 0,
    'xtick.major.pad': 8, 'ytick.major.pad': 8,
    'figure.facecolor': BG, 'axes.facecolor': BG,
    'axes.spines.top': False, 'axes.spines.right': False,
    'axes.spines.left': False, 'axes.spines.bottom': False,
    'grid.linewidth': 0.7, 'grid.alpha': 0.65, 'axes.axisbelow': True,
    'legend.frameon': False, 'legend.fontsize': 14, 'legend.handlelength': 1.2,
    'legend.handleheight': 0.8, 'legend.columnspacing': 1.5,
    'savefig.transparent': True,
})

def classify(reasons, cats=CATS, ask=CATS_ASK, cache='categories.json'):
    p = CACHE / cache
    done = json.loads(p.read_text()) if p.exists() else {}
    todo = sorted({r for r in reasons if r not in done})
    def batch(rs):
        msg = (ask + '\n' + '\n'.join(cats) + '\n\nAntworte nur mit einer Zeile pro Nummer im Format Nummer|Kategorie.\n\n' + '\n'.join(f'{i + 1}. {r}' for i, r in enumerate(rs)))
        try: out = llm([{'role': 'user', 'content': msg}], temperature=0)['choices'][0]['message']['content'] or ''
        except Exception as e: print('ERR', e); return {}
        return {rs[int(m[1]) - 1]: m[2].strip() for m in re.finditer(r'^\s*(\d+)\s*\|\s*(.+?)\s*$', out, re.M) if 0 < int(m[1]) <= len(rs) and m[2].strip() in cats}
    with ThreadPoolExecutor(16) as ex:
        for r in ex.map(batch, [todo[i:i + 20] for i in range(0, len(todo), 20)]):
            done.update(r); p.write_text(json.dumps(done, ensure_ascii=False))
    return done

def finish(fig, name, heading=None, handles=(), legend_cols=3):
    # Reserve space for the heading, labels and legend.
    width, height = fig.get_size_inches()
    if handles:
        fig.legend(handles=handles, ncol=min(legend_cols, len(handles)), loc='lower center', bbox_to_anchor=(0.5, 0.01))
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            if isinstance(axis.get_major_locator(), matplotlib.ticker.AutoLocator):
                axis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=4, min_n_ticks=3, steps=[1, 2, 2.5, 5, 10], integer=not isinstance(axis.get_major_formatter(), matplotlib.ticker.PercentFormatter)))
        labels = ax.get_yticklabels()
        if any(len(t.get_text()) > 28 for t in labels):
            ax.set_yticks(ax.get_yticks(), ['\n'.join(textwrap.wrap(t.get_text(), 28, break_long_words=False)) for t in labels])
    header = 0.15
    if heading:
        header = 0.38
        fig.text(0.025, 1 - 0.14 / height, heading, ha='left', va='top', fontsize=17, fontweight='bold', color=INK)
    footer = 0.48 * ((len(handles) + legend_cols - 1) // legend_cols) if handles else 0.08
    fig.tight_layout(pad=0.8, w_pad=2.5, h_pad=2.0, rect=(0, footer / height, 1, 1 - header / height))
    fig.savefig(OUT / name, dpi=200, transparent=not name.endswith('.png'))  # the PNG is the link preview image: opaque
    plt.close(fig); print(OUT / name)

def poisson_ci(n, z=1.96):  # Byar's approximation to the exact Poisson interval for a count
    return (n * (1 - 1 / (9 * n) - z / (3 * n ** .5)) ** 3 if n else 0), (n + 1) * (1 - 1 / (9 * (n + 1)) + z / (3 * (n + 1) ** .5)) ** 3

def percent(value):
    rounded = f'{value:.0%}'
    return (f'{value:.1%}' if value != 0 and rounded == '0%' else rounded).replace('.', ',')


def ratebars(ax, labels, ns, pops, colors, h):  # rate per 100k with 95 % Poisson interval
    r = [n / q * 1e5 for n, q in zip(ns, pops)]
    lo, hi = zip(*[[x / q * 1e5 for x in poisson_ci(n)] for n, q in zip(ns, pops)])
    ax.barh(labels, r, color=colors, height=h)
    ax.errorbar(r, range(len(r)), xerr=[[v - l for v, l in zip(r, lo)], [u - v for v, u in zip(r, hi)]], fmt='none', ecolor=INK, elinewidth=1, capsize=2)
    for i, (v, u, n) in enumerate(zip(r, hi, ns)): ax.text(u + max(hi) * 0.015, i, f'{v:.0f}'.replace('.', ',') + f'  (n = {n:,})'.replace(',', '.'), va='center', fontsize=11, color=MUTED)

def stack(ax, rows, cats, cols, title):  # 100 % bars, rows = [(label, Counter)] top to bottom
    rows, left = rows[::-1], [0] * len(rows)
    for k, col in zip(cats, cols):
        v = [c[k] / max(1, sum(c.values())) for _, c in rows]
        ax.barh([l for l, _ in rows], v, left=left, color=col, height=0.62, edgecolor=BG, linewidth=1)
        for i, (x, l0) in enumerate(zip(v, left)):
            if x >= 0.14: ax.text(l0 + x / 2, i, percent(x), ha='center', va='center', fontsize=11, color=INK if sum(c * w for c, w in zip(matplotlib.colors.to_rgb(col), (0.2126, 0.7152, 0.0722))) > 0.6 else BG)
        left = [a + b for a, b in zip(left, v)]
    for i, (_, c) in enumerate(rows): ax.text(1.01, i, f'n={sum(c.values()):,}'.replace(',', '.'), va='center', fontsize=11, color=MUTED)
    ax.set_xlim(0, 1); ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0)); ax.set_title(title, fontsize=12, color=INK, loc='left')
    ax.spines['left'].set_visible(False); ax.tick_params(axis='y', length=0)

def gender(p):
    # Name-based estimates are excluded from every gender breakdown.
    return p['gender'] if p.get('gender_source') in ('wikidata', 'occupation') else None


def run():
    ps = json.loads((DATA / 'bvk.json').read_text())
    aw = [(p, a) for p in ps for a in p['awards']]

    yrs = sorted({a['year'] for _, a in aw})

    # 1 reasons by grade (share within grade), categories classified by an LLM
    reasons = [a['reason'] for _, a in aw if a['reason']]
    cat = classify(reasons)
    c = Counter(cat[r] for r in reasons if r in cat)
    c.pop('Nicht spezifiziert', 0)
    gl = ['Verdienstmedaille', 'Verdienstkreuz am Bande', 'Verdienstkreuz 1. Klasse', 'Höhere Stufen']
    gk = lambda g: g if g in gl[:3] else (None if g == 'unbekannt' else 'Höhere Stufen')
    top = [k for k, _ in sorted(c.items(), key=lambda x: -x[1])]
    fig, axs = plt.subplots(1, 4, figsize=(16, 9), sharey=True, sharex=True)
    for ax, g in zip(axs.flat, gl):
        cc = Counter(cat.get(a['reason']) for _, a in aw if a['reason'] in cat and cat[a['reason']] != 'Nicht spezifiziert' and gk(a['grade']) == g)
        tot = sum(cc.values())
        ax.barh(top[::-1], [cc[k] / max(tot, 1) for k in top[::-1]], color=S[0], height=0.7)
        ax.set_title(g + '\n' + f'n = {tot:,}'.replace(',', '.'), fontsize=11, color=INK); ax.xaxis.grid(color=GRID); ax.set_axisbelow(True)
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0)); ax.tick_params(axis='y', length=0)
    finish(fig, 'reasons_by_grade.svg', 'Verleihungsgründe nach Ordensstufe')

    # 2 party: LLM-checked membership at award time; 'andere' = a party not in PARTIES
    checked = [x for x in json.loads((DATA / 'party.json').read_text()) if x['party'] != 'keine']
    pname = lambda q: q if q in PARTIES else 'Sonstige'
    pcol = {**PARTIES, 'Sonstige': '#a8a7a2'}
    pc = Counter(pname(x['party']) for x in checked)
    items = sorted(((k, pc[k]) for k in [*PARTIES, *['Sonstige'] * bool(pc['Sonstige'])]), key=lambda x: x[1])  # incl. parties with no hits
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.barh([k for k, _ in items], [v for _, v in items], color=[pcol[k] for k, _ in items], height=0.7)
    m = sum(pc.values())
    for i, (_, v) in enumerate(items): ax.text(v + m * 0.004, i, f'{v} ({percent(v / m)})', va='center', fontsize=11, color=MUTED)
    ax.xaxis.grid(color=GRID); ax.set_axisbelow(True); ax.spines['left'].set_visible(False); ax.tick_params(axis='y', length=0)
    finish(fig, 'parties.svg', 'Bundesverdienstkreuze nach Partei')

    # 3 party share over time (checked parties only, year of first award)
    yr = {p['id']: min(a['year'] for a in p['awards']) for p in ps}
    rows = [(yr[x['id']], pname(x['party'])) for x in checked]
    ys = sorted({y for y, _ in rows}); order = [k for k in ['CDU', 'CSU', 'SPD', 'Grüne', 'FDP', 'Linke', 'Freie Wähler', 'AfD', 'ÖDP', 'Sonstige'] if any(q == k for _, q in rows)]
    fig, ax = plt.subplots(figsize=(9, 5)); bottom = [0] * len(ys)
    for k in order:
        v = [sum(1 for y, q in rows if y == yy and q == k) / sum(1 for y, _ in rows if y == yy) for yy in ys]
        ax.bar(ys, v, bottom=bottom, color=pcol[k], width=0.75, label=k, edgecolor=BG, linewidth=1)
        bottom = [b + x for b, x in zip(bottom, v)]
    for yy in ys: ax.text(yy, 1.01, f'n={sum(1 for y, _ in rows if y == yy)}', ha='center', fontsize=11, color=MUTED)
    ax.set_xticks(ys); ax.set_ylim(0, 1.06); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0)); ax.spines['left'].set_visible(False)
    ax.legend(frameon=False, ncol=4, loc='upper center', bbox_to_anchor=(0.5, -0.07), fontsize=14)
    finish(fig, 'parties_over_time.svg', 'Bundesverdienstkreuze nach Partei und Jahr')

    # 3b per member: honoured persons per year and 100k members, 2015-2025; member counts (Wikidata) interpolated monthly
    mem = defaultdict(lambda: defaultdict(list))
    for q, n, d in sparql(MEMBERS_Q, 'wd_party_members.tsv'):
        if d[:4].isdigit(): mem[q.rsplit('/', 1)[1]][int(d[:4]) + (int(d[5:7]) - 1) / 12 + (int(d[8:10]) - 1) / 365].append(float(n.split('"')[0]))
    months = [y + (m + 0.5) / 12 for y in range(2015, 2026) for m in range(12)]
    my = {k: sum(np.interp(months, sorted(mem[q]), [sum(v) / len(v) for _, v in sorted(mem[q].items())])) / 12 for k, q in PARTY_QID.items()}
    hc = Counter(q for y, q in rows if 2015 <= y <= 2025)
    items = sorted(PARTY_QID, key=lambda k: hc[k] / my[k])
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ratebars(ax, items, [hc[k] for k in items], [my[k] for k in items], [pcol[k] for k in items], 0.7)
    ax.xaxis.grid(color=GRID); ax.set_axisbelow(True); ax.spines['left'].set_visible(False); ax.tick_params(axis='y', length=0)
    ax.set_xlabel('Auszeichnungen je 100.000 Mitglieder und Jahr (2015–2025)')
    finish(fig, 'parties_per_member.svg', 'Bundesverdienstkreuze nach Partei, pro Kopf')

    # 4 gender share per year and per grade
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 9))
    sh = lambda xs: (sum(1 for p in xs if gender(p) == 'w') / max(1, sum(1 for p in xs if gender(p))), sum(1 for p in xs if gender(p)))
    w = [sh([p for p, a in aw if a['year'] == y])[0] for y in yrs]
    a1.bar(yrs, w, color=S[1], width=0.72); a1.bar(yrs, [1 - x for x in w], bottom=w, color=S[0], width=0.72, edgecolor=BG, linewidth=1)
    for y, x in zip(yrs, w): a1.text(y, x / 2, percent(x), ha='center', va='center', fontsize=11, color=BG)
    a1.set_xticks(yrs); a1.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0)); a1.set_title('pro Jahr', fontsize=12, color=INK, loc='left')
    gw = [sh([p for p, a in aw if gk(a['grade']) == g]) for g in gl]
    a2.barh(gl[::-1], [x for x, _ in gw[::-1]], color=S[1], height=0.6); a2.barh(gl[::-1], [1 - x for x, _ in gw[::-1]], left=[x for x, _ in gw[::-1]], color=S[0], height=0.6, edgecolor=BG)
    for i, (x, n) in enumerate(gw[::-1]): a2.text(x / 2, i, percent(x), ha='center', va='center', fontsize=11, color=BG); a2.text(1.01, i, f'n={n:,}'.replace(',', '.'), va='center', fontsize=11, color=MUTED)
    a2.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0)); a2.set_title('nach Stufe', fontsize=12, color=INK, loc='left'); a2.tick_params(axis='y', length=0)
    for ax in (a1, a2): ax.spines['left'].set_visible(False)
    finish(fig, 'gender.svg', 'Bundesverdienstkreuze nach Geschlecht', [matplotlib.patches.Patch(color=S[1], label='Frauen'), matplotlib.patches.Patch(color=S[0], label='Männer')])

    # 5 age at award by grade, split by source of birth date
    fig, ax = plt.subplots(figsize=(10, 6.8))
    srcs = [('Geburtsdatum aus\nWikidata/Wikipedia', {'wikidata', 'dewiki'}, S[0], 0.19), ('Altersangabe in der Presse\n(±1 Jahr)', {'press-age'}, S[1], -0.19)]
    for _, bs, col, off in srcs:
        data = [(i + 1 + off, [a['age'] for p, a in aw if a['age'] is not None and p['born_source'] in bs and gk(a['grade']) == g]) for i, g in enumerate(gl[::-1])]
        for y, _ in filter(lambda x: not x[1], data): ax.text(70, y, 'keine Angaben', ha='center', va='center', fontsize=11, color=MUTED)
        data = [x for x in data if x[1]]
        bp =ax.boxplot([d for _, d in data], positions=[y for y, _ in data], orientation='horizontal', widths=0.3, patch_artist=True, showfliers=False, manage_ticks=False, medianprops={'color': INK, 'linewidth': 2})
        for b in bp['boxes']: b.set(facecolor=col, edgecolor=col)
        for (y, d), cap in zip(data, bp['caps'][1::2]): ax.text(cap.get_xdata()[0] + 1.5, y, f'n = {len(d):,}'.replace(',', '.'), va='center', fontsize=11, color=MUTED)
    ax.set_yticks(range(1, 5), gl[::-1]); ax.set_xticks(range(20, 101, 20)); ax.set_xlim(right=128); ax.set_ylim(0.5, 4.5)
    ax.xaxis.grid(color=GRID); ax.set_axisbelow(True); ax.spines['left'].set_visible(False); ax.tick_params(axis='y', length=0); ax.set_xlabel('Alter bei Verleihung (Jahre)')
    ax.legend(handles=[matplotlib.patches.Patch(facecolor=col, edgecolor=col, label=lab) for lab, _, col, _ in srcs], frameon=False, ncol=2, loc='upper center', bbox_to_anchor=(0.5, -0.13), fontsize=14)
    finish(fig, 'age.svg', 'Bundesverdienstkreuze nach Alter')

    # 6 awards per capita by state and municipality size; official lists only, as press coverage differs by state
    off = [(p, a) for p, a in aw if any(s['via'] in ('bpr', 'wikiprojekt', 'bundesanzeiger') for s in a['sources'])]
    gs, code = gemeinden(), {v: k for k, v in STATES.items()}
    pop = Counter()
    for k, x in gs.items(): pop[STATES[k[:2]]] += x['pop']
    sc = Counter(p['state'] for p, _ in off if p['state'])
    rate = {s: sc[s] / pop[s] * 1e5 for s in sc}
    items = sorted(rate, key=lambda s: rate[s])
    region = {'West': S[0], 'Ost': S[1], 'Berlin': '#a8a7a2'}
    reg = lambda s: 'Berlin' if s == 'Berlin' else 'Ost' if code[s] >= '12' else 'West'
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 11), gridspec_kw={'height_ratios': [3, 1.4]})
    ratebars(a1, items, [sc[s] for s in items], [pop[s] for s in items], [region[reg(s)] for s in items], 0.7)
    sizes = [('unter 5.000', 0), ('5.000–20.000', 5e3), ('20.000–100.000', 2e4), ('100.000–500.000', 1e5), ('ab 500.000', 5e5)]
    size = lambda n: next(l for l, lo in sizes[::-1] if n >= lo)
    zp, zc = Counter(), Counter(size(gs[p['ags']]['pop']) for p, _ in off if p['ags'])
    for x in gs.values(): zp[size(x['pop'])] += x['pop']
    ratebars(a2, [l for l, _ in sizes[::-1]], [zc[l] for l, _ in sizes[::-1]], [zp[l] for l, _ in sizes[::-1]], S[0], 0.6)
    a1.set_title('nach Bundesland', fontsize=12, color=INK, loc='left'); a2.set_title('nach Einwohnerzahl der Wohnortgemeinde', fontsize=12, color=INK, loc='left')
    for ax in (a1, a2): ax.xaxis.grid(color=GRID); ax.set_axisbelow(True); ax.spines['left'].set_visible(False); ax.tick_params(axis='y', length=0)
    finish(fig, 'regions.svg', 'Bundesverdienstkreuze je 100.000 Einwohner',
           [matplotlib.patches.Patch(color=v, label=k) for k, v in zip(['Westdeutsche Länder', 'Ostdeutsche Länder', 'Berlin'], region.values())])

    # 7 recipients living abroad (residence, not citizenship)
    known = [(p, a) for p, a in off if p['country']]
    ab = [(p, a) for p, a in known if p['country'] != 'Deutschland']
    cc = Counter(p['country'] for p, _ in ab); items = sorted(cc.items(), key=lambda x: (-x[1], unicodedata.normalize('NFKD', x[0])))[:10][::-1]  # ties alphabetical (Ä as A)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 9), gridspec_kw={'height_ratios': [2, 1.4]})
    a1.barh([k for k, _ in items], [v for _, v in items], color=S[0], height=0.7)
    for i, (_, v) in enumerate(items): a1.text(v + 0.5, i, str(v), va='center', fontsize=11, color=MUTED)
    sh = [(sum(1 for _, a in ab if gk(a['grade']) == g), sum(1 for _, a in known if gk(a['grade']) == g)) for g in gl]
    a2.barh(gl[::-1], [x / n for x, n in sh[::-1]], color=S[1], height=0.6)
    for i, (x, n) in enumerate(sh[::-1]): a2.text(x / n + 0.01, i, percent(x / n) + f' ({x} von {n:,})'.replace(',', '.'), va='center', fontsize=11, color=MUTED)
    a2.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0)); a2.set_xlim(0, max(x / n for x, n in sh) * 1.45)
    a1.set_title(f'häufigste Länder (Top 10 von {len(cc)})', fontsize=12, color=INK, loc='left'); a2.set_title('Anteil nach Stufe', fontsize=12, color=INK, loc='left')
    for ax in (a1, a2): ax.xaxis.grid(color=GRID); ax.set_axisbelow(True); ax.spines['left'].set_visible(False); ax.tick_params(axis='y', length=0)
    finish(fig, 'abroad.svg', 'Bundesverdienstkreuze im Ausland')

    # 8 academic titles as printed in the official lists (honorary doctorate alone doesn't count)
    tk = lambda t: 'Professor/in' if re.search(r'Prof', t or '') else 'Dr.' if re.search(r'Dr\.(?! h\.? ?c)', t or '') else 'ohne Titel'
    tc, tcol = ['Professor/in', 'Dr.', 'ohne Titel'], [S[0], S[2], '#929184']
    fig, ax = plt.subplots(figsize=(10, 6))
    stack(ax, [(g, Counter(tk(p['titles']) for p, a in off if gk(a['grade']) == g)) for g in gl], tc, tcol, '')
    finish(fig, 'titles.svg', 'Bundesverdienstkreuze nach Titel und Stufe', [matplotlib.patches.Patch(color=v, label=k) for k, v in zip(tc, tcol)])

    # 9 volunteering vs. job: what the award was mainly for, judged by an LLM from occupation + reason
    mt = lambda p, a: (f"Beruf: {p['occupation']}. " if p['occupation'] else '') + f"Begründung: {a['reason']}"
    wr = [(p, a) for p, a in aw if a['reason']]
    mk = classify([mt(p, a) for p, a in wr], MERIT, MERIT_ASK, 'merit.json')
    wr = [(p, a, mk[mt(p, a)]) for p, a in wr if mt(p, a) in mk]
    mcol = [S[1], S[3], S[0], '#929184']
    fig, ax = plt.subplots(figsize=(10, 6))
    stack(ax, [(g, Counter(m for _, a, m in wr if gk(a['grade']) == g)) for g in gl], MERIT, mcol, '')
    finish(fig, 'merit.svg', 'Bundesverdienstkreuze für Ehrenamt und Beruf', [matplotlib.patches.Patch(color=v, label=k) for k, v in zip(MERIT, mcol)], legend_cols=4)

    # 10 map: awards per capita by district (official lists, as in 6); outlines BKG VG2500
    geo = {}
    for L in ('krs', 'lan'):
        p = CACHE / f'vg2500_{L}.json'
        if not p.exists(): p.write_text(get(f'{VG}&typeNames=vg2500:vg2500_{L}').text)
        geo[L] = json.loads(p.read_text())['features']
    kreis = lambda a: KREIS.get(a[:5], a[:5])
    kp, kc = Counter(), Counter(kreis(p['ags']) for p, _ in off if p['ags'])
    for k, x in gs.items(): kp[kreis(k)] += x['pop']
    parts = lambda g: g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
    area = lambda r: abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]))) / 2
    polys = sorted(((poly[0], f['properties']['ags']) for f in geo['krs'] for poly in parts(f['geometry'])), key=lambda x: -area(x[0]))  # cities drawn over the district around them
    ramp = ['#e5e8d9', '#c5d1bc', '#a0b7a0', '#78988b', '#507a76', '#2f514e']
    map_years = len({a['year'] for _, a in off})
    rates = {f['properties']['ags']: kc[f['properties']['ags']] / kp[f['properties']['ags']] * 1e5 / map_years for f in geo['krs']}
    bins = [0.5, 0.75, 1, 1.5, 2]
    labels = ['Unter 0,5', '0,5–0,75', '0,75–1', '1–1,5', '1,5–2', 'Ab 2']
    mapcolor = lambda k: ramp[sum(rates[k] >= b for b in bins)]
    fig, ax = plt.subplots(figsize=(8, 10))
    ax.add_collection(matplotlib.collections.PolyCollection([r for r, _ in polys], facecolors=[mapcolor(k) for _, k in polys], edgecolors=BG, linewidths=0.3))
    ax.add_collection(matplotlib.collections.LineCollection([r for f in geo['lan'] if f['properties']['gf'] == 9 for poly in parts(f['geometry']) for r in poly], colors=INK, linewidths=0.8))
    ax.margins(0.01); ax.autoscale_view(); ax.set_aspect('equal'); ax.axis('off')
    ax.legend(handles=[matplotlib.patches.Patch(color=c, label=l) for c, l in zip(ramp, labels)],
              title='Bundesverdienstkreuze\nje 100,000 Einwohner und Jahr', loc='lower left', bbox_to_anchor=(0, 1.02), ncol=3,
              borderaxespad=0, frameon=False, fontsize=14, title_fontsize=14)
    finish(fig, 'kreise.png', 'Bundesverdienstkreuze je 100,000 Einwohner und Jahr')

    # 10b same map as inline SVG for the article (index.php includes it; hover shows district, rate, count)
    xs, ys = zip(*(pt for f in geo['krs'] for poly in parts(f['geometry']) for r in poly for pt in r))
    xmin, ymax = min(xs), max(ys)
    def path(rings, tol=1.2):  # km from the NW corner, points closer than tol km to the previous one dropped
        out = []
        for r in rings:
            q = []
            for x, y in r:
                x, y = (x - xmin) / 1e3, (ymax - y) / 1e3
                if not q or (x - q[-1][0]) ** 2 + (y - q[-1][1]) ** 2 >= tol ** 2: q.append((x, y))
            if len(q) > 2: out.append('M' + 'L'.join(f'{x:.1f} {y:.1f}' for x, y in q) + 'Z')
        return ''.join(out)
    W, H = (max(xs) - min(xs)) / 1e3, (max(ys) - min(ys)) / 1e3
    svg = [f'<svg class="kmap" viewBox="-5 -5 {W + 10:.0f} {H + 140:.0f}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Karte: Bundesverdienstkreuze je 100,000 Einwohner und Jahr nach Kreis">',
           '<g transform="translate(0 130)"><g class="krs" stroke="#fffff8" stroke-width="0.5" fill-rule="evenodd">']  # evenodd: holes for enclaved cities
    for f in geo['krs']:
        k, pr = f['properties']['ags'], f['properties']
        t = (f"{pr['gen']} ({pr['bez']}, {STATES[k[:2]]})", ('<1' if 0 < rates[k] < 0.5 else f"{rates[k]:.0f}") + f' je 100,000 Einwohner und Jahr · {kc[k]} Verleihungen in {map_years} Kalenderjahren')
        svg.append(f'<path vector-effect="non-scaling-stroke" fill="{mapcolor(k)}" data-t="{html.escape("|".join(t))}" '
                   f'd="{path(r for poly in parts(f["geometry"]) for r in poly)}"><title>{html.escape(": ".join(t))}</title></path>')
    svg.append('</g><path vector-effect="non-scaling-stroke" fill="none" stroke="#111" stroke-width="1" pointer-events="none" d="'
               + path(r for f in geo['lan'] if f['properties']['gf'] == 9 for poly in parts(f['geometry']) for r in poly) + '"/>')
    # Reserve a separate band above the geography so the legend never covers districts.
    svg.append('</g><g font-family="Figure Sans, DejaVu Sans, sans-serif" font-size="18" fill="#686b62"><text x="0" y="18"><tspan x="0">Bundesverdienstkreuze</tspan><tspan x="0" dy="26">je 100,000 Einwohner und Jahr</tspan></text>'
               + ''.join(f'<rect x="{(i % 3) * W / 3:.1f}" y="{62 + 28 * (i // 3)}" width="18" height="12" fill="{c}"/>'
                         f'<text x="{24 + (i % 3) * W / 3:.1f}" y="{74 + 28 * (i // 3)}">{l}</text>' for i, (c, l) in enumerate(zip(ramp, labels))) + '</g></svg>')
    (OUT / 'kreise_map.svg').write_text('\n'.join(svg)); print(OUT / 'kreise_map.svg')
    # 11 people table for the article's search widget: published fields plus estimated gender and the topic / merit labels as filters (no age or party)
    gi = {g: i for i, g in enumerate([g for g in GRADES.values() if g] + ['unbekannt'])}
    src = lambda a: next((s['url'] for v in ('bpr', 'bundesanzeiger', 'wikiprojekt', 'dewiki', 'search', 'wikidata') for s in a['sources'] if s['via'] == v), None)
    urls = sorted({u for _, a in aw if (u := src(a))}); ui = {u: i for i, u in enumerate(urls)}
    ti, mi = {k: i for i, k in enumerate(CATS)}, {k: i for i, k in enumerate(MERIT)}
    rows = [[p['name'], p['titles'] or '', p['residence'] or '', p['state'] or (p['country'] if p['country'] != 'Deutschland' else '') or '', p['wikidata'] or '', p['occupation'] or '', p['gender'] or '',
             [[gi[a['grade']], a['year'], a['reason'] or '', ui.get(src(a), -1), ti.get(cat.get(a['reason']), -1), mi.get(mk.get(mt(p, a)), -1)] for a in p['awards']]] for p in ps]
    (OUT / 'people.json').write_text(json.dumps({'grades': list(gi), 'states': list(STATES.values()), 'topics': CATS, 'merit': MERIT, 'urls': urls, 'people': rows}, ensure_ascii=False, separators=(',', ':')))
    print(OUT / 'people.json')
    print(c.most_common(), pc.most_common())

if __name__ == '__main__': run()
