"""Scripted original lw/lu/dependency vs independent Python/native mode-1 deals."""
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_chance import ChanceSampler, ChanceResourceLimit


def histories():
    flop=(1<<40)|(1<<44)|(1<<48)
    return [(0,), (0,flop), (0,flop,flop|(1<<50)), (0,flop,flop|(1<<50),flop|(1<<50)|(1<<51))]


def fixtures():
    rng=random.Random(2026110503)
    common_ints=[rng.randrange(1<<31) for _ in range(2500)]
    result=[]
    def add(name,prefix,rows,doubles=None,skip=-1,expected_failure=False):
        result.append(dict(id=name,prefix=prefix,rows=rows,doubles=doubles or [rng.random() for _ in range(2500)],
                           integers=common_ints,skip=skip,expected_failure=expected_failure))
    for i,prefix in enumerate(histories()):
        for players in (1,2,6,9,10):
            add(f'uniform_{i}_{players}',prefix,['-']*players)
            add(f'full_weighted_{i}_{players}',prefix,['1|']*players)
            add(f'mixed_{i}_{players}',prefix,['-' if p%2 else '1|' for p in range(players)])
    for i in range(80):
        players=rng.randrange(2,11);rows=[]
        for p in range(players):
            if p%4==3:rows.append('-');continue
            values=[(c,0.0 if rng.random()<.15 else 10**rng.uniform(-3,3)) for c in range(1326)]
            rows.append('0|'+','.join(f'{c}:{v!r}' for c,v in values))
        add(f'weighted_{i}',histories()[i%4],rows)
    add('whole_assignment_retry',histories()[1],['0|0:1,5:1','0|1:1,14:1'],[.1,.1,.9,.9])
    add('inclusive_cdf_half',histories()[3],['0|0:1,5:1'],[.5])
    add('above_cdf_half',histories()[3],['0|0:1,5:1'],[math.nextafter(.5,1)])
    add('zero_endpoint',histories()[3],['0|100:1'],[0.0])
    add('positive_endpoint',histories()[3],['0|100:1'],[math.nextafter(0,1)])
    add('last_endpoint',histories()[3],['0|100:1'],[math.nextafter(1,0)])
    for exponent in (-200,200):
        add(f'scale_{exponent}',histories()[2],[f'{10.**exponent!r}|','-',f'{10.**exponent!r}|'])
    for skip in range(3):
        add(f'uniform_target_{skip}',histories()[1],['0|100:1,200:2,300:3','1|','-'],skip=skip)
    add('impossible_overlap',histories()[3],['0|0:1','0|0:1'],[.5],expected_failure=True)
    return result


def parse_rows(rows):
    result=[]
    for text in rows:
        if text=='-':result.append(None);continue
        default,terms=text.split('|');weights=[float(default)]*1326
        if terms:
            for term in terms.split(','):
                combo,weight=term.split(':');weights[int(combo)]=float(weight)
        result.append(weights)
    return result


def independent(case):
    calls=bytearray();di=ii=0
    def real():
        nonlocal di
        u=case['doubles'][di%len(case['doubles'])];di+=1;calls.extend(struct.pack('<id',0,u));return u
    def integer(bound):
        nonlocal ii
        n=case['integers'][ii%len(case['integers'])]%bound;ii+=1;calls.extend(struct.pack('<iq',bound,n));return n
    sampler=ChanceSampler(parse_rows(case['rows']),case['prefix'],max_attempts=10000)
    try:
        deal=sampler.sample_callbacks(integer,real,skip_player=case['skip'])
        output=dict(status='ok',combos=list(deal.combos),board=list(deal.board_history),used=deal.used_mask,attempts=deal.attempts)
    except ChanceResourceLimit:
        output=dict(status='resource_limit')
    return dict(output,double_calls=di,integer_calls=ii,calls_sha256=hashlib.sha256(calls).hexdigest())


def run(command,**kwargs):
    output=subprocess.run(command,capture_output=True,text=True,timeout=120,**kwargs)
    if output.returncode:raise RuntimeError(output.stderr)
    return output.stdout


def main():
    out=ROOT/'analysis/hrc-deep/chance';out.mkdir(parents=True,exist_ok=True)
    cases=fixtures();tsv=out/'inputs.tsv'
    tsv.write_text('\n'.join('\t'.join((c['id'],','.join(map(str,c['prefix'])),';'.join(c['rows']),','.join(map(repr,c['doubles'])),','.join(map(str,c['integers'])),str(c['skip']))) for c in cases)+'\n')
    java=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe');classes=out/'classes';classes.mkdir(exist_ok=True)
    source=ROOT/'scripts/java/OriginalChanceProbe.java'
    run([str(java.with_name('javac.exe')),'-d',str(classes),str(source)])
    original_command=[str(java),'-Xmx512m','-cp',str(classes),'OriginalChanceProbe',r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar',r'D:\Program Files\HRC\plugins\net.holdemresources.calculator.mavendependencies_0.2.0\org.apache.commons',str(tsv)]
    raw=run(original_command);(out/'original.jsonl').write_text(raw)
    original=[json.loads(line) for line in raw.splitlines()];byid={c['id']:c for c in original if c['kind']=='result'}
    native_source=ROOT/'scripts/native/chance_probe.cpp';exe=out/'chance-probe.exe'
    compile_command=[r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe','c++','-O3','-std=c++17',str(native_source),'-o',str(exe)]
    run(compile_command);native_out=out/'native';native_out.mkdir(exist_ok=True)
    raw_native=run([str(exe),str(tsv),str(native_out)]);(out/'native.jsonl').write_text(raw_native)
    natives={c['id']:c for c in map(json.loads,raw_native.splitlines())}
    results=[]
    for case in cases:
        ref=byid[case['id']];ind=independent(case);native=natives[case['id']]
        native['calls_sha256']=hashlib.sha256((native_out/(case['id']+'.calls')).read_bytes()).hexdigest()
        keys=['double_calls','integer_calls','calls_sha256']
        if case['expected_failure']:
            success=ref['used']==-1 and ref['combos']==[-1]*len(case['rows']) and ref['cancel_checks']==1 and ind['status']==native['status']=='resource_limit'
        else:
            success=ind['status']==native['status']=='ok';keys+=['combos','board','used','attempts']
        success=success and all(ref[key]==ind[key]==native[key] for key in keys)
        results.append(dict(id=case['id'],passed=success,original=ref,python=ind,native=native))
    report=dict(scope='Fixed-board mode-1 lw whole-assignment rejection, Commons GuideTable CDF, lu missing-board fill; scripted random values, not PRNG seed equivalence or mn mode-2 training.',
        passed=all(r['passed'] for r in results),case_count=len(results),cases=results,
        original_class_hashes=[r for r in original if r['kind']=='class'],original_command=original_command,compile_command=compile_command,
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,native_source,ROOT/'preflop_lab/hrc_chance.py',ROOT/'native/hrc_chance.hpp',Path(__file__)]},
        input_sha256=hashlib.sha256(tsv.read_bytes()).hexdigest(),controls='Original impossible joint range returns all -1 after its10000-attempt cancellation check; independent implementations raise explicitResourceLimit at10000. More responsive cooperative cancellation is intentional.')
    (ROOT/'reports/hrc-original-chance-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':report['passed'],'cases':len(results),'failures':[r for r in results if not r['passed']]},indent=2))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
