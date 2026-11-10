"""Build and self-test the explicitly scoped original-CI observation agent."""
from pathlib import Path
import argparse,hashlib,json,subprocess,zipfile

ROOT=Path(__file__).resolve().parents[1]
JAVA=Path('D:/Tools/REA-Research/jdk-21.0.13+9/bin')
ASM=Path('D:/Tools/REA-Research/ghidra_12.1.4_PUBLIC/Ghidra/Framework/Emulation/lib/asm-9.7.1.jar')
TARGET=Path('D:/Program Files/HRC/plugins/net.holdemresources.calculator_4.1.0.202603231401.jar')
p=argparse.ArgumentParser();p.add_argument('--output',default='analysis/hrc-deep/ci-runtime-observer');args=p.parse_args()
OUT=(ROOT/args.output).resolve()
CLASSES=OUT/'classes'
CLASSES.mkdir(parents=True,exist_ok=True)
names=['HrcCiSink','HrcCiObservationAgent','HrcCiAttach','HrcCiObservationSelfTest']
subprocess.run([str(JAVA/'javac.exe'),'-cp',str(ASM),'-d',str(CLASSES),*[str(ROOT/'scripts/java'/f'{name}.java') for name in names]],check=True)
with zipfile.ZipFile(TARGET) as z:
    original_sha=hashlib.sha256(z.read('net/holdemresources/internal/mr.class')).hexdigest()
sink=OUT/'ci-sink.jar';agent=OUT/'ci-observation-agent.jar'
with zipfile.ZipFile(sink,'w') as z:z.write(CLASSES/'rea/hrcbench/HrcCiSink.class','rea/hrcbench/HrcCiSink.class')
with zipfile.ZipFile(agent,'w') as z:
    z.writestr('META-INF/MANIFEST.MF','Manifest-Version: 1.0\nAgent-Class: HrcCiObservationAgent\nPremain-Class: HrcCiObservationAgent\nCan-Retransform-Classes: true\n\n')
    for path in CLASSES.glob('HrcCiObservationAgent*.class'):z.write(path,path.name)
    with zipfile.ZipFile(ASM) as asm:
        for name in asm.namelist():
            if name.endswith('.class'):z.writestr(name,asm.read(name))
test=OUT/'selftest'
assert not (test/'original-ci.jsonl').exists(), 'Preserve prior selftest; choose a new build directory for rerun'
options=f'start|{test}|{sink}|{original_sha}'
r=subprocess.run([str(JAVA/'java.exe'),f'-javaagent:{agent}={options}','-cp',str(CLASSES),'HrcCiObservationSelfTest',str(TARGET)],check=True,capture_output=True,text=True)
(OUT/'selftest-stdout.txt').write_text(r.stdout,encoding='utf8')
(OUT/'selftest-stderr.txt').write_text(r.stderr,encoding='utf8')
row=json.loads((test/'original-ci.jsonl').read_text())
assert row['index']==2 and row['original_epoch_millis']==123456789 and row['original_samples']==10000250 and row['ci']==9.125
assert set(r.stdout.splitlines())=={'a:int=2','a:long=123456789','b:long=10000250','a:double=9.125'}
manifest={'target_class':'net.holdemresources.internal.mr','constructor':'(IJJD)V','original_class_sha256':original_sha,
          'agent_sha256':hashlib.sha256(agent.read_bytes()).hexdigest(),'sink_sha256':hashlib.sha256(sink.read_bytes()).hexdigest(),
          'asm_sha256':hashlib.sha256(ASM.read_bytes()).hexdigest(),'selftest':'passed; original fields unchanged, observation arguments exact, owner-based removal returned true, second constructor call after removal produced no log',
          'agent':str(agent),'sink':str(sink),'classes':str(CLASSES),
          'sources':{name:hashlib.sha256((ROOT/'scripts/java'/f'{name}.java').read_bytes()).hexdigest() for name in names}}
(OUT/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
print(json.dumps(manifest,indent=2))
