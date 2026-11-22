import csv, glob, collections, unicodedata, sys
base=sys.argv[1]
def norm(s): return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c)).lower().replace('.','').replace(' jr','').replace(' ii','').replace(' iii','').replace(' iv','').strip()
fg2={}; birth={}
for f in glob.glob(base+'/chad/p*.csv'):
    for r in csv.DictReader(open(f,encoding='utf-8')):
        if r['key_mlbam']:
            birth[r['key_mlbam']]='-'.join(x.zfill(2) for x in (r['birth_year'],r['birth_month'],r['birth_day'])) if r['birth_year'] else ''
            if r['key_fangraphs']: fg2[r['key_fangraphs']]=r['key_mlbam']
num=lambda x: float(x) if x not in ('','NULL') else 0.0
bat=collections.defaultdict(lambda: dict(pa=0,war=0,off=0,dfn=0,name=''))
for r in csv.DictReader(open(base+'/warzip/war_daily_bat.txt',encoding='utf-8',errors='replace')):
    if r['year_ID']!='2026': continue
    b=bat[r['mlb_ID']]; b['name']=r['name_common']
    b['pa']+=num(r['PA']); b['war']+=num(r['WAR']); b['off']+=num(r['WAR_off']); b['dfn']+=num(r['WAR_def'])
pit=collections.defaultdict(lambda: dict(ipo=0,war=0,name=''))
for r in csv.DictReader(open(base+'/warzip/war_daily_pitch.txt',encoding='utf-8',errors='replace')):
    if r['year_ID']!='2026': continue
    p=pit[r['mlb_ID']]; p['name']=r['name_common']; p['ipo']+=num(r['IPouts']); p['war']+=num(r['WAR'])
byname=collections.defaultdict(set)
for m,v in list(bat.items())+list(pit.items()): byname[norm(v['name'])].add(m)
roster=[r for r in csv.DictReader(open(base+'/mwbl-data/2026/contracts.csv')) if r['ID']!='UNK']
stats={r['ID']:r for r in csv.DictReader(open(base+'/mwbl-data/2026/roster-stats.csv'))}
rows=[];seen=set();report=collections.Counter();amb=[];miss=[]
for r in roster:
    if r['ID'] in seen: continue
    seen.add(r['ID'])
    m=fg2.get(r['ID']); how='chadwick'
    if not m or (m not in bat and m not in pit):
        cands=byname.get(norm(r['Name']),set())
        if len(cands)==1: m=next(iter(cands)); how='name'
        elif len(cands)>1: amb.append((r['Name'],sorted(cands))); m=None
        elif not m: how='none'
    b=bat.get(m) if m else None; p=pit.get(m) if m else None
    has_stats=r['ID'] in stats
    if has_stats and not b and not p: miss.append((r['Name'],r['ID']))
    report[how if (b or p) else ('nostats_'+how)]+=1
    rows.append([r['ID'],r['Name'],m or '',birth.get(m,'') if m else '',how,
        int(b['pa']) if b else '',round(b['off'],2) if b else '',round(b['dfn'],2) if b else '',round(b['war'],2) if b else '',
        round(p['ipo']/3,1) if p else '',round(p['war'],2) if p else ''])
with open(base+'/mwbl-data/2026/war.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['ID','Name','mlbam','birth','match','PA','off_war','def','bat_war','IP','war']); w.writerows(rows)
print(report); print("ambiguous:",amb); print("sheet has MLB stats but no WAR:",miss)
