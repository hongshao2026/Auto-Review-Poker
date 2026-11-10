"""Validate installed16384 profiles and complete fixed-flop compression maps."""
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
from preflop_lab.hrc_dynamic import _runouts
from preflop_lab.hrc_resource_dynamic import ProfileTable, prepare_profile_resources, prepare_resource


def run(command):
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    if result.returncode:raise RuntimeError(result.stderr)
    return result.stdout


def main():
    plugins=Path(r'D:\Program Files\HRC\plugins');jdk=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
    cache=ROOT/'.research-cache/subtree-resources';out=ROOT/'analysis/hrc-deep/resource-dynamic';out.mkdir(parents=True,exist_ok=True)
    manifest=prepare_profile_resources(plugins,cache,board_cache=ROOT/'.research-cache/abstractions')
    module=runpy.run_path(str(ROOT/'scripts/validate-hrc-dynamic.py'))
    ranges=module['ranges']();cases=[]
    for i,history in enumerate(list(module['histories']())[:2]):
        for street in (2,3):cases.append(dict(id=f'resource_{i}_{street}',prefix=list(history),street=street))
    inputs=out/'inputs.tsv';inputs.write_text('\n'.join(f"{c['id']}\t{c['street']}\t{c['prefix'][1]}" for c in cases)+'\n')
    source=ROOT/'scripts/java/OriginalResourceDynamicProbe.java';helper=ROOT/'scripts/java/OriginalFlopBucketProbe.java';classes=out/'classes';classes.mkdir(exist_ok=True)
    brotli=plugins/'net.holdemresources.calculator.mavendependencies_0.2.0/org.brotli/dec-0.1.2.jar'
    run([str(jdk/'javac.exe'),'-cp',str(brotli),'-d',str(classes),str(helper),str(source)])
    original_command=[str(jdk/'java.exe'),'-Xmx2g','-cp',str(classes)+';'+str(brotli),'OriginalResourceDynamicProbe',str(plugins/'net.holdemresources.calculator_4.1.0.202603231401.jar'),str(plugins/'org.eclipse.collections_11.1.0.v20220705-1455.jar'),str(cache),str(inputs),str(out/'original')]
    raw=run(original_command);(out/'original.jsonl').write_text(raw);records=[json.loads(line) for line in raw.splitlines()];byid={r['id']:r for r in records if r['kind']=='result'}
    native_source=ROOT/'scripts/native/dynamic_table_probe.cpp';exe=out/'resource-table-probe.exe'
    compile_command=[r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe','c++','-O3','-std=c++17',str(native_source),'-o',str(exe)];run(compile_command)
    results=[];tables={street:ProfileTable(cache,street) for street in (2,3)}
    for case in cases:
        mapping=prepare_resource(case['prefix'],case['street'],ranges,tables[case['street']],max_seconds=120)
        payload=bytearray();boards=list(_runouts(mapping.prefix,mapping.street))
        for row,history in boards:
            payload.extend(struct.pack('<i',row))
            for player in mapping.maps:
                if player is None:payload.extend(struct.pack('<i',-1))
                else:payload.extend(struct.pack('<i',1326));payload.extend(player[row].tobytes())
        reference=byid[case['id']];digest=hashlib.sha256(payload).hexdigest();cache_path=out/(case['id']+'.hrdyn');mapping.write(cache_path)
        queries=out/'queries.bin';output=out/'native.bin';queries.write_bytes(struct.pack('<I',len(boards))+b''.join(struct.pack('<4Q',*history,*([0]*(4-len(history)))) for _,history in boards))
        run([str(exe),str(cache_path),str(queries),str(output)])
        actual=np.fromfile(output,dtype='<i4').reshape(len(boards),len(mapping.maps),1326);errors=0;expected_hash=hashlib.sha256()
        for i,(row,_) in enumerate(boards):
            for p,player in enumerate(mapping.maps):
                values=np.full(1326,-1,dtype='<i4') if player is None else player[row];errors+=int(np.count_nonzero(actual[i,p]!=values));expected_hash.update(values.tobytes())
        passed=digest==reference['sha256'] and mapping.effective==reference['effective'] and errors==0
        results.append(dict(**case,passed=passed,entries=reference['entries'],original_sha256=reference['sha256'],independent_sha256=digest,effective=mapping.effective,
            native_lookups=actual.size,native_differences=errors,native_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),expected_native_sha256=expected_hash.hexdigest(),
            cache_sha256=hashlib.sha256(cache_path.read_bytes()).hexdigest()))
        print(case['id'],passed,mapping.effective,flush=True)
    report=dict(scope='Original oh/ol base16384 profiles + oo/on compressed mapper. Turn calls originaloo.a factory; river reachable-ID construction replays staticqa lines229-263, not qa execution. Complete two-fixed-flop domains; C++ productionreader comparison.',
        passed=all(r['passed'] for r in results),cases=results,case_count=len(results),original_entries=sum(r['entries'] for r in results),native_lookups=sum(r['native_lookups'] for r in results),
        profile_manifest=manifest,original_command=original_command,compile_command=compile_command,allowlist=[r for r in records if r['kind']=='allowlist'],
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,helper,native_source,ROOT/'preflop_lab/hrc_resource_dynamic.py',ROOT/'native/hrc_dynamic.hpp',Path(__file__)]},input_sha256=hashlib.sha256(inputs.read_bytes()).hexdigest())
    (ROOT/'reports/hrc-original-resource-dynamic-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('passed','case_count','original_entries','native_lookups')},indent=2))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
