"""Matched 20-worker mature EP subtree throughput, with immutable inputs."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_native import build


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',required=True)
    args=parser.parse_args()
    case=ROOT/'.research-cache/hand-bubble-20261108'
    output=ROOT/'.research-cache/monetary-table-benchmark-20261109'
    output.mkdir(exist_ok=False)
    baseline=ROOT/'.research-cache/cpu-round4-20261108/accepted/solver.exe'
    candidate=build()
    source=case/'formal/checkpoint.bin'
    before=json.loads((case/'formal/index.json').read_text())['samples']
    spec=importlib.util.spec_from_file_location('monetary_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    original_command=monitor.phase_command
    def command(plan,name,**kwargs):
        values=original_command(plan,name,**kwargs)
        values[15]='0';values[16]=str(case/'sampling-scope.bin');values[18]='0'
        return values+[str(int(name.startswith('new'))),'1','1','1']
    monitor.phase_command=command
    report=dict(status='running',purpose='Fixed-work throughput; not time-to-CI10 or a new HRC benchmark',
        source_checkpoint=str(source),source_sha256_before=sha(source),
        input_binary_sha256=sha(case/'input/tree.bin'),scope_path=[0],threads=20,
        additional_samples=5_000_000,ci_enabled=False,
        executables={key:dict(path=str(path),sha256=sha(path)) for key,path in [('old',baseline),('new',candidate)]},
        order=['old-a','new-a','new-b','old-b'],phases={})
    destination=ROOT/'reports/hrc-monetary-table-benchmark-20261109.json'
    def save():
        monitor.dump(output/'report.json',report);monitor.dump(destination,report)
    save()
    try:
        for name in report['order']:
            plan=dict(output=str(output),tree_binary=str(case/'input/tree.bin'),
                resources_dir=str(ROOT/'.research-cache/abstractions'),seed=43,
                build=dict(executable_path=str(candidate if name.startswith('new') else baseline)),
                mode='v4',formal_track_ci=False,formal_target_ci=-1,
                formal_total_sample_cap=before+5_000_000,maximum_additional_samples=5_000_000,
                hard_seconds_per_phase=900,memory_budget_bytes=8<<30,training_threads=20)
            with (output/(name+'.runner.log')).open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
                phase=monitor.run_phase(plan,name,resume=source)
            s=phase['summary']
            assert s['iteration']==before+5_000_000 and s['stop_reason']=='sample_target'
            assert s['sampling_scope']=='selected_subtree' and s['sampling_root_node_id']==1
            assert s['terminal_tables']==name.startswith('new')
            report['phases'][name]=phase;save()
            print(json.dumps(dict(phase=name,wall_seconds=phase['wall_seconds'],training_seconds=s['elapsed_seconds'],
                table_setup_seconds=s['terminal_table_setup_seconds'],table_bytes=s['terminal_table_bytes'],
                peak_gib=phase['peak_working_set_bytes']/2**30)),flush=True)
        report['source_checkpoint_unchanged']=sha(source)==report['source_sha256_before']
        assert report['source_checkpoint_unchanged']
        mean={label:statistics.mean(p['wall_seconds']for name,p in report['phases'].items()if name.startswith(label))for label in ('old','new')}
        report.update(status='completed',mean_wall_seconds=mean,speedup_including_setup_and_saves=mean['old']/mean['new'])
        save()
        print(json.dumps({k:report[k]for k in ('status','mean_wall_seconds','speedup_including_setup_and_saves')}),flush=True)
    except Exception as error:
        report.update(status='incomplete',error=str(error));save();raise


if __name__=='__main__':main()
