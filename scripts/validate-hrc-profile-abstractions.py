"""Offline original-reader crosscheck of the three exact local data profiles.

This validation is separate from training. It loads only the previously audited
oh/ol/lo/... reader allowlist and Eclipse Collections, never a solver or strategy.
"""
from pathlib import Path
import array
import hashlib
import itertools
import json
import random
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_abstraction import combo_index,permute_mask,file_sha256

CACHE=ROOT/'.research-cache/abstractions'
OUT=ROOT/'analysis/hrc-desktop'
PLUGINS=Path(r'D:\Program Files\HRC\plugins')
JDK=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
MAIN=PLUGINS/'net.holdemresources.calculator_4.1.0.202603231401.jar'
EC=PLUGINS/'org.eclipse.collections_11.1.0.v20220705-1455.jar'
BROTLI=PLUGINS/'net.holdemresources.calculator.mavendependencies_0.2.0/org.brotli/dec-0.1.2.jar'
manifest=json.loads((CACHE/'manifest.json').read_text())
rng=random.Random(98174)
cases=[]
for profile in manifest['profiles']:
    street=profile['street'];boards=array.array('Q');values=array.array('H')
    with (CACHE/profile['boards_file']).open('rb') as f:boards.fromfile(f,profile['rows'])
    with (CACHE/profile['values_file']).open('rb') as f:values.fromfile(f,profile['rows']*profile['hole_columns'])
    for _ in range(75):
        row=rng.randrange(len(boards));board=boards[row]
        legal=[(l,h) for h in range(1,52) for l in range(h) if not board&((1<<h)|(1<<l))]
        col=rng.randrange(len(legal));lo,hi=legal[col];bucket=values[row*len(legal)+col]
        for permutation in itertools.permutations(range(4)):
            new_board=permute_mask(board,permutation)
            a=4*(lo//4)+permutation[lo%4];b=4*(hi//4)+permutation[hi%4]
            cases.append((street,new_board,combo_index(a,b),bucket))
    del values
casefile=OUT/'exact-profile-bucket-cases.tsv'
casefile.write_text(''.join('\t'.join(map(str,c))+'\n' for c in cases),encoding='utf-8')
classes=OUT/'exact-profile-probe-classes';classes.mkdir(exist_ok=True)
sources=[ROOT/'scripts/java/OriginalFlopBucketProbe.java',ROOT/'scripts/java/OriginalProfileBucketProbe.java']
subprocess.run([str(JDK/'javac.exe'),'-cp',str(BROTLI),'-d',str(classes),*map(str,sources)],check=True,capture_output=True)
command=[str(JDK/'java.exe'),'-Xmx2g','-cp',str(classes)+';'+str(BROTLI),'OriginalProfileBucketProbe',str(MAIN),str(EC),str(CACHE),str(casefile)]
run=subprocess.run(command,capture_output=True,text=True,errors='replace')
records=[]
for line in run.stdout.splitlines():
    if line.startswith('{'):records.append(json.loads(line))
report={'scope':'Offline original abstraction reader only; no original solver, strategy, sampler or application initialization. Training independently uses preprocessed data.',
        'source_sha256':{p.name:file_sha256(p) for p in sources},'main_jar_sha256':file_sha256(MAIN),
        'casefile_sha256':file_sha256(casefile),'case_count':len(cases),'sample_design':'75 canonical-board/hole pairs per street, all24suit permutations; same seed/sequence as independent native unit test',
        'profiles':manifest['profiles'],'command':command,'returncode':run.returncode,'records':records,'stderr':run.stderr,
        'passed':run.returncode==0 and records and records[-1].get('all_passed') is True and records[-1].get('cases')==5400}
(OUT/'exact-profile-original-reader-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k in ('case_count','records','returncode','stderr','passed')},indent=2))
if not report['passed']:raise SystemExit(1)
