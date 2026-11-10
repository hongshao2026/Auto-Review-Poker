"""Audited pure original dynamic keys and per-player complete mapping matrices."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_dynamic import COMBOS, COMBO_ARRAY, key_rows, prepare, _runouts


def histories():
    cards=[(51,28,22,4,1),(0,16,32,44,48),(0,16,33,45,50),(0,1,2,3,48),
           (48,49,24,25,26),(8,12,16,20,24)]
    rng=random.Random(20261105)
    cards.extend(tuple(rng.sample(range(52),5)) for _ in range(6))
    for values in cards:
        flop=sum(1<<c for c in values[:3]);yield (0,flop,flop|(1<<values[3]),flop|(1<<values[3])|(1<<values[4]))


def ranges():
    values=[np.zeros(1326) for _ in range(5)];values[0][:]=1
    values[1][np.isin(np.arange(1326)%11,[1,3])]=.25
    values[2]=None;values[3][[0,1,42,100,777,1325]]=1
    return values


def fixtures(full):
    cases=[]
    for board_index,history in enumerate(histories()):
        for start in (1,2,3):
            for street in range(start,4):
                for mode in ('strict','balanced','relaxed'):
                    cases.append(dict(kind='K',id=f'key_{board_index}_{start}_{street}_{mode}',mode=mode,prefix=history[:start+1],history=history[:street+1]))
    # Every remaining physical board card and all1326 combos are compared,
    # including zero weight, inactive player and suit-equivalent excluded combos.
    for board_index,history in enumerate(list(histories())[:2]):
        for start in (1,2,3):
            for street in range(start,min(start+1,3)+1):
                for mode in ('strict','balanced','relaxed','perfect','none'):
                    cases.append(dict(kind='M',id=f'map_{board_index}_{start}_{street}_{mode}',mode=mode,prefix=history[:start+1],street=street))
    if full:
        history=next(histories())
        for mode in ('strict','balanced','relaxed'):
            cases.append(dict(kind='M',id=f'full_flop_river_{mode}',mode=mode,prefix=history[:2],street=3))
    return cases


def independent(case):
    output=bytearray()
    if case['kind']=='K':
        keys=key_rows(case['prefix'],case['history'],case['mode'])
        for combo,hole in enumerate(COMBOS):
            if hole&case['history'][-1]:continue
            key=keys[combo];output.extend(struct.pack('<ii',combo,len(key)));output.extend(key.tobytes())
        return bytes(output),[],0
    begin=time.perf_counter();mapping=prepare(case['prefix'],case['street'],case['mode'],ranges(),max_seconds=300)
    duration=time.perf_counter()-begin
    for row,history in _runouts(case['prefix'],case['street']):
        output.extend(struct.pack('<i',row))
        for player_map in mapping.maps:
            if player_map is None:output.extend(struct.pack('<i',-1))
            else:output.extend(struct.pack('<i',1326));output.extend(player_map[row].tobytes())
    return bytes(output),mapping.effective,duration


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--full-river',action='store_true');args=parser.parse_args()
    out=ROOT/'analysis/hrc-deep/dynamic';out.mkdir(parents=True,exist_ok=True)
    cases=fixtures(args.full_river);tsv=out/'inputs.tsv'
    def nums(v):return ','.join(map(str,v))
    tsv.write_text('\n'.join('\t'.join((c['kind'],c['id'],c['mode'],nums(c['prefix']),nums(c['history']) if c['kind']=='K' else str(c['street']))) for c in cases)+'\n')
    java=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe');source=ROOT/'scripts/java/OriginalDynamicProbe.java';classes=out/'classes';classes.mkdir(exist_ok=True)
    compile_command=[str(java.with_name('javac.exe')),'-d',str(classes),str(source)];built=subprocess.run(compile_command,capture_output=True,text=True)
    if built.returncode:raise RuntimeError(built.stderr)
    originals=out/'original';originals.mkdir(exist_ok=True)
    command=[str(java),'-Xmx2g','-Djava.util.concurrent.ForkJoinPool.common.parallelism=2','-cp',str(classes),'OriginalDynamicProbe',
             r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar',str(tsv),str(originals)]
    with (out/'original.jsonl').open('w') as log:
        original=subprocess.run(command,stdout=log,stderr=subprocess.PIPE,text=True,timeout=600)
    if original.returncode:raise RuntimeError(original.stderr)
    records=[json.loads(line) for line in (out/'original.jsonl').read_text().splitlines()];byid={r['id']:r for r in records if r['kind']=='result'}
    results=[];failures=[]
    for case in cases:
        data,effective,duration=independent(case);digest=hashlib.sha256(data).hexdigest();reference=byid[case['id']]
        passed=digest==reference['sha256'] and effective==reference['effective']
        result={**case,'passed':passed,'entries':reference['entries'],'original_sha256':reference['sha256'],'independent_sha256':digest,
            'original_effective':reference['effective'],'independent_effective':effective,'python_seconds':duration,'original_nanoseconds':reference['nanoseconds']}
        if not passed:
            original_data=(originals/(case['id']+'.bin')).read_bytes()
            mismatch=next((i for i,(a,b) in enumerate(zip(data,original_data)) if a!=b),None)
            result['first_different_byte']=mismatch;failures.append(result)
        results.append(result)
        if case['kind']=='M':print(case['id'],passed,effective,f'{duration:.3f}s',flush=True)
    report={'scope':'Pure dynamic key and per-player mapper comparison against original classes; no pg, application or source strategy loaded. Full current/one-card future physical-combo mapping; optional full two-card future.',
        'passed':not failures,'full_flop_river':args.full_river,'key_cases':sum(c['kind']=='K' for c in cases),'mapping_cases':sum(c['kind']=='M' for c in cases),
        'key_comparisons':sum(c['entries'] for c in results if c['kind']=='K'),'mapping_comparisons':sum(c['entries'] for c in results if c['kind']=='M'),
        'cases':results,'failures':failures,'compile_command':compile_command,'command':command,'loaded_classes':[r for r in records if r['kind']=='class'],
        'source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,Path(__file__),ROOT/'preflop_lab/hrc_dynamic.py']},
        'evidence_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [tsv,out/'original.jsonl']}}
    (ROOT/'reports/hrc-original-dynamic-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('passed','key_cases','mapping_cases','key_comparisons','mapping_comparisons')},indent=2))
    if failures:print([(r['id'],r['first_different_byte']) for r in failures][:20]);raise SystemExit(1)


if __name__=='__main__':main()
