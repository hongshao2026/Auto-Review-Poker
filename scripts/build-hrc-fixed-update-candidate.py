"""Specialize the two default storage layouts for two/three actions."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/throughput-round3-20261108/baseline'
OUT=BASE.parent/'fixed-update-candidate'
BODY=r'''
    template<int K,int F> void update_fixed(Random& rng,int h,const double* p,const double* q,double w,double z){
        double value=0;for(int a=0;a<K;++a)if(p[a]>0)value+=p[a]*q[a];
        ++updates;++visits[h];
        double t=raw[0]+1;
        if constexpr(F==23){int d=refresh_divisor(t);if(rng.integer()%d==0){t=double(updates);raw[0]=t;}}
        else raw[0]=t;
        size_t r=F==23?1+size_t(2*K+1)*h:1+size_t(h+1)*K;
        for(int a=0;a<K;++a)raw[r+a]+=t*w*(q[a]-value);
        if constexpr(F==23){size_t av=r+K+1;for(int a=0;a<K;++a)raw[av+a]+=t*p[a];raw[r+K]+=t*w;}
        else if(z>0){for(int a=0;a<K;++a)raw[1+a]+=t*z*p[a];}
    }
'''


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    for path in BASE.glob('hrc_*.hpp'):shutil.copy2(path,OUT/path.name)
    cpp=(BASE/'hrc_research_solver.cpp').read_text(encoding='utf-8')
    marker='    void update(Random& rng,int h,const double* p,const double* q,double w,double z){'
    assert cpp.count(marker)==1;cpp=cpp.replace(marker,BODY+'\n'+marker,1)
    marker='        double value=0;for(int a=0;a<k;++a)if(p[a]>0)value+=p[a]*q[a];'
    fast=('        if(k==2){if(base_format()==23){update_fixed<2,23>(rng,h,p,q,w,z);return;}\n'
          '            if(base_format()==25){update_fixed<2,25>(rng,h,p,q,w,z);return;}}\n'
          '        else if(k==3){if(base_format()==23){update_fixed<3,23>(rng,h,p,q,w,z);return;}\n'
          '            if(base_format()==25){update_fixed<3,25>(rng,h,p,q,w,z);return;}}\n')
    assert cpp.count(marker)==1;cpp=cpp.replace(marker,fast+marker,1)
    (OUT/'hrc_research_solver.cpp').write_text(cpp,encoding='utf-8')
    compiler=Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')
    flags=['-O3','-std=c++17','-ffp-contract=off']
    exe=OUT/'hrc_research_solver-fixed-update.exe'
    subprocess.run([str(compiler),'c++',*flags,str(OUT/'hrc_research_solver.cpp'),'-o',str(exe)],check=True,capture_output=True,text=True)
    template=(BASE.parent/'recursion-review/probe-template.cpp').read_text(encoding='utf-8')
    probe=OUT/'probe.cpp';probe.write_text(template.replace('SOURCE/hrc_research_solver.cpp','hrc_research_solver.cpp'),encoding='utf-8')
    subprocess.run([str(compiler),'c++',*flags,str(probe),'-o',str(OUT/'probe.exe')],check=True,capture_output=True,text=True)
    data=OUT/'state.bin';result=subprocess.run([str(OUT/'probe.exe'),str(data)],check=True,capture_output=True,text=True,timeout=30)
    reference=BASE.parent/'recursion-review/baseline-state.bin'
    raw=data.read_bytes();equal=raw==reference.read_bytes()
    report={'status':'passed' if equal else 'failed','full_state_equal':equal,'output_bytes':len(raw),
            'sha256':hashlib.sha256(raw).hexdigest(),'fixture':json.loads(result.stdout),'production_modified':False,
            'executable':str(exe),'executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}
    (OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if not equal:raise RuntimeError('Fixed-action update changed sequential state')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
