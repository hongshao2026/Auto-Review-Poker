"""Original mz enable/disable vs independent migration formulas and policy math."""
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_policy import FrequencyStore


def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]


def simulate(format,k):
    h=2;width=k if format==25 else 2*k+(format!=27);header=1 if format==23 else k+1
    initial=[f32((i%7-2)/3) for i in range(header+h*width)];initial[0]=16.5
    if format in (23,31):
        for b in range(h):initial[header+b*width+k]=float(b+2)
    targets=[.4]+[None]*(k-1);edges=[0.]*(k-1)+[.75]
    store=FrequencyStore(h,k,targets,edges,format)
    if format==23:
        # mz.a(mx,targets,edges) serializes/restores the freshly wrapped store
        # while injecting old rows, quantizing even the new targets to float32.
        store.targets=[f32(t) if not math.isnan(t) else t for t in store.targets]
        store.edges=[f32(e) for e in store.edges]
        store.raw[k+1:]=initial[1:]
        store.reset(True,True)
    store.sync_from_raw()
    def snap():
        return {'raw':store.raw[:],'targets':['NaN' if math.isnan(t) else t for t in store.targets],
            'edges':store.edges[:],'edge_sums':store.edge_sums[:],'shared_sums':store.shared_sums[:],
            'updates':store.updates,'minimum':store.minimum,'maximum':store.maximum}
    enabled=snap()
    store.update(0,[1/k]*k,[a*2-1. for a in range(k)],.7,.4,lambda n:1%int(math.sqrt(n))==0)
    updated=snap();store.flush()
    store.targets=[.65]+[math.nan]*(k-1);store.edges=[0.]+[-.25*a for a in range(1,k)];store.edge_sums=store.edges[:]
    edited=snap();store.flush()
    if format==23:restored=[f32(store.raw[0])]+[f32(x) for x in store.raw[k+1:]]
    elif format==31:restored=[f32(x) for x in store.raw]
    else:restored=[0.]*len(initial)
    return dict(kind='case',id=f'migration_{format}_{k}',format=format,actions=k,initial=initial,
        enabled=enabled,updated=updated,edited=edited,restored_format=format,restored_raw=restored)


def main():
    out=ROOT/'analysis/hrc-deep/store-migration';out.mkdir(parents=True,exist_ok=True)
    classes=out/'classes';classes.mkdir(exist_ok=True)
    java=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
    sources=[ROOT/'scripts/java/OriginalExtendedStoreProbe.java',ROOT/'scripts/java/OriginalStoreMigrationProbe.java']
    compile_command=[str(java.with_name('javac.exe')),'-d',str(classes),*map(str,sources)]
    subprocess.run(compile_command,check=True,capture_output=True,text=True)
    command=[str(java),'-cp',str(classes),'OriginalStoreMigrationProbe',r'D:\Program Files\HRC\plugins']
    run=subprocess.run(command,capture_output=True,text=True)
    if run.returncode:raise RuntimeError(run.stderr)
    evidence=out/'original.jsonl';evidence.write_text(run.stdout)
    records=[json.loads(line) for line in run.stdout.splitlines()];failures=[];errors=[];cases=[]
    def compare(a,b,path):
        if isinstance(a,dict):
            for key in a:compare(a[key],b.get(key),path+'/'+key)
        elif isinstance(a,list):
            if not isinstance(b,list) or len(a)!=len(b):failures.append([path,'length']);return
            for i,(x,y) in enumerate(zip(a,b)):compare(x,y,path+'/'+str(i))
        elif isinstance(a,(float,int)) and isinstance(b,(float,int)):
            errors.append(abs(a-b))
            if abs(a-b)>1e-12*max(1,abs(a)):failures.append([path,a,b])
        elif a!=b:failures.append([path,a,b])
    for row in records:
        if row['kind']!='case':continue
        before=len(failures);compare(simulate(row['format'],row['actions']),row,row['id']);cases.append({'id':row['id'],'passed':before==len(failures)})
    report={'scope':'Original pure mz enable/unwrap methods, including formats23/25/27/31. Existing-target edit replays audited fi field assignments after its flush; actual GUI execute was not run.',
        'cases':cases,'case_count':len(cases),'passed':not failures,'failures':failures,'max_abs_error':max(errors),
        'compile_command':compile_command,'command':command,'loaded_classes':[r for r in records if r['kind']=='class'],
        'source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources+[Path(__file__),ROOT/'preflop_lab/hrc_policy.py']},
        'evidence_sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
    (ROOT/'reports/hrc-original-store-migration-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('case_count','passed','max_abs_error','failures')},indent=2))
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
