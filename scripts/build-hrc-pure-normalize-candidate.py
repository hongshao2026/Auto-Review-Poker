"""Skip two divisions only for finite positive totals with a zero action."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/throughput-round3-20261108/recursion-review/normalize23'
OUT=BASE.parent.parent/'pure-normalize-candidate'


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    for path in BASE.glob('hrc_*.hpp'):shutil.copy2(path,OUT/path.name)
    cpp=(BASE/'hrc_research_solver.cpp').read_text(encoding='utf-8')
    anchor='        if(total>0){p[0]/=total;p[1]/=total;}else{p[0]=.5;p[1]=.5;}return;'
    new=('        if(total>0){if(std::isfinite(total)){\n'
         '            if(p[0]==0){p[1]=1;return;}if(p[1]==0){p[0]=1;return;}}\n'
         '            p[0]/=total;p[1]/=total;}else{p[0]=.5;p[1]=.5;}return;')
    assert cpp.count(anchor)==1;cpp=cpp.replace(anchor,new,1)
    (OUT/'hrc_research_solver.cpp').write_text(cpp,encoding='utf-8')
    zig=Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')
    flags=['-O3','-std=c++17','-ffp-contract=off']
    exe=OUT/'hrc_research_solver-pure-normalize.exe'
    subprocess.run([str(zig),'c++',*flags,str(OUT/'hrc_research_solver.cpp'),'-o',str(exe)],check=True,capture_output=True,text=True)
    template=(BASE.parent/'probe-template.cpp').read_text(encoding='utf-8')
    source=OUT/'probe.cpp';source.write_text(template.replace('SOURCE/hrc_research_solver.cpp','hrc_research_solver.cpp'),encoding='utf-8')
    subprocess.run([str(zig),'c++',*flags,str(source),'-o',str(OUT/'probe.exe')],check=True,capture_output=True,text=True)
    out=OUT/'state.bin';row=subprocess.run([str(OUT/'probe.exe'),str(out)],check=True,capture_output=True,text=True)
    reference=BASE.parent/'baseline-state.bin';data=out.read_bytes()
    result={'full_state_equal':data==reference.read_bytes(),'output_bytes':len(data),
            'sha256':hashlib.sha256(data).hexdigest(),'fixture':json.loads(row.stdout),'production_modified':False}
    (OUT/'validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    assert result['full_state_equal'];print(json.dumps(result),flush=True)


if __name__=='__main__':main()
