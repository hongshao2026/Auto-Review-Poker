"""Small post-completion fixed-sample diagnostics; never changes the CI run."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT/'.research-cache/three40bb-ci10-independent-20261107'
REPORT = ROOT/'reports/hrc-three40bb-throughput-diagnostic-20261107.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=DEFAULT)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--include-old', action='store_true')
    args = parser.parse_args()
    folder = args.run.resolve()
    spec = importlib.util.spec_from_file_location('ci_monitor', ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor = importlib.util.module_from_spec(spec); spec.loader.exec_module(monitor)
    plan = json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    diag = folder/'throughput-diagnostics'
    cases = [('current4', 4, plan['build']['executable_path']),
             ('current8', 8, plan['build']['executable_path'])]
    if args.include_old:
        cases.append(('old8', 8, str(ROOT/'analysis/hrc-native/build/hrc_research_solver-2daac8135134f017a7b5.exe')))
    description = {'status': 'prepared', 'output': str(diag),
        'source_checkpoint': str(folder/'initialization/checkpoint.bin'),
        'source_samples': 10_000_000, 'new_samples_per_case': 5_000_000,
        'ci_enabled': False, 'resets': False, 'cases': cases,
        'limitations': ['One short observation per condition; no statistical speedup claim.',
            'Asynchronous update order and training policies can vary with thread count.',
            'Old/current comparison also includes prior checkpoint I/O changes and resource-domain checks.'],
        'measurements': []}
    if not args.execute:
        print(json.dumps(description, indent=2)); return
    final = json.loads((folder/'formal/summary.json').read_text(encoding='utf-8'))
    if not (final['stop_reason'] == 'ci_target' and final['target_reached'] and final['ci']['value'] < 10):
        raise ValueError('The formal run must reach CI10 before any diagnostic sampling')
    if diag.exists():
        raise ValueError('Refusing to overwrite an existing diagnostic directory')
    diag.mkdir()
    description['source_checkpoint_sha256'] = monitor.sha(folder/'initialization/checkpoint.bin')
    description['formal_checkpoint_sha256_before'] = monitor.sha(folder/'formal/checkpoint.bin')
    started = time.perf_counter()
    try:
        for name, threads, executable in cases:
            current = copy.deepcopy(plan)
            current.update(output=str(diag), formal_track_ci=False, formal_target_ci=-1,
                formal_total_sample_cap=15_000_000, training_threads=threads,
                hard_seconds_per_phase=30)
            current.pop('maximum_additional_samples', None)
            current['build']['executable_path'] = executable
            result = monitor.run_phase(current, name, resume=folder/'initialization/checkpoint.bin')
            result['executable_sha256'] = monitor.sha(Path(executable))
            result['new_samples'] = result['summary']['iteration']-10_000_000
            result['new_samples_per_native_second'] = result['new_samples']/result['summary']['elapsed_seconds']
            if result['summary']['stop_reason'] != 'sample_target' or result['new_samples'] != 5_000_000:
                raise ValueError(f'{name} failed to finish its fixed sample budget')
            description['measurements'].append(result)
            monitor.dump(diag/'report.json', description)
        description['status'] = 'completed'
    finally:
        description['wall_seconds'] = time.perf_counter()-started
        description['formal_checkpoint_sha256_after'] = monitor.sha(folder/'formal/checkpoint.bin')
        description['formal_checkpoint_unchanged'] = description['formal_checkpoint_sha256_before'] == description['formal_checkpoint_sha256_after']
        monitor.dump(diag/'report.json', description); monitor.dump(REPORT, description)
    print(json.dumps({'status': description['status'], 'report': str(REPORT)}), flush=True)


if __name__ == '__main__': main()
