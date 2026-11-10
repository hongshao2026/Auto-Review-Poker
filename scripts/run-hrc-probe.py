"""Compile a reviewed probe, retain raw output, and reject any missing or failed check."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
JDK=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
JAR=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')
RNG=JAR.parent/'net.holdemresources.calculator.mavendependencies_0.2.0/org.apache.commons/commons-rng-client-api-1.6.jar'
CHOICES={
    'strategy':('OriginalStrategyProbe',[str(JAR),str(RNG)],('numeric_check',),30),
    'tree':('OriginalTreeProbe',[str(JAR)],('tree_case',),8),
    'traversal':('OriginalTraversalProbe',[str(JAR),str(RNG)],('numeric_check','invariant_check'),52),
    'settlement':('OriginalSettlementProbe',[str(JAR)],('settlement_case',),7),
}
parser=argparse.ArgumentParser()
parser.add_argument('probe',choices=CHOICES)
args=parser.parse_args()
name,arguments,kind,count=CHOICES[args.probe]
source=ROOT/f'scripts/java/{name}.java'
classes=ROOT/'analysis/hrc-deep/java-tools'
classes.mkdir(parents=True,exist_ok=True)
sources=[source]
if args.probe=='settlement': sources.append(ROOT/'scripts/java/OriginalTreeProbe.java')
subprocess.run([str(JDK/'javac.exe'),'-d',str(classes),*map(str,sources)],check=True,capture_output=True)
command=[str(JDK/'java.exe'),'-cp',str(classes),name,*arguments]
run=subprocess.run(command,capture_output=True,text=True)
out=ROOT/'analysis/hrc-deep/probes'
out.mkdir(parents=True,exist_ok=True)
(out/f'{args.probe}-original-output.jsonl').write_text(run.stdout,encoding='utf-8')
(out/f'{args.probe}-stderr.txt').write_text(run.stderr,encoding='utf-8')
records=[json.loads(s) for s in run.stdout.splitlines()]
checks=[r for r in records if r.get('kind') in kind]
passed=run.returncode==0 and len(checks)==count and all(r.get('pass') is True for r in checks)
result={'probe':name,'command':command,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'jar_sha256':hashlib.sha256(JAR.read_bytes()).hexdigest(),'returncode':run.returncode,'expected_checks':count,'checks':len(checks),'passed':passed,'stderr':run.stderr,'records':records}
(ROOT/f'reports/hrc-original-{args.probe}-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({k:result[k] for k in ('probe','returncode','expected_checks','checks','passed')},indent=2))
if not passed:
    print(run.stderr)
    print(json.dumps([r for r in checks if not r['pass']],indent=2))
    raise SystemExit(1)
