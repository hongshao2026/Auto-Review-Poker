"""Run the original installed 64-bucket flop reader against independent schema cases."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
JDK=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
PLUGINS=Path(r'D:\Program Files\HRC\plugins')
MAIN=PLUGINS/'net.holdemresources.calculator_4.1.0.202603231401.jar'
DATA=PLUGINS/'net.holdemresources.postflopabstractions.holdem_1.0.0.jar'
EC=PLUGINS/'org.eclipse.collections_11.1.0.v20220705-1455.jar'
BROTLI=PLUGINS/'net.holdemresources.calculator.mavendependencies_0.2.0/org.brotli/dec-0.1.2.jar'
CASES=ROOT/'analysis/hrc-deep/equity/flop64-probe-cases.tsv'
SOURCE=ROOT/'scripts/java/OriginalFlopBucketProbe.java'
OUT=ROOT/'analysis/hrc-deep/probes'
CLASSES=ROOT/'analysis/hrc-deep/java-tools'
OUT.mkdir(parents=True,exist_ok=True)
CLASSES.mkdir(parents=True,exist_ok=True)
if not CASES.exists():
    subprocess.run([sys.executable,str(ROOT/'scripts/validate-hrc-abstraction-resource.py')],check=True)
subprocess.run([str(JDK/'javac.exe'),'-cp',str(BROTLI),'-d',str(CLASSES),str(SOURCE)],check=True,capture_output=True)
command=[str(JDK/'java.exe'),'-Xmx1g','-cp',str(CLASSES)+';'+str(BROTLI),'OriginalFlopBucketProbe',str(MAIN),str(DATA),str(EC),str(CASES)]
run=subprocess.run(command,capture_output=True,text=True)
(OUT/'abstraction-original-output.txt').write_text(run.stdout,encoding='utf-8')
(OUT/'abstraction-stderr.txt').write_text(run.stderr,encoding='utf-8')
result={'command':command,'returncode':run.returncode,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'cases_sha256':hashlib.sha256(CASES.read_bytes()).hexdigest(),'scope':'One installed Johanson13_2021-02 64-bucket flop profile only; unmodified original oh/ol/lo/... classes with installed Eclipse Collections and Brotli dependencies. No profile registry or application startup invoked.','stdout':run.stdout,'stderr':run.stderr,'passed':False}
if run.returncode==0:
    summary=json.loads(run.stdout.splitlines()[-1])
    result.update(summary)
    result['passed']=summary.get('all_passed') is True and summary.get('original_reader_cases')==1152 and summary.get('exhaustive_legal_board_hole_cases')==25989600
(ROOT/'reports/hrc-original-abstraction-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('command','stdout','stderr','scope')},indent=2))
if not result['passed']:
    print(run.stderr)
    raise SystemExit(1)
