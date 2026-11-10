"""Make an isolated, reproducible choose-lock candidate from the frozen baseline."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.research-cache/throughput-round2-20261108/baseline'
OUT = BASE.parent / 'choose-lock-candidate'
old = '        if(node_mutexes){std::lock_guard<std::mutex> guard(node_mutexes[id]);n.strategy(h,p);return sample(n,p);}'
new = '''        if(node_mutexes){
            double exploration;int actions;
            {std::lock_guard<std::mutex> guard(node_mutexes[id]);n.strategy(h,p);exploration=n.exploration_probability();actions=n.k;}
            return sample_policy(actions,p,exploration);
        }'''
helper = '''    // Parallel path uses only a locked snapshot and this worker's private RNG.
    int sample_policy(int actions,const double* p,double exploration){
        if(rng.unit()<exploration)return int(rng.bound(actions));
        for(int a=0;a<actions;++a)if(p[a]>=1)return a;
        double u=rng.unit();for(int a=0;a<actions;++a){u-=p[a];if(u<=0)return a;}return 0;
    }
'''

def prepare():
    source = (BASE/'hrc_research_solver.cpp').read_text()
    assert source.count(old) == 1
    revised = source.replace(old,new).replace('    int sample(const Node& n,const double* p){',helper+'    int sample(const Node& n,const double* p){')
    OUT.mkdir(exist_ok=True)
    for path in BASE.glob('*.hpp'):
        target=OUT/path.name
        if target.exists() and target.read_bytes()!=path.read_bytes():
            raise RuntimeError(f'Refusing to replace changed candidate header {target}')
        target.write_bytes(path.read_bytes())
    target=OUT/'hrc_research_solver.cpp'
    if target.exists() and target.read_text()!=revised:
        raise RuntimeError('Refusing to replace changed candidate source')
    target.write_text(revised,encoding='utf-8',newline='\n')
    (OUT/'choose-lock.patch').write_text(''.join(difflib.unified_diff(source.splitlines(True),revised.splitlines(True),fromfile='a/native/hrc_research_solver.cpp',tofile='b/native/hrc_research_solver.cpp')),encoding='utf-8')
    manifest={'baseline_sha256':hashlib.sha256((BASE/'hrc_research_solver.cpp').read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'production_modified':False,'single_thread_path_changed':False}
    (OUT/'candidate.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest))

if __name__=='__main__':prepare()
