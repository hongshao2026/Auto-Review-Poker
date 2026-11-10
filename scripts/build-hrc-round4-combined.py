"""Compose non-overlapping frozen candidate edits and build an isolated kernel."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/cpu-round4-20261108'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def merge(current,old,new):
    a,b=old.splitlines(True),new.splitlines(True)
    for op,lo,hi,nlo,nhi in difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
        if op=='equal':continue
        before=''.join(a[lo:hi]);after=''.join(b[nlo:nhi])
        if not before:
            anchor=''.join(a[lo:lo+3])
            if not anchor or current.count(anchor)!=1:raise ValueError('Ambiguous insertion')
            current=current.replace(anchor,after+anchor,1)
        else:
            if current.count(before)!=1:raise ValueError('Overlapping or ambiguous feature edit: '+before[:100])
            current=current.replace(before,after,1)
    return current

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name',required=True)
    p.add_argument('--features',nargs='+',required=True)
    p.add_argument('--lto',choices=['none','thin','full'],default='none')
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    features={'ci':BASE/'ci/native','shared':BASE/'sync/shared_metadata_table_release',
        'hot192':BASE/'layout/hot-metadata-baseline192/native',
        'hot256':BASE/'layout/hot-metadata-baseline/native',
        'hotindex':BASE/'layout/hot-metadata-index/native',
        'block32':BASE/'sync/block32','block64':BASE/'sync/block64','qos':BASE/'sync/native_qos'}
    if sum(name.startswith('hot') for name in args.features)>1:raise ValueError('Select one metadata layout')
    if sum(name.startswith('block') for name in args.features)>1:raise ValueError('Select one block size')
    original=BASE/'compiler/source'
    assert sha(original/'hrc_research_solver.cpp')=='641453406f885c8a851697eaa27f69636aa8336d41a2091a3f1ffca9a9bdc0b7'
    folder=BASE/'combined'/args.name;folder.mkdir(parents=True,exist_ok=False)
    native=folder/'native';shutil.copytree(original,native)
    applied=[]
    for name in args.features:
        changed=[]
        for old in original.iterdir():
            if old.suffix not in ('.hpp','.h','.cpp'):continue
            candidate=features[name]/old.name
            if not candidate.exists():raise FileNotFoundError(candidate)
            if sha(old)==sha(candidate):continue
            target=native/old.name
            target.write_text(merge(target.read_text('utf-8'),old.read_text('utf-8'),candidate.read_text('utf-8')),encoding='utf-8')
            changed.append(old.name)
        applied.append({'feature':name,'source':str(features[name]),'changed_files':changed})
    compiler_spec=json.loads((BASE/'compiler/variants/thin_lto.json').read_text())['spec']
    compiler=compiler_spec['compiler'];assert sha(compiler)==compiler_spec['compiler_fingerprint']['sha256']
    flags=['-O3','-std=c++17','-ffp-contract=off']
    if args.lto!='none':flags.append('-flto='+args.lto)
    identity={'sources':{f.name:sha(f) for f in sorted(native.iterdir()) if f.is_file()},
              'compiler_fingerprint':compiler_spec['compiler_fingerprint'],'flags':flags,'profile':None,
              'working_directory':str(folder)}
    digest=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    exe=folder/'solver.exe'
    command=[compiler,'c++',*flags,str(native/'hrc_research_solver.cpp'),'-o',str(exe)]
    result={'status':'prepared','features':applied,'build_identity':digest,'identity':identity,
            'command':command,'executable':str(exe)}
    (folder/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    if args.execute:
        start=time.perf_counter();r=subprocess.run(command,cwd=folder,capture_output=True,text=True)
        result.update(returncode=r.returncode,build_seconds=time.perf_counter()-start,stdout=r.stdout,stderr=r.stderr)
        if r.returncode:result['status']='failed'
        else:
            result.update(status='built',executable_sha256=sha(exe))
            probe=subprocess.run([str(exe),'--self-test'],capture_output=True,check=True)
            reference=subprocess.check_output([str(ROOT/'.research-cache/throughput-round3-20261108/accepted/hrc_round3_accepted.exe'),'--self-test'])
            if probe.stdout!=reference:raise ValueError('Combined built-in numeric probe mismatch')
            result['builtin_numeric_probe_equal']=True
        (folder/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
        if r.returncode:raise RuntimeError(r.stderr)
    print(json.dumps({k:result[k] for k in ('status','build_identity','executable')},indent=2))

if __name__=='__main__':main()
