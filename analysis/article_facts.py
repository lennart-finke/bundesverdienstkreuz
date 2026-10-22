# Recompute article counts from the dataset and cached classifications; no LLM calls.
# Run: MPLCONFIGDIR=/tmp/bvk-mpl .venv/bin/python -m analysis.article_facts
import json, statistics
from collections import Counter
from pathlib import Path
import analysis.figures as f
ps=json.loads(Path('data/bvk.json').read_text());aw=[(p,a) for p in ps for a in p['awards']];off=[(p,a) for p,a in aw if any(s['via'] in ('bpr','wikiprojekt','bundesanzeiger') for s in a['sources'])]
cat=json.loads(Path('cache/categories.json').read_text());merit=json.loads(Path('cache/merit.json').read_text());party=json.loads(Path('data/party.json').read_text())
c=Counter(cat[a['reason']] for p,a in aw if a['reason']); mc=Counter(merit[(f"Beruf: {p['occupation']}. " if p['occupation'] else '')+f"Begründung: {a['reason']}"] for p,a in aw if a['reason'])
gs=f.gemeinden();pop=Counter();kp=Counter();sc=Counter(p['state'] for p,a in off if p['state']);kc=Counter(f.KREIS.get(p['ags'][:5],p['ags'][:5]) for p,a in off if p['ags'])
for k,x in gs.items():pop[f.STATES[k[:2]]]+=x['pop'];kp[f.KREIS.get(k[:5],k[:5])]+=x['pop']
geo=json.loads(Path('cache/vg2500_krs.json').read_text());names={x['properties']['ags']:x['properties']['gen'] for x in geo['features']}
rate={s:sc[s]/pop[s]*1e5 for s in sc};pc=Counter(x['party'] for x in party if x['party']!='keine');years=sorted({a['year'] for p,a in off})
stats=dict(people=len(ps),awards=len(aw),years=years,age_people=sum(any(a['age'] is not None for a in p['awards']) for p in ps),age_awards=sum(a['age'] is not None for p,a in aw),age_median=statistics.median(a['age'] for p,a in aw if a['age'] is not None),gender_people=sum(bool(f.gender(p)) for p in ps),gender_sources=Counter(p['gender_source'] for p in ps if f.gender(p)),gender_years={y:dict(Counter(f.gender(p) for p,a in aw if a['year']==y and f.gender(p))) for y in years},party=pc,reason_people=sum(any(a['reason'] for a in p['awards']) for p in ps),reason_awards=sum(c.values()),categories=c,merit=mc,official_awards=len(off),state_awards=sum(sc.values()),state_people=len({p['id'] for p,a in off if p['state']}),municipality_awards=sum(bool(p['ags']) for p,a in off),state_rates=rate,saar_sachsen=rate['Saarland']/rate['Sachsen'],top_districts=[{'name':names[k],'total_per100k':kc[k]/kp[k]*1e5,'annual_per100k':kc[k]/kp[k]*1e5/len(years),'awards':kc[k]} for k in sorted(names,key=lambda k:kc[k]/kp[k],reverse=True)[:5]],abroad_people=len({p['id'] for p,a in off if p['country'] and p['country']!='Deutschland'}),abroad_awards=sum(bool(p['country'] and p['country']!='Deutschland') for p,a in off),abroad_countries=len({p['country'] for p,a in off if p['country'] and p['country']!='Deutschland'}),all_countries=len({p['country'] for p in ps if p['country']}),grade_counts=Counter(a['grade'] for p,a in aw))
Path('data/article_facts.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')
