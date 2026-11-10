"""Compare every production dense-table lookup with the original-audited mapper."""
import hashlib
import json
from pathlib import Path
import runpy
import struct
import subprocess
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_dynamic import prepare,_runouts


def main():
    out=ROOT/'analysis/hrc-deep/dynamic-native';out.mkdir(parents=True,exist_ok=True)
    module=runpy.run_path(str(ROOT/'scripts/validate-hrc-dynamic.py'))
    prior=json.loads((ROOT/'reports/hrc-original-dynamic-validation.json').read_text());assert prior['passed']
    cases=[case for case in prior['cases'] if case['kind']=='M']
    source=ROOT/'scripts/native/dynamic_table_probe.cpp';exe=out/'dynamic-probe.exe'
    compile_command=[r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe','c++','-O3','-std=c++17',str(source),'-o',str(exe)]
    built=subprocess.run(compile_command,capture_output=True,text=True)
    if built.returncode:raise RuntimeError(built.stderr)
    results=[];bad=[]
    for case in cases:
        mapping=prepare(case['prefix'],case['street'],case['mode'],module['ranges'](),max_seconds=300)
        path=out/(case['id']+'.hrdyn');mapping.write(path)
        boards=list(_runouts(mapping.prefix,mapping.street));query=out/'queries.bin';output=out/'lookup.bin'
        query.write_bytes(struct.pack('<I',len(boards))+b''.join(struct.pack('<4Q',*history,*([0]*(4-len(history)))) for _,history in boards))
        run=subprocess.run([str(exe),str(path),str(query),str(output)],capture_output=True,text=True)
        if run.returncode:raise RuntimeError(run.stderr)
        observed=np.fromfile(output,dtype='<i4').reshape(len(boards),len(mapping.maps),1326)
        expected_digest=hashlib.sha256();errors=0
        for i,(row,_) in enumerate(boards):
            for p,player in enumerate(mapping.maps):
                values=np.full(1326,-1,dtype='<i4') if player is None else player[row]
                expected_digest.update(values.tobytes());errors+=int(np.count_nonzero(values!=observed[i,p]))
        original_style,_,_=module['independent'](case)
        audited=hashlib.sha256(original_style).hexdigest()==case['original_sha256']
        results.append({'id':case['id'],'passed':errors==0 and audited,'lookups':observed.size,'differences':errors,
            'original_audited':audited,'expected_sha256':expected_digest.hexdigest(),'native_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'cache_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cache_bytes':path.stat().st_size})
        # Keep the independently generated maps for application integration;
        # query/output scratch is overwritten only within this owned folder.
        if len(results)==1:
            original=path.read_bytes()
            for label,payload in [('truncated',original[:-1]),('trailing',original+b'X'),
                    ('invalid_player_index',original[:44]+struct.pack('<i',99)+original[48:])]:
                broken=out/(label+'.hrdyn');broken.write_bytes(payload)
                failure=subprocess.run([str(exe),str(broken),str(query),str(out/'invalid.bin')],capture_output=True,text=True)
                bad.append({'id':label,'passed':failure.returncode!=0,'error':failure.stderr.strip()})
        print(case['id'],errors,flush=True)
    report={'scope':'Production native/hrc_dynamic.hpp reader and complete lookup maps, transitively linked by full digest to original dynamic classes. Includesinactive and zero-range rows as -1 runtime values.',
        'passed':all(r['passed'] for r in results+bad),'case_count':len(results),'lookup_count':sum(r['lookups'] for r in results),
        'cases':results,'malformed_controls':bad,'compile_command':compile_command,
        'source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,ROOT/'native/hrc_dynamic.hpp',ROOT/'preflop_lab/hrc_dynamic.py',Path(__file__)]},
        'original_report_sha256':hashlib.sha256((ROOT/'reports/hrc-original-dynamic-validation.json').read_bytes()).hexdigest()}
    (ROOT/'reports/hrc-original-dynamic-native-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('passed','case_count','lookup_count')},indent=2))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
