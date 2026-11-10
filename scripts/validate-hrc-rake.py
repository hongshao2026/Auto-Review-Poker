"""Compare complete rank-ordered raked settlement with original lC/lK/lH."""
import hashlib
import json
from pathlib import Path
import random
import subprocess

ROOT=Path(__file__).resolve().parents[1]
JAVA=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
ZIG=Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
JAR=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')


def cases():
    out=[]
    def add(name,remaining,paid,folded,ranks,dead=0,street=0,raises=0):
        for mode in range(4):
            for fraction,cap in ((0,100),(.05,100),(.025,3),(.5,1),(1.,10000)):
                out.append(dict(id=f'{name}_{mode}_{fraction}_{cap}',remaining=remaining,paid=paid,folded=folded,
                    ranks=ranks,dead=dead,street=street,raises=raises,mode=mode,fraction=fraction,cap=cap))
    add('multi_pots',[0,0,0],[100,200,300],0,[3,2,1])
    add('best_side_pot_first',[0,0,0],[100,200,300],0,[1,3,2])
    add('unequal_tie',[0,0,0],[100,200,300],0,[3,3,2],dead=1)
    add('fold',[100,100,100],[50,100,1],5,[0,1,0])
    add('fold_postflop',[100,100,100],[50,100,1],5,[0,1,0],street=1)
    add('fold_3bet',[100,100,100],[50,100,1],5,[0,1,0],raises=2)
    add('fold_raised',[100,100,100],[50,100,1],5,[0,1,0],raises=1)
    add('odd_threeway',[0,0,50,1],[100,100,100,1],8,[4,4,4,0])
    rng=random.Random(20261105)
    for n in range(2,11):
        for v in range(6):
            paid=[rng.randint(1,300) for _ in range(n)]
            remaining=[rng.choice([0,50,100]) for _ in range(n)]
            live=rng.sample(range(n),rng.randint(1,n))
            folded=sum(1<<i for i in range(n) if i not in live)
            for i in range(n):
                if i not in live:remaining[i]=50
            add(f'random_{n}_{v}',remaining,paid,folded,[rng.randint(0,4) for _ in range(n)],
                dead=rng.randint(0,20),street=v%4,raises=v%3)
    return out


def line(c):
    return '\t'.join(map(str,[c['id'],','.join(map(str,c['remaining'])),','.join(map(str,c['paid'])),c['folded'],
                              ','.join(map(str,c['ranks'])),c['dead'],c['street'],c['raises'],c['mode'],c['fraction'],c['cap']]))


def main():
    directory=ROOT/'analysis/hrc-deep/rake'
    directory.mkdir(parents=True,exist_ok=True)
    fixtures=cases();text='\n'.join(line(c) for c in fixtures)+'\n'
    inputs=directory/'inputs.tsv';inputs.write_text(text)
    sources=[ROOT/'scripts/java'/n for n in ('OriginalTreeProbe.java','OriginalRakeProbe.java')]
    subprocess.run([str(JAVA.with_name('javac.exe')),'-d',str(directory),*map(str,sources)],check=True,capture_output=True,text=True)
    original=subprocess.run([str(JAVA),'-cp',str(directory),'OriginalRakeProbe',str(JAR),str(inputs)],capture_output=True,text=True)
    (directory/'original.jsonl').write_text(original.stdout)
    if original.returncode:raise RuntimeError(original.stderr[-4000:])
    source=ROOT/'scripts/native/settlement_probe.cpp';exe=directory/'settlement.exe'
    subprocess.run([str(ZIG),'c++','-O3','-std=c++17','-ffp-contract=off',str(source),'-o',str(exe)],check=True,capture_output=True,text=True)
    native=subprocess.run([str(exe)],input=text,check=True,capture_output=True,text=True)
    (directory/'independent.jsonl').write_text(native.stdout)
    originals={r['id']:r for r in map(json.loads,original.stdout.splitlines()) if r['kind']=='case'}
    computed={r['id']:r for r in map(json.loads,native.stdout.splitlines())}
    rows=[]
    for case in fixtures:
        a,b=originals[case['id']],computed[case['id']]
        fields=('stacks','winner_masks','rake','pots','tied_award')
        agrees = bool(b.get('error')) if a.get('error') else all(a[f]==b.get(f) for f in fields)
        rows.append({'input':case,'original':a,'independent':b,'passed':agrees})
    report={'artifact':str(JAR),'sha256':hashlib.sha256(JAR.read_bytes()).hexdigest(),
            'scope':'Original lC snapshot, lK street sweep, lH rank-overload; no card evaluator/GUI/license/solver. Synthetic terminal states include arbitrary valid chip vectors, not all reachable action sequences. Preflop raise counts supplied through original ly actions.',
            'cases':len(rows),'passed':all(r['passed'] for r in rows),'results':rows,
            'header_sha256':hashlib.sha256((ROOT/'native/hrc_settlement.hpp').read_bytes()).hexdigest(),
            'class_hashes':[r for r in map(json.loads,original.stdout.splitlines()) if r['kind']=='class']}
    (ROOT/'reports/hrc-original-rake-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'cases':len(rows),'passed':report['passed'],'failed':[r for r in rows if not r['passed']][:4]}))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
