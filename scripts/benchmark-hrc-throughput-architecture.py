"""Isolated A/B of terminal tables and independently ticketed workers."""
from __future__ import annotations
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_native import build


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=5_000_000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--cases', nargs='+', choices=['frozen8','current_off8','tables8','scheduler8','combined8','combined4'])
    parser.add_argument('--output', type=Path, default=ROOT/'.research-cache/throughput-architecture-20261107/benchmark')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/hrc-throughput-architecture-20261108.json')
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    source = ROOT/'.research-cache/three40bb-ci10-independent-20261107'
    initial = source/'initialization/checkpoint.bin'; formal = source/'formal/checkpoint.bin'
    frozen = json.loads((ROOT/'.research-cache/throughput-architecture-20261107/baseline.json').read_text(encoding='utf-8'))
    exe = build()
    spec = importlib.util.spec_from_file_location('architecture_monitor', ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor = importlib.util.module_from_spec(spec); spec.loader.exec_module(monitor)
    old_command = monitor.phase_command

    def command(plan, name, *, resume=None):
        result = old_command(plan, name, resume=resume)
        if plan['variant_flags'] is not None:
            assert len(result) == 19
            result += ['1000000000', *map(str, plan['variant_flags'])]
        return result

    monitor.phase_command = command
    base = json.loads((source/'plan.json').read_text(encoding='utf-8'))
    base.update(output=str(output), formal_track_ci=False, formal_target_ci=-1,
                hard_seconds_per_phase=120, formal_total_sample_cap=10_000_000+args.samples)
    base.pop('maximum_additional_samples', None)
    report = {'schema': 'throughput-architecture-ab-v1', 'status': 'running',
              'output': str(output), 'new_executable': str(exe), 'new_executable_sha256': sha(exe),
              'baseline': frozen, 'source_checkpoint_sha256': sha(initial),
              'formal_checkpoint_sha256_before': sha(formal),
              'samples_per_trial': args.samples, 'repeats': args.repeats,
              'serial_exactness': [], 'trials': [],
              'limits': ['Fixed-sample throughput is not a CI10 runtime or strategy quality proof.',
                         'Asynchronous scheduling changes update interleavings and worker sample allocation.',
                         'Alternating sequential trials; no fixed CPU affinity or clock.',
                         'Formal checkpoints are never modified or used as training inputs.']}

    def run(name, executable, flags, threads, samples):
        plan = copy.deepcopy(base)
        plan['build']['executable_path'] = executable
        plan.update(variant_flags=flags, training_threads=threads,
                    formal_total_sample_cap=10_000_000+samples)
        with (output/'events.log').open('a', encoding='utf-8') as log, contextlib.redirect_stdout(log):
            result = monitor.run_phase(plan, name, resume=initial)
        summary = result['summary']
        if summary['stop_reason'] != 'sample_target' or summary['iteration'] != 10_000_000+samples:
            raise RuntimeError('Trial did not complete its exact budget: '+name)
        result['samples_per_second'] = samples/summary['elapsed_seconds']
        return result

    try:
        # Both table modes retain the old serial numerical/RNG trajectory.
        for name, executable, flags in [('frozen', frozen['baseline_executable'], None),
                                        ('current_off', str(exe), (0, 0)),
                                        ('current_tables', str(exe), (1, 0))]:
            row = run('serial_'+name, executable, flags, 1, 100_000)
            row['checkpoint_sha256'] = sha(Path(row['output'])/'checkpoint.bin')
            report['serial_exactness'].append(row)
        report['serial_checkpoints_equal'] = len({x['checkpoint_sha256'] for x in report['serial_exactness']}) == 1
        if not report['serial_checkpoints_equal']:
            raise RuntimeError('Serial tables changed learned arrays, RNG or root values')
        cases = [('frozen8', frozen['baseline_executable'], None, 8),
                 ('current_off8', str(exe), (0, 0), 8),
                 ('tables8', str(exe), (1, 0), 8),
                 ('scheduler8', str(exe), (0, 1), 8),
                 ('combined8', str(exe), (1, 1), 8),
                 ('combined4', str(exe), (1, 1), 4)]
        if args.cases:
            if 'frozen8' not in args.cases: raise ValueError('Cases must retain the frozen8 control')
            cases = [case for case in cases if case[0] in args.cases]
        for repeat in range(args.repeats):
            order = cases[repeat:]+cases[:repeat]
            if repeat % 2: order = list(reversed(order))
            for name, executable, flags, threads in order:
                row = run(f'{name}_r{repeat}', executable, flags, threads, args.samples)
                row.update(variant=name, repeat=repeat)
                report['trials'].append(row)
                monitor.dump(args.report, report)
                print(json.dumps({'variant': name, 'repeat': repeat,
                                  'seconds': row['summary']['elapsed_seconds'],
                                  'million_samples_per_second': row['samples_per_second']/1e6,
                                  'control_rounds': row['summary'].get('parallel_control_rounds')}, ensure_ascii=False), flush=True)
        report['medians'] = {}
        for name, _, _, _ in cases:
            rows = [r for r in report['trials'] if r['variant'] == name]
            seconds = [r['summary']['elapsed_seconds'] for r in rows]
            report['medians'][name] = {'seconds': statistics.median(seconds),
                                      'min_seconds': min(seconds), 'max_seconds': max(seconds),
                                      'samples_per_second': args.samples/statistics.median(seconds)}
        baseline = report['medians']['frozen8']['seconds']
        for row in report['medians'].values(): row['speed_vs_frozen8'] = baseline/row['seconds']
        report['status'] = 'completed'
    finally:
        report['formal_checkpoint_sha256_after'] = sha(formal)
        report['formal_checkpoint_unchanged'] = sha(formal) == report['formal_checkpoint_sha256_before']
        report['source_checkpoint_unchanged'] = sha(initial) == report['source_checkpoint_sha256']
        monitor.dump(args.report, report); monitor.dump(output/'report.json', report)
    print(json.dumps({'status': report['status'], 'medians': report.get('medians'),
                      'report': str(args.report)}, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
