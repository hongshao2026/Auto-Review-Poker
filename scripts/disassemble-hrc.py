"""Disassemble every class without loading it; preserve exact case and JVM descriptors."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis/hrc-deep'
JAVAP=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\javap.exe')
source=json.loads((OUT/'source-index.json').read_text(encoding='utf-8'))
classes=sorted(source['sources'],key=lambda x:x['jar_ordinal'])
destination=OUT/'javap-all'
destination.mkdir(exist_ok=True)

def batch(items):
    name=f"{items[0]['jar_ordinal']:04d}-{items[-1]['jar_ordinal']:04d}.txt"
    command=[str(JAVAP),'-c','-p','-s','-sysinfo','-classpath',source['jar'],*[r['class'].replace('/','.') for r in items]]
    run=subprocess.run(command,capture_output=True)
    output=destination/name
    output.write_bytes(run.stdout)
    output.with_suffix('.stderr.txt').write_bytes(run.stderr)
    return {'path':str(output.relative_to(ROOT)), 'sha256':hashlib.sha256(run.stdout).hexdigest(), 'returncode':run.returncode, 'classes':[r['class'] for r in items], 'command':command, 'stderr':run.stderr.decode('utf-8',errors='replace')}

with ThreadPoolExecutor(max_workers=4) as pool:
    batches=list(pool.map(batch,[classes[i:i+60] for i in range(0,len(classes),60)]))
manifest={'jar':source['jar'],'jar_sha256':source['jar_sha256'],'class_count':len(classes),'batches':batches,'all_processes_succeeded':all(r['returncode']==0 for r in batches)}
(destination/'index.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps({'class_count':len(classes),'batches':len(batches),'all_processes_succeeded':manifest['all_processes_succeeded']}))
if not manifest['all_processes_succeeded']: raise SystemExit(1)
