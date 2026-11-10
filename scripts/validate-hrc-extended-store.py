"""Reproduce independent storage reference versus allowlisted original bytecode."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_extended_store import ExtendedStore


def cases():
    result = []
    for format in (27, 31):
        for k in (2, 3, 4, 8):
            width = 2*k + (format == 31)
            h = 3
            rows = {0: [3., -2.] + [0.]*(k-2) + ([.5] if format==31 else []) + [float(a+1) for a in range(k)],
                    2: [-float(a+1) for a in range(k)] + ([0.] if format==31 else []) + [0.]*k}
            p = [1/k]*k
            q = [float(a-1) for a in range(k)]
            base = [('U',0,.7,.25,1,p,q), ('U',2,1.,.4,1,p,q), ('U',0,0.,9.,0,p,q), ('U',1,-1.,9.,0,p,q),
                    ('U',0,1.3,0.,0,p,q), ('F',), ('S',), ('C',100.25), ('U',1,.5,.3,1,p,q)]
            for reset in ((1,0),(0,1),(1,1)):
                result.append(dict(id=f'store{format}_k{k}_reset{reset[0]}{reset[1]}',format=format,h=h,k=k,
                    header=[100.25]+[float(a+1) for a in range(k)],rows=rows,selected=[0,1,2],
                    operations=base+[('R',*reset),('G',),('D',.25),('S',)]))
    # The previous cases deliberately reset unflushed adders; separately test
    # the application-safe flush-then-discount order and multi-block offsets.
    for k in (2,3,8):
        h=16384//(2*k+1)+2; selected=[0,h-3,h-2,h-1]
        result.append(dict(id=f'chunk_boundary_k{k}',format=31,h=h,k=k,header=[16.]+[0.]*k,
            rows={b:[float(a+1) for a in range(k)]+[2.]+[1.]*k for b in selected},selected=selected,
            operations=[('U',h-2,.8,.6,1,[1/k]*k,list(range(k))),('F',),('D',.5),('S',)]))
    for k in (2,3,4):
        result.append(dict(id=f'convert25_k{k}',format=25,h=3,k=k,header=[9.25]+[float(a+2) for a in range(k)],
            rows={0:[-float(a+1) for a in range(k)],1:[0.]*k,2:[float(a+1) for a in range(k)]},selected=[0,1,2],
            operations=[('V',),('U',2,.7,.9,0,[1/k]*k,list(range(k))),('S',)]))
    return result


def simulate(case):
    f,h,k=case['format'],case['h'],case['k'];width=k if f==25 else 2*k+(f==31)
    flat=case['header']+[0.]*(h*width)
    for b,values in case['rows'].items():flat[k+1+b*width:k+1+(b+1)*width]=values
    store=ExtendedStore(f,h,k,struct.pack(f'<{len(flat)}f',*flat))
    snapshots=[store.snapshot(case['selected'])];serialized=[]
    for operation in case['operations']:
        op,*args=operation
        if op=='U':store.update(*args)
        elif op=='F':store.flush()
        elif op=='G':store.shared_display()
        elif op=='C':store.set_count(*args)
        elif op=='R':store.reset(*args)
        elif op=='D':store.discount_average(*args)
        elif op=='V':store=store.converted_to_27()
        elif op=='S':
            data=store.serialize();serialized.append(hashlib.sha256(data).hexdigest())
            store=ExtendedStore(store.format,h,k,data)
        snapshots.append(store.snapshot(case['selected']))
    return dict(id=case['id'],snapshots=snapshots,serialized_sha256=serialized)


def main():
    out=ROOT/'analysis/hrc-deep/extended-store';out.mkdir(parents=True,exist_ok=True)
    fixtures=cases(); lines=[]
    nums=lambda values:','.join(map(str,values))
    for c in fixtures:
        ops=[';'.join(nums(v) if isinstance(v,list) else str(v) for v in op) for op in c['operations']]
        lines.append('\t'.join([c['id'],str(c['format']),str(c['h']),str(c['k']),nums(c['header']),
            ';'.join(str(b)+':'+nums(row) for b,row in c['rows'].items()),nums(c['selected']),'|'.join(ops)]))
    tsv=out/'inputs.tsv';tsv.write_text('\n'.join(lines)+'\n')
    java=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
    source=ROOT/'scripts/java/OriginalExtendedStoreProbe.java';classes=out/'classes';classes.mkdir(exist_ok=True)
    compile_command=[str(java.with_name('javac.exe')),'-d',str(classes),str(source)]
    subprocess.run(compile_command,check=True,capture_output=True,text=True)
    command=[str(java),'-cp',str(classes),'OriginalExtendedStoreProbe',r'D:\Program Files\HRC\plugins',str(tsv)]
    original=subprocess.run(command,capture_output=True,text=True)
    if original.returncode:
        raise RuntimeError(original.stderr)
    (out/'original.jsonl').write_text(original.stdout)
    records=[json.loads(line) for line in original.stdout.splitlines()];byid={r['id']:r for r in records if r['kind']=='case'}
    summaries=[];failures=[]
    def compare(expected,observed,path):
        if isinstance(expected,dict):
            for key in expected:
                if key!='kind':compare(expected[key],observed.get(key),path+'/'+key)
        elif isinstance(expected,list):
            if not isinstance(observed,list) or len(expected)!=len(observed):failures.append((path,'length'));return
            for i,(a,b) in enumerate(zip(expected,observed)):compare(a,b,path+'/'+str(i))
        elif expected!=observed:
            if isinstance(expected,(int,float)) and isinstance(observed,(int,float)) and abs(expected-observed)<=1e-10*max(1,abs(expected)):
                return
            failures.append((path,expected,observed))
    for case in fixtures:
        independent=simulate(case);before=len(failures);compare(independent,byid[case['id']],case['id'])
        summaries.append({'id':case['id'],'snapshots':len(independent['snapshots']),'passed':before==len(failures)})
    report={'scope':'Sequential original formats25/27/31 storage update, cached counters, reset/discount, serialization, chunk boundaries and25to27 conversion. No thread race equivalence claim.',
        'case_count':len(fixtures),'snapshot_count':sum(c['snapshots'] for c in summaries),'cases':summaries,'fixtures':fixtures,
        'failures':failures,'passed':not failures,'compile_command':compile_command,'command':command,
        'loaded_classes':[r for r in records if r['kind']=='class'],
        'source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,Path(__file__),ROOT/'preflop_lab/hrc_extended_store.py']},
        'evidence_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [tsv,out/'original.jsonl']}}
    (ROOT/'reports/hrc-original-extended-store-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('case_count','snapshot_count','passed','failures')},indent=2))
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
