"""Actual production Node vs existing original update/reset/flush snapshots."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_extended_store import ExtendedStore


def main():
    fixture_module=runpy.run_path(str(ROOT/'scripts/validate-hrc-extended-store.py'))
    fixtures=fixture_module['cases']()
    original_records=[json.loads(line) for line in (ROOT/'analysis/hrc-deep/extended-store/original.jsonl').read_text().splitlines()]
    original={r['id']:r for r in original_records if r['kind']=='case'}
    cases=[];payload=bytearray()
    for case in fixtures:
        f,h,k=case['format'],case['h'],case['k'];width=k if f==25 else 2*k+(f==31)
        flat=case['header']+[0.]*(h*width)
        for b,row in case['rows'].items():flat[k+1+b*width:k+1+(b+1)*width]=row
        store=ExtendedStore(f,h,k,struct.pack(f'<{len(flat)}f',*flat))
        for i,operation in enumerate(case['operations']):
            op,*args=operation;before=copy.deepcopy(store)
            if op=='U':store.update(*args)
            elif op=='F':store.flush()
            elif op=='G':store.shared_display()
            elif op=='C':store.set_count(*args)
            elif op=='R':store.reset(*args)
            elif op=='D':store.discount_average(*args)
            elif op=='V':store=store.converted_to_27()
            elif op=='S':store=ExtendedStore(store.format,h,k,store.serialize())
            if op not in ('U','R','F') or before.format not in (27,31):continue
            reference=original[case['id']]['snapshots'][i+1]
            observed=store.snapshot(case['selected'])
            assert observed['raw_sha256']==reference['raw_sha256'] and observed['counter']==reference['counter']
            assert observed['shared_adders']==reference['shared_adders']
            flat=before.flatten();shared=before.shared if before.format==31 else []
            payload.extend(struct.pack('<iiiQI',before.format,h,k,before.counter,len(flat)))
            payload.extend(struct.pack(f'<{len(flat)}dI',*flat,len(shared)))
            payload.extend(struct.pack(f'<{len(shared)}di',*shared,{'U':0,'R':1,'F':2}[op]))
            if op=='U':
                bucket,w,z,rng,p,q=args
                payload.extend(struct.pack(f'<iddi{2*k}d',bucket,w,z,rng,*p,*q))
            elif op=='R':payload.extend(struct.pack('<ii',*args))
            cases.append({'id':case['id'],'step':i+1,'operation':op,'expected':copy.deepcopy(store),'original':reference})
    out=ROOT/'analysis/hrc-deep/extended-store/native';out.mkdir(parents=True,exist_ok=True)
    input_file=out/'inputs.bin';output_file=out/'outputs.bin';input_file.write_bytes(struct.pack('<I',len(cases))+payload)
    source=ROOT/'scripts/native/extended_store_node_probe.cpp';exe=out/'node-probe.exe'
    compile_command=[r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe','c++','-O3','-std=c++17','-ffp-contract=off',str(source),'-o',str(exe)]
    built=subprocess.run(compile_command,capture_output=True,text=True)
    if built.returncode:raise RuntimeError(built.stderr)
    command=[str(exe),str(input_file),str(output_file)];subprocess.run(command,check=True,capture_output=True,text=True)
    data=output_file.read_bytes();cursor=4;assert struct.unpack_from('<I',data)[0]==len(cases);results=[]
    for case in cases:
        counter,n=struct.unpack_from('<QI',data,cursor);cursor+=12;raw_bytes=data[cursor:cursor+8*n];cursor+=8*n
        extra=struct.unpack_from('<I',data,cursor)[0];cursor+=4;sums=list(struct.unpack_from(f'<{extra}d',data,cursor));cursor+=8*extra
        expected=case['expected'];reference=case['original'];raw_hash=hashlib.sha256(raw_bytes).hexdigest()
        raw=list(struct.unpack(f'<{n}d',raw_bytes));errors=[abs(a-b) for a,b in zip(raw,expected.flatten())]
        # Raw SHA also checks all unselected rows, which the original snapshot
        # hashes in full even when only a few rows are printed for readability.
        passed=counter==reference['counter'] and raw_hash==reference['raw_sha256'] and (not extra or sums==reference['shared_adders'])
        results.append({'id':case['id'],'step':case['step'],'operation':case['operation'],'passed':passed,
            'max_abs_error':max(errors),'raw_sha256':raw_hash,'original_raw_sha256':reference['raw_sha256'],
            'counter':counter,'original_counter':reference['counter']})
    assert cursor==len(data)
    report={'scope':'Actual production Node.update/reset/flush versus original mB/mD snapshots. Pre-step states use independently reproduced original raw state. No emulation of absent discount or persistence APIs in harness.',
        'case_count':len(results),'passed':all(r['passed'] for r in results),'max_abs_error':max(r['max_abs_error'] for r in results),'cases':results,
        'compile_command':compile_command,'command':command,
        'source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,Path(__file__),ROOT/'native/hrc_research_solver.cpp',ROOT/'native/hrc_policy.hpp']},
        'evidence_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [input_file,output_file]}}
    (ROOT/'reports/hrc-original-extended-store-native-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('case_count','passed','max_abs_error')},indent=2))
    if not report['passed']:print([c for c in results if not c['passed']][:10]);raise SystemExit(1)


if __name__=='__main__':main()
