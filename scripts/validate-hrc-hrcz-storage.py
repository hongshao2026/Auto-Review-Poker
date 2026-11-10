"""Original mx save/load and pY lock-setter replay against independent codec."""
import base64
from array import array
import hashlib
import json
import math
from pathlib import Path
import runpy
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from preflop_lab import hrc_hrcz_storage as codec

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    folder=ROOT/'analysis/hrc-deep/hrcz-storage';folder.mkdir(parents=True,exist_ok=True)
    classes=folder/'classes';classes.mkdir(exist_ok=True)
    decision=runpy.run_path(str(ROOT/'tests/test_hrc_hrcz_storage.py'))['decision']
    cases=[]
    for fmt,base in [(23,23),(25,25),(27,27),(31,31),(63,23),(63,25),(63,27),(63,31)]:
        for h in (1,7):
            for k in (2,3,4):
                record=decision(fmt,h,k,counter=16.5,base=base)
                cases.append((f'plain_{fmt}_{base}_{h}_{k}',record))
    for fmt in (23,27,31):
        for weights in ((.4,),(.1,.9),(.4,.6)):
            record=decision(fmt,3,2,counter=60000501)
            record['locks']={a:array('f',[value]*3) for a,value in enumerate(weights)}
            cases.append((f'locks_{fmt}_{len(cases)}',record))
    cases.append(('block_boundary31',decision(31,4097,2,counter=16777217)))
    source=[ROOT/'scripts/java/OriginalExtendedStoreProbe.java',ROOT/'scripts/java/OriginalStorageCodecProbe.java']
    jdk=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
    subprocess.run([str(jdk/'javac.exe'),'-d',str(classes),*map(str,source)],check=True,capture_output=True,text=True)
    inputs=folder/'inputs.tsv'
    inputs.write_text('\n'.join('\t'.join(map(str,[name,r['format_id'],r['bucket_or_vector_count'],r['action_count'],len(r['locks']),base64.b64encode(codec.encode_payload(r)).decode()])) for name,r in cases),encoding='ascii')
    process=subprocess.run([str(jdk/'java.exe'),'-cp',str(classes),'OriginalStorageCodecProbe',r'D:\Program Files\HRC\plugins',str(inputs)],check=True,capture_output=True,text=True)
    (folder/'original.jsonl').write_text(process.stdout,encoding='utf-8')
    actual={row['id']:row for row in map(json.loads,process.stdout.splitlines()) if row.get('kind')=='case'}
    checks=[]
    for name,record in cases:
        original=actual[name];fmt=record['format_id'];h=record['bucket_or_vector_count'];k=record['action_count']
        expected=codec.decode_payload(0,fmt,h,len(record['locks']),codec.encode_payload(record),k)
        loaded=list(expected['raw']);checks.append({'id':name+'.raw','passed':loaded==original['loaded_raw']})
        checks.append({'id':name+'.clock','passed':math.floor(loaded[0]+.5)==original['updates']})
        checks.append({'id':name+'.locks','passed':codec.runtime_locks(expected)==original['runtime_locks']})
        if fmt!=25:expected['raw'][0]=math.floor(loaded[0]+.5)
        expected['locks']={}
        serialized=codec.encode_payload(expected)
        checks.append({'id':name+'.serialize','passed':serialized==base64.b64decode(original['serialized_base64'])})
    report={'passed':all(row['passed'] for row in checks),'cases':len(cases),'checks':len(checks),'results':checks,
            'source_hashes':{str(p.relative_to(ROOT)):sha(p) for p in [*source,ROOT/'preflop_lab/hrc_hrcz_storage.py']},
            'input_sha256':sha(inputs),'original_output_sha256':sha(folder/'original.jsonl'),
            'loaded_classes':[row for row in map(json.loads,process.stdout.splitlines()) if row.get('kind')=='class'],
            'scope':{'original_mx_float_load_save':True,'original_my_setter_replay':True,'pY_gui_or_full_archive_loader_executed':False,
                     'native_solver_or_gui_started':False,'fresh_rng_on_import':True,'terminal_vectors_are_absolute_not_sample_counters':True}}
    destination=ROOT/'reports/hrc-original-hrcz-storage-validation.json';destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'cases':report['cases'],'checks':report['checks'],'failed':[r for r in checks if not r['passed']],'report':str(destination)}))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
