"""Isolated serial integer-bound census; no production-source mutation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    folder=ROOT/'.research-cache/throughput-round2-20261108/rng-census'
    folder.mkdir(exist_ok=False)
    frozen=folder.parent/'baseline'
    text=(frozen/'hrc_research_solver.cpp').read_text(encoding='utf-8')
    old='uint32_t bound(uint32_t n) {++bounded_calls;'
    assert text.count(old)==1
    text=text.replace(old,'uint64_t bound_histogram[64]{};\n    '+old+'++bound_histogram[std::min(n,uint32_t(63))];')
    old='if(!checkpoint_current)e.save(output);double elapsed='
    assert text.count(old)==1
    text=text.replace(old,'std::cerr<<"{\\\"bounds\\\":[";for(int i=0;i<64;++i){if(i)std::cerr<<\',\';std::cerr<<e.rng.bound_histogram[i];}std::cerr<<"],\\\"integer_calls\\\":"<<e.rng.int_calls<<",\\\"unit_calls\\\":"<<e.rng.double_calls<<"}"<<std::endl;\n    '+old)
    cpp=folder/'census.cpp';cpp.write_text(text,encoding='utf-8')
    compiler=json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text())['compiler']
    exe=folder/'census.exe'
    subprocess.run([compiler,'c++','-O3','-std=c++17','-ffp-contract=off','-I',str(frozen),str(cpp),'-o',str(exe)],check=True,capture_output=True,text=True)
    spec=importlib.util.spec_from_file_location('census_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    scene=ROOT/'.research-cache/three40bb-ci10-independent-20261107'
    plan=json.loads((scene/'plan.json').read_text(encoding='utf-8'))
    plan.update(output=str(folder),formal_total_sample_cap=10_500_000,formal_target_ci=-1,formal_track_ci=False,training_threads=1,hard_seconds_per_phase=60)
    plan.pop('maximum_additional_samples',None);plan['build']['executable_path']=str(exe)
    result=monitor.run_phase(plan,'serial',resume=scene/'initialization/checkpoint.bin')
    data=json.loads((folder/'serial/stderr.log').read_text(encoding='utf-8'))
    data.update(samples=500_000,terminal_calls=result['summary']['terminal_calls'],
                limits='One serial trace from own 10m checkpoint; counters perturb code layout, not a time profile.')
    (ROOT/'reports/hrc-rng-census-20261108.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(json.dumps({'bounds':{n:c for n,c in enumerate(data['bounds']) if c},'integer_calls':data['integer_calls'],'unit_calls':data['unit_calls']}))


if __name__=='__main__':main()
