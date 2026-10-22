"""Month-by-month announcement coverage, extraction checks, and source overlap."""
import datetime, json, re
from collections import defaultdict, Counter
from .common import DATA, EXT, docs, write
from .official import OFFICIAL, valid_list
from .merge import norm
from .identity import publisher


def audit(today=None):
    today = today or datetime.date.today()
    months = defaultdict(lambda: defaultdict(list))
    problems = []
    for key, d in docs():
        if d['src'] not in OFFICIAL: continue
        path = EXT / f'{key}.json'
        ex = json.loads(path.read_text()) if path.exists() else {'awards': []}
        aa = ex['awards']
        month = d.get('announcement_month')
        m = re.search(r'Bekanntgabe-Ordensverleihung/(\d{2})(\d{2})', d['url'])
        if not month and m: month = f'20{m[1]}-{m[2]}'
        if not month and d['src'] == 'wikiprojekt':
            dates = [a.get('announced') for a in aa if a.get('announced')]
            if dates: month = Counter(x[:7] for x in dates).most_common(1)[0][0]
        if not month: continue  # ceremony/biography pages are not monthly announcements
        valid = d['src'] == 'wikiprojekt' or valid_list(d['text'])
        issues = []
        if not valid: issues.append('invalid_page')
        if not path.exists(): issues.append('not_extracted')
        elif valid and not aa: issues.append('zero_extracted')
        elif 0 < len(aa) < 10: issues.append('low_count_review')
        doc = {'url': d['url'], 'records': len(aa), 'valid': valid, 'issues': issues,
               'names': sorted({(norm(a['name']), a['grade']) for a in aa})}
        months[month][d['src']].append(doc)
        if issues: problems.append({'month': month, 'source': d['src'], 'url': d['url'], 'issues': issues})
    rows = []
    for y in range(2015, today.year + 1):
        for m in range(1, 13):
            if (y, m) > (today.year, today.month): continue
            month = f'{y}-{m:02d}'; bysrc = months[month]
            sets = {src: set().union(*(set(map(tuple, d['names'])) for d in ds if d['valid'])) for src, ds in bysrc.items()}
            pairs = []
            for i, a in enumerate(OFFICIAL):
                for b in OFFICIAL[i + 1:]:
                    if a in sets and b in sets:
                        pairs.append({'a': a, 'b': b, 'only_a': sorted(sets[a] - sets[b]), 'only_b': sorted(sets[b] - sets[a])})
            rows.append({'month': month, 'sources': {src: {'unique_name_grade_pairs': len(sets.get(src, set())), 'documents': ds} for src, ds in bysrc.items()},
                         'missing_sources': [src for src in OFFICIAL if not sets.get(src)], 'differences': pairs})
    people = json.loads((DATA / 'bvk.json').read_text())
    sources, alone, multi = Counter(), Counter(), 0
    publishers, publisher_alone = Counter(), Counter()
    for p in people:
        ss = {s['via'] for a in p['awards'] for s in a['sources']}
        sources.update(ss)
        groups = {'wikiprojekt' if s['via'] == 'wikiprojekt' else publisher(s['url']) for a in p['awards'] for s in a['sources']}
        publishers.update(groups)
        if len(groups) == 1: publisher_alone.update(groups)
        if len(ss) == 1: alone.update(ss)
        else: multi += 1
    ids = Counter(p['id'] for p in people)
    duplicate_ids = {key: [p['name'] for p in people if p['id'] == key] for key, n in ids.items() if n > 1}
    return {'duplicate_person_ids': duplicate_ids, 'generated_at': datetime.datetime.now(datetime.UTC).isoformat(),
            'source_count_note': 'Source counts describe collection routes attached to merged records, not independent publishers. Publisher counts classify the actual host separately from collection routes. Single-source counts describe the current dataset, not proof that no other publication exists. The historical source_exclusivity_audit.json records the pre-fix investigation.',
            'note': 'Months refer to announcements, not award dates. Missing source pages may be covered by another source. Name differences require review, not automatic addition. The current month may still be pending.',
            'people': len(people), 'awards': sum(len(p['awards']) for p in people),
            'publisher_people': dict(publishers), 'exclusive_publisher_people': dict(publisher_alone),
            'source_people': dict(sources), 'exclusive_source_people': dict(alone), 'multi_source_people': multi,
            'problems': problems, 'months': rows}


def run():
    report = audit(); write(DATA / 'coverage.json', report)
    lines = [f"Recipients: {report['people']}; awards: {report['awards']}", report['note'], '',
             'Month      BPR   WikiProjekt  Bundesanzeiger  Missing sources']
    for row in report['months']:
        counts = [row['sources'].get(s, {}).get('unique_name_grade_pairs', 0) for s in OFFICIAL]
        lines.append(f"{row['month']}  {counts[0]:5}  {counts[1]:11}  {counts[2]:14}  {', '.join(row['missing_sources'])}")
    lines += ['', f"Pre-existing/shared person IDs requiring identity review: {len(report['duplicate_person_ids'])}",
              f"Months with cross-source name/grade differences: {sum(any(d['only_a'] or d['only_b'] for d in row['differences']) for row in report['months'])}"]
    lines += ['', 'Problems:'] + [f"{p['month']} {p['source']} {','.join(p['issues'])}: {p['url']}" for p in report['problems']]
    (DATA / 'coverage.txt').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines[:4])); print(f"{len(report['problems'])} document problems; details in data/coverage.json and data/coverage.txt")

if __name__ == '__main__': run()
