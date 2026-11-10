"""Independent own-checkpoint CI acceptance for a frozen optimized executable."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scenario',choices=['three','nine'],required=True)
    p.add_argument('--exe',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=600)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    source=ROOT/('.research-cache/three40bb-ci10-independent-20261107' if args.scenario=='three'
                 else '.research-cache/nine40bb-ci10-independent-20261106')
    plan_file=source/'plan.json' if args.scenario=='three' else ROOT/'reports/hrc-nine40bb-ci10-independent-20261106.json'
    plan=json.loads(plan_file.read_text());initial=source/'initialization/checkpoint.bin';exe=args.exe.resolve()
    for key in ('phases','interruption','observed_bottlenecks','topology_fairness_audit'):plan.pop(key,None)
    reference=plan['build'];plan['build']={'executable_path':str(exe),'executable_sha256':sha(exe)}
    plan.update(output=str(out),training_threads=20,memory_budget_bytes=8<<30,formal_track_ci=True,
        formal_target_ci=10,formal_total_sample_cap=3_000_000_000,maximum_additional_samples=2_990_000_000,
        hard_seconds_per_phase=args.seconds)
    spec=importlib.util.spec_from_file_location('acceptance_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    result={'status':'running','scenario':args.scenario,'plan':plan,'reference_build':reference,
        'initial_checkpoint':str(initial),'initial_sha256_before':sha(initial),'executable_sha256':sha(exe),
        'limits':['Independent own initialization; no original policy is a training input.',
                  'CI is policy drift, not exploitability or an error bound.',
                  'A wall-bounded diagnostic is not a claim to have reached CI10.']}
    monitor.dump(out/'plan.json',plan);monitor.dump(out/'report.json',result)
    try:
        with (out/'runner.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
            result['formal']=monitor.run_phase(plan,'formal',resume=initial)
        result['status']='completed'
    except Exception as error:
        result.update(status='failed',error=str(error));raise
    finally:
        result['initial_unchanged']=sha(initial)==result['initial_sha256_before']
        monitor.dump(out/'report.json',result);monitor.dump(args.report,result)
    print(json.dumps({'status':result['status'],'scenario':args.scenario,'summary':result['formal']['summary']}),flush=True)

if __name__=='__main__':main()
