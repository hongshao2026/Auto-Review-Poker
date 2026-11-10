"""Collect pre-optimization audit evidence and numeric probe equivalence.

After production optimization, --source-dir must point to the preserved native
snapshot matching these historical experiments. This does not benchmark the new
production kernel; use report-hrc-optimization.py for that.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,default=ROOT/'native')
    args=parser.parse_args()
    roots=[ROOT/'.research-cache/performance-audit-20261106',ROOT/'.research-cache/performance-audit-20261106-ranks']
    experiments=[json.loads((p/'report.json').read_text(encoding='utf-8')) for p in roots]
    if not all(e['all_checkpoints_identical'] for e in experiments):raise ValueError('Checkpoint difference')
    source=digest(args.source_dir/'hrc_research_solver.cpp')
    if any(e['source_sha256']!=source for e in experiments):raise ValueError('Source differs from historical experiment; pass the pre-optimization snapshot via --source-dir')
    binaries={name:Path(value['path']) for e in experiments for name,value in e['executables'].items()}
    reference=subprocess.check_output([str(binaries['baseline']),'--self-test'],text=True)
    expected=[json.loads(line) for line in reference.splitlines()]
    probes={}
    for name,path in binaries.items():
        output=subprocess.check_output([str(path),'--self-test'],text=True)
        probes[name]={'records':len(expected),'identical':expected==[json.loads(line) for line in output.splitlines()]}
    tables={s:(ROOT/f'.research-cache/abstractions/street{s}.buckets.u16').stat().st_size for s in (1,2,3)}
    result={'schema':'hrc-performance-review-v1','date':'2026-11-06','timezone':'Asia/Shanghai',
        'hardware':{'cpu':'Intel Core i5-13600KF','physical_cores':14,'logical_processors':20,'physical_memory_gib':31.84},
        'production_modified':False,'production_source_sha256':source,
        'experiments':experiments,'numeric_probes':probes,
        'execution':{'trainer':'local native C++ subprocess','training_threads':1,
            'baseline_peak_working_set_mib':{'chip':experiments[0]['results']['eight15bb_chip']['baseline']['median_peak_working_set_bytes']/1048576,
                'pko':experiments[0]['results']['eight15bb_pko']['baseline']['median_peak_working_set_bytes']/1048576}},
        'static_opportunities':[
            {'item':'8-bit turn/river bucket IDs','evidence':'native/hrc_cards.hpp:112-158',
             'current_table_bytes':tables,'potential_saved_bytes':sum(tables[s]//2 for s in (2,3)),
             'measured_speedup':None,'reason':'These two profiles have 256 buckets and IDs 0..255; files stay u16 and require a checked internal representation conversion.'},
            {'item':'Cache exploration probability and counter refresh divisor','evidence':'native/hrc_research_solver.cpp:97-107,270-273',
             'measured_speedup':None,'reason':'Use a cache keyed by the actual stored counter. Preserve random-call order, floor/sqrt arithmetic, reset/resume/CI flush invalidation.'},
            {'item':'Remove per-node small heap allocations for locks/frequency strategy','evidence':'native/hrc_policy.hpp:37-67,110-115',
             'measured_speedup':None,'reason':'At most 16 actions; caller-owned fixed buffers can replace temporary vectors without changing numeric operations. Applies to constrained nodes.'},
            {'item':'Parallel training','evidence':'native/hrc_research_solver.cpp:275-292,302; preflop_lab/server.py:170-190',
             'measured_speedup':None,'reason':'The mutable regret/average stores and RNG are serial. A parallel mode needs explicit synchronization, memory budgeting and separate convergence/strategy validation.'}],
        'limits':['500000 samples per trial, three rotated-order repetitions, seed43, eight-player15BB ChipEV and ICM/PKO only.',
            'No CPU affinity or clock control; small differences are not statistically established.',
            'Native duration includes final checkpoint output; peak working set refers only to the native process, excluding web browser/server/HRC.',
            'No FGS, MTT, raked, locked or imported warm-checkpoint performance claims; the constant cache explicitly bypasses FGS and rake.',
            'A byte-identical checkpoint proves identical sampled state for these cases, not global convergence or equivalence for untested configurations.']}
    target=ROOT/'reports/hrc-performance-audit.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'report':str(target),'probes':probes,'all_checkpoints_identical':True,
        'potential_bucket_saving_mib':result['static_opportunities'][0]['potential_saved_bytes']/1048576}))
    if not all(p['identical'] for p in probes.values()):raise SystemExit('Probe regression')


if __name__=='__main__':main()
