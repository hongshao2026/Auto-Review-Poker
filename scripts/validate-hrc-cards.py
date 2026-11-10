"""Compare original card helpers to independent combinatorial five-card evaluation."""
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis/hrc-deep/probes'
OUT.mkdir(parents=True,exist_ok=True)
JAVA=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
JAR=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')

def five_card(cards):
    ranks=[c//4+2 for c in cards]
    groups=sorted(((count,rank) for rank,count in Counter(ranks).items()),reverse=True)
    unique=sorted(set(ranks),reverse=True)
    straight=5 if unique==[14,5,4,3,2] else (unique[0] if len(unique)==5 and unique[0]-unique[-1]==4 else None)
    flush=len({c%4 for c in cards})==1
    if straight and flush: return (8,straight)
    if groups[0][0]==4: return (7,groups[0][1],groups[1][1])
    if [g[0] for g in groups]==[3,2]: return (6,groups[0][1],groups[1][1])
    if flush: return (5,*sorted(ranks,reverse=True))
    if straight: return (4,straight)
    if groups[0][0]==3: return (3,groups[0][1],*sorted([r for r in ranks if r!=groups[0][1]],reverse=True))
    if [g[0] for g in groups][:2]==[2,2]: return (2,*sorted([g[1] for g in groups if g[0]==2],reverse=True),groups[-1][1])
    if groups[0][0]==2: return (1,groups[0][1],*sorted([r for r in ranks if r!=groups[0][1]],reverse=True))
    return (0,*sorted(ranks,reverse=True))

def rank(mask):
    cards=[i for i in range(52) if mask>>i&1]
    return max(map(five_card,itertools.combinations(cards,5)))

def canonical(mask):
    rank_masks=sorted(sum(((mask>>(4*r+s))&1)<<r for r in range(13)) for s in range(4))
    return sum(((rank_masks[s]>>r)&1)<<(4*r+s) for s in range(4) for r in range(13))

def hand(text):
    ranks='23456789TJQKA'; suits='cdhs'
    return sum(1<<(4*ranks.index(c[0])+suits.index(c[1])) for c in text.split())

cases=[]
fixtures={
    'royal':'Ac Kc Qc Jc Tc 2d 3h', 'wheel_flush':'Ac 2c 3c 4c 5c Kd Qh',
    'quads':'Ac Ad Ah As Kc 2d 3h', 'full_house':'Ac Ad Ah Kc Kd Qh 2s',
    'two_trips':'Ac Ad Ah Kc Kd Kh 2s', 'flush':'Ac Jc 9c 7c 3c Kd Qh',
    'wheel':'Ac 2d 3h 4s 5c Kd Qh', 'straight':'Ac Kd Qh Js Tc 9d 2h',
    'trips':'Ac Ad Ah Kc Qd 8h 2s', 'two_pair':'Ac Ad Kh Ks Qc 8d 2h',
    'pair':'Ac Ad Kh Qs Jc 8d 2h', 'high':'Ac Kd Qh 9s 7c 4d 2h'}
for name,txt in fixtures.items():
    mask=hand(txt)
    for index,p in enumerate(itertools.permutations(range(4))):
        renamed=sum(1<<(4*(i//4)+p[i%4]) for i in range(52) if mask>>i&1)
        cases.append((f'{name}_{index}',renamed))
rng=random.Random(20261104)
for n in (0,1,2,3,4,5,6,7):
    for i in range(30): cases.append((f'canonical_{n}_{i}',sum(1<<c for c in rng.sample(range(52),n))))
for i in range(2000): cases.append((f'random7_{i}',sum(1<<c for c in rng.sample(range(52),7))))
inputs=OUT/'cards-inputs.tsv'
inputs.write_text(''.join(f'{name}\t{mask}\n' for name,mask in cases),encoding='utf-8')
command=[str(JAVA),'-cp',str(ROOT/'analysis/hrc-deep/java-tools'),'OriginalCardsProbe',str(JAR),str(inputs)]
classes=ROOT/'analysis/hrc-deep/java-tools'
classes.mkdir(parents=True,exist_ok=True)
subprocess.run([str(JAVA.with_name('javac.exe')),'-d',str(classes),str(ROOT/'scripts/java/OriginalCardsProbe.java')],check=True,capture_output=True)
run=subprocess.run(command,capture_output=True,text=True)
(OUT/'cards-process-stderr.txt').write_text(run.stderr,encoding='utf-8')
if run.returncode:
    raise RuntimeError(run.stderr)
(OUT/'cards-original-output.jsonl').write_text(run.stdout,encoding='utf-8')
records=[json.loads(line) for line in run.stdout.splitlines()]
failures=[]; ordered=[]; card_count=0; endian_count=0
for r in records:
    if r['kind']=='cards':
        card_count+=1
        if canonical(r['mask'])!=r['canonical'] or r['applied']!=r['canonical'] or sorted(r['permutation'])!=[0,1,2,3]: failures.append({'case':r,'reason':'canonicalization'})
        if r['rank'] is not None: ordered.append((rank(r['mask']),r['rank'],r['id']))
    elif r['kind']=='endian':
        endian_count+=1; data=bytes.fromhex(r['hex']); offset=r['offset']
        for name,size in [('short',2),('int',4),('long',8)]:
            expected=int.from_bytes(data[offset:offset+size],'little',signed=True)
            if r[name]!=expected: failures.append({'case':r,'reason':name,'expected':expected})
# Original short ranks are evaluated for order/tie equivalence, NOT assumed to be a specific public evaluator's IDs.
ordered.sort()
direction=None
for previous,current in zip(ordered,ordered[1:]):
    pscore,prank,_=previous; score,actual,_=current
    if score==pscore:
        if actual!=prank: failures.append({'reason':'equal hand strengths have unequal original ranks','pair':[previous,current]})
    else:
        delta=(actual>prank)-(actual<prank)
        if direction is None: direction=delta
        if delta!=direction or delta==0: failures.append({'reason':'ranking order mismatch','pair':[previous,current]})
summary={'jar_sha256':hashlib.sha256(JAR.read_bytes()).hexdigest(),'command':command,
         'scope':'Original og/oD/lv/lt + unmodified lookup7card.dat.gz only. Evaluation checks hand ordering and ties against exhaustive 5-of-7 oracle, not equality to a separately assumed numeric rank encoding. No abstraction lookup or full solve executed.',
         'cards_cases':card_count,'seven_card_evaluations':len(ordered),'endian_cases':endian_count,'observed_categories':sorted({r[0][0] for r in ordered}),
         'rank_direction':'increasing strength increases original rank' if direction==1 else 'increasing strength decreases original rank',
         'original_inputs':[r for r in records if r['kind'] in ('class','resource')],'passed':not failures,'failures':failures}
(ROOT/'reports/hrc-original-cards-validation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps({k:summary[k] for k in ('cards_cases','seven_card_evaluations','endian_cases','observed_categories','rank_direction','passed')},indent=2))
if failures: print(json.dumps(failures[:3],indent=2));raise SystemExit(1)
