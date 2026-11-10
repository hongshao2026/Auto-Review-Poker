"""Original reach/lw/lu/mf bytes vs actual independent scope step.

The original mn scheduling loop is reconstructed explicitly from its audited
dispatch; no application job/GUI/controller or original mn class is loaded.
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis/hrc-deep/sampling-scope'
JDK=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
ZIG=Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
JAR=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')
RNG=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator.mavendependencies_0.2.0\org.apache.commons')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    descriptor=OUT/'scope.bin';descriptor.write_bytes(b'HRSCOPE1'+struct.pack('<II',1,1))
    sources=[ROOT/'scripts/java'/name for name in ('OriginalTraversalProbe.java','OriginalNestedTraversalProbe.java','OriginalChanceProbe.java','OriginalSamplingScopeProbe.java')]
    native=ROOT/'scripts/native/scope_probe.cpp';exe=OUT/'scope-probe.exe'
    commands=[[str(JDK/'javac.exe'),'-d',str(OUT),*map(str,sources)],
              [str(ZIG),'c++','-O2','-std=c++17','-ffp-contract=off',str(native),'-o',str(exe)],
              [str(JDK/'java.exe'),'-cp',str(OUT),'OriginalSamplingScopeProbe',str(JAR),str(RNG)],
              [str(exe),str(descriptor)]]
    outputs=[]
    for i,command in enumerate(commands):
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (OUT/f'{i}-stdout.jsonl').write_text(result.stdout,encoding='utf-8');(OUT/f'{i}-stderr.txt').write_text(result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError(f'Command {i}: {result.stderr[-5000:]}')
        outputs.append(result.stdout)
    records=[json.loads(s) for s in outputs[2].splitlines()];original=[r for r in records if r.get('kind')=='result']
    independent=[json.loads(s) for s in outputs[3].splitlines()]
    assert len(original)==len(independent)==128
    failures=[];numeric=0;max_error=0.
    for o,n in zip(original,independent):
        key={k:o[k] for k in ('variant','version','seed','step')}
        for field in ('mode','samples','deals','combos','board','rng_calls'):
            if o[field]!=n[field]:failures.append({**key,'field':field,'original':o[field],'independent':n[field]})
        for a,b in zip(o['nodes'],n['nodes']):
            numeric+=len(a['raw']);error=max(abs(x-y) for x,y in zip(a['raw'],b['raw']));max_error=max(max_error,error)
            if a!=b:failures.append({**key,'node':a['id'],'raw_error':error,'updates':[a['updates'],b['updates']]})
    report={'passed':not failures,'snapshots':len(original),'numeric_values':numeric,'max_numeric_error':max_error,
            'scope':'Actual independent SamplingScope + Engine.step vs original lU/lR/mf reach extraction, lw/lu dealing, lX/lY scalar/vector recursion and mE store. Original mn dispatcher is explicitly assembled from audited sequence; original mn/application/GUI not executed. Synthetic constant terminal payoffs; scripted shared xoshiro RNG, not original RNG seeding equivalence.',
            'modes':[1,2],'versions':[3,4],'prefix_policy':'nonuniform frozen display including zero own reach AA',
            'class_hashes':[r for r in records if r.get('kind')=='class'],
            'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [*sources,native,ROOT/'native/hrc_scope.hpp',ROOT/'native/hrc_research_solver.cpp',ROOT/'native/hrc_parallel.hpp',ROOT/'native/hrc_chance.hpp']},
            'original_jar_sha256':sha(JAR),'native_executable_sha256':sha(exe),'commands':commands,'failures':failures[:20]}
    target=ROOT/'reports/hrc-original-native-scope-validation.json';target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','snapshots','numeric_values','max_numeric_error','failures')},indent=2))
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
