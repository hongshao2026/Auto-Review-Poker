"""Original mq replay with explicit rebasing of fixture wall-clock fields.

Original formulas/methods are unmodified. Rebasing private timestamps permits
testing hours of history retention without waiting hours. Millisecond jitter is
recorded; CI values are compared separately from non-deterministic wall time.
"""
import hashlib
import json
import math
from pathlib import Path
import runpy
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    h=runpy.run_path(str(ROOT/'tests/test_hrc_ci.py'))
    cases=h['ci_fixtures']();lines=[h['ci_line'](c) for c in cases]
    out=ROOT/'analysis/hrc-deep/probes';inputs=out/'ci-inputs.tsv';inputs.write_text('\n'.join(lines)+'\n')
    java=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
    jar=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')
    rng=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator.mavendependencies_0.2.0\org.apache.commons\commons-rng-client-api-1.6.jar')
    source=ROOT/'scripts/java/OriginalPolicyProbe.java';classes=ROOT/'analysis/hrc-deep/java-policy'
    subprocess.run([str(java.with_name('javac.exe')),'-d',str(classes),str(source)],check=True)
    command=[str(java),'-cp',str(classes),'OriginalPolicyProbe',str(jar),str(rng),str(inputs)]
    proc=subprocess.run(command,capture_output=True,text=True)
    (out/'ci-original-output.jsonl').write_text(proc.stdout)
    if proc.returncode:raise RuntimeError(proc.stderr)
    records=[json.loads(line) for line in proc.stdout.splitlines()];original=[r for r in records if 'id' in r]
    native=h['HELPERS']['run_lines'](lines);reference=[h['expected'](c) for c in cases]
    (out/'ci-independent-output.jsonl').write_text('\n'.join(map(json.dumps,native))+'\n')
    results=[];max_error=0.;max_ms=0;max_speed=0.
    for o,n,p in zip(original,native,reference):
        h['HELPERS']['close'](n,p)
        for index,(a,b) in enumerate(zip(o['snapshots'],n['snapshots'])):
            error=abs(a['ci']-b['ci']) if math.isfinite(a['ci']) else 0
            timestamps=[abs(a['last_time']-b['last_time'])]
            passed=a['accepted']==b['accepted'] and len(a['history'])==len(b['history']) and error<1e-9
            passed &= max(abs(x-y) for x,y in zip(a['progress'],b['progress']))<1e-12
            for ah,bh in zip(a['history'],b['history']):
                passed &= ah[0]==bh[0] and ah[2]==bh[2] and abs(ah[3]-bh[3])<1e-9
                timestamps.append(abs(ah[1]-bh[1]))
            # Each original method independently reads System.currentTimeMillis.
            # 20 ms tolerance is reported, not hidden in numeric CI accuracy.
            speed_error=abs(a['speed']-b['speed'])
            passed &= max(timestamps)<=20 and speed_error<=max(1e-9,abs(b['speed'])*.002)
            max_error=max(max_error,error);max_ms=max(max_ms,max(timestamps));max_speed=max(max_speed,speed_error)
            results.append({'id':o['id'],'step':index,'passed':bool(passed),'ci_error':error,'timestamp_jitter_ms':max(timestamps),'speed_error':speed_error,'history_length':len(a['history'])})
    report={'passed':all(r['passed'] for r in results),'snapshots':len(results),'max_ci_error':max_error,'max_timestamp_jitter_ms':max_ms,'max_samples_per_second_error':max_speed,
            'command':command,'jar_sha256':hashlib.sha256(jar.read_bytes()).hexdigest(),'header_sha256':hashlib.sha256((ROOT/'native/hrc_ci.hpp').read_bytes()).hexdigest(),
            'probe_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'class_hashes':[r for r in records if r.get('kind')=='class'],'cases':results,
            'scope':'Unmodified original mq/mr/ms and mf/mE snapshots; synthetic 1/2/4-node graphs, no worker/application. Fixture rebases original timestamp fields before each poll to simulate hours of elapsed time; stored counts/policies and original methods are not modified. CI/history formulas verified; actual clock jitter retained separately. Restarts create new original mq objects.'}
    (ROOT/'reports/hrc-original-ci-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','class_hashes','command')},indent=2))
    if not report['passed']:
        print([r for r in results if not r['passed']][:5]);raise SystemExit(1)


if __name__=='__main__':main()
