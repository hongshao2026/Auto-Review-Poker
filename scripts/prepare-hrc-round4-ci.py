"""Prepare an isolated allocation-free CI snapshot candidate; no native build."""
from pathlib import Path
import difflib
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.research-cache/cpu-round4-20261108/ci'
OUT.mkdir(exist_ok=False)
dest=OUT/'native';dest.mkdir()
for path in (ROOT/'native').glob('*'):
    if path.is_file():shutil.copy2(path,dest/path.name)
path=dest/'hrc_research_solver.cpp'
original=path.read_text(encoding='utf-8');source=original
assert hashlib.sha256(path.read_bytes()).hexdigest()=='641453406f885c8a851697eaa27f69636aa8336d41a2091a3f1ffca9a9bdc0b7'
needle='    void flush(){if(frequency)frequency->flush();'
method='''    // Same display normalization, writing into the caller's existing policy
    // row. Avoid one heap allocation per bucket during full-tree CI snapshots.
    void display_into(int h,double* out)const{
        if(frequency){const auto p=frequency->display(h);std::copy(p.begin(),p.end(),out);return;}
        const double* base=raw.data()+(base_format()!=25?average(h):regret(h));
        if(locks&&locks->active()){locks->compose_into(base,h,false,out);return;}
        double sum=0;for(int a=0;a<k;++a)sum+=(out[a]=std::max(0.0,base[a]));
        if(sum>0)for(int a=0;a<k;++a)out[a]/=sum;
        else std::fill(out,out+k,1.0/k);
    }
'''
assert source.count(needle)==1
source=source.replace(needle,method+needle)
old='s.policy.reserve(size_t(n.buckets)*n.k);for(int b=0;b<n.buckets;++b){auto p=n.display(b);s.policy.insert(s.policy.end(),p.begin(),p.end());}'
new='s.policy.resize(size_t(n.buckets)*n.k);for(int b=0;b<n.buckets;++b)n.display_into(b,s.policy.data()+size_t(b)*n.k);'
assert source.count(old)==1;source=source.replace(old,new)
path.write_text(source,encoding='utf-8')
(OUT/'candidate.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),source.splitlines(True))),encoding='utf-8')
(OUT/'manifest.json').write_text(json.dumps({'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
    'baseline_cpp_sha256':'641453406f885c8a851697eaa27f69636aa8336d41a2091a3f1ffca9a9bdc0b7',
    'changes':['Write normalized policies directly into final snapshot rows; same arithmetic and fallback semantics'],
    'status':'prepared_not_built'},indent=2)+'\n',encoding='utf-8')
print(str(OUT))
