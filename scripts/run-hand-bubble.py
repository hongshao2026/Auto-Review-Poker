"""Independent full-tree initialization then EP CI10, using generated inputs.

Original nodedata and terminal utilities never enter either native invocation.
This functional run can overlap application work; it is not a timing benchmark.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_native import BUILD, build
from preflop_lab.hrc_sampling import write_scope_descriptor


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true', required=True)
    args = p.parse_args()
    folder = ROOT / '.research-cache/hand-bubble-20261108'
    config = json.loads((folder / 'config.json').read_text())
    compact = json.loads((folder / 'input/tree.json').read_text())
    descriptor, selection = write_scope_descriptor(compact, folder, 'selected_subtree', [0])
    executable = build()
    plan = dict(output=str(folder), tree_binary=str(folder / 'input/tree.bin'),
                resources_dir=str(ROOT / '.research-cache/abstractions'), seed=config['seed'],
                build=json.loads((BUILD / 'build.json').read_text()), training_threads=20,
                initialization_samples=10_000_000, initialization_track_ci=False,
                formal_track_ci=True, formal_target_ci=10, formal_total_sample_cap=3_000_000_000,
                maximum_additional_samples=2_990_000_000, hard_seconds_per_phase=21600,
                memory_budget_bytes=8 << 30, mode='v4')
    plan['build']['executable_path'] = str(executable)
    report = {'status': 'running', 'purpose': 'functional independent solve, not a speed benchmark',
              'original_archive': 'C:/Users/Shao/HoldemResources/SavedHands/Hand bubble.hrcz',
              'original_sha256': '0657418a1d2f237e585d04c29dfd507ebff4f7d04755ad916989b023e71ea376',
              'source_policy_used_for_training': False, 'saved_leaf_utilities_used': False,
              'selection': selection, 'plan': plan, 'phases': {}}
    module_spec = importlib.util.spec_from_file_location('bubble_monitor', ROOT / 'scripts/benchmark-hrc-ci-target.py')
    monitor = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(monitor)
    original_command = monitor.phase_command

    def command(current, name, **kwargs):
        result = original_command(current, name, **kwargs)
        if name == 'formal':
            result[16] = str(descriptor)
        return result

    monitor.phase_command = command
    destination = ROOT / 'reports/hrc-hand-bubble-run-20261108.json'

    def persist():
        monitor.dump(folder / 'run-report.json', report)
        monitor.dump(destination, report)

    persist()
    try:
        with (folder / 'run.log').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
            initial = monitor.run_phase(plan, 'initialization')
            report['phases']['initialization'] = initial
            persist()
            if initial['summary']['iteration'] != 10_000_000:
                raise RuntimeError('Initialization stopped before 10m; formal EP solve was not started')
            checkpoint = folder / 'initialization/checkpoint.bin'
            report['initialization_checkpoint_sha256_before'] = sha(checkpoint)
            formal = monitor.run_phase(plan, 'formal', resume=checkpoint)
            report['phases']['formal'] = formal
            report['initialization_checkpoint_unchanged'] = sha(checkpoint) == report['initialization_checkpoint_sha256_before']
            summary = formal['summary']
            if summary['stop_reason'] != 'ci_target' or summary['ci']['value'] >= 10:
                raise RuntimeError('Formal solve stopped before CI<10; checkpoint retained')
        report['status'] = 'completed'
    except Exception as error:
        report.update(status='incomplete', error=str(error))
        raise
    finally:
        persist()
    print(json.dumps({'status': report['status'], 'selection': selection,
                      'formal': report['phases']['formal']['summary']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
