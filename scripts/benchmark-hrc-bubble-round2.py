"""Fixed-work bubble benchmarks with frozen inputs and bounded disk usage."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import struct

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / '.research-cache/monetary-table-20261109/accepted/solver.exe'
SOURCE = ROOT / '.research-cache/runs/91504bf5f41e43028c2ed1ce912df1cd/checkpoint.bin'
CASE = ROOT / '.research-cache/hand-bubble-20261108'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', action='append', nargs=3, metavar=('NAME', 'EXE', 'THREADS'))
    parser.add_argument('--samples', type=int, default=20_000_000)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--scope', type=Path, default=CASE / 'sampling-scope.bin')
    parser.add_argument('--tree', type=Path, default=CASE / 'input/tree.bin')
    parser.add_argument('--threads', nargs='+', type=int, default=[1, 4, 8, 12, 16, 20])
    args = parser.parse_args()
    cases = [(name, Path(exe).resolve(), int(threads)) for name, exe, threads in args.case] if args.case else [
        (f'threads{n}', BASELINE, n) for n in args.threads]
    if any(not 1 <= threads <= 32 for _, _, threads in cases):
        raise ValueError('Threads must be 1..32')
    output = args.output.resolve()
    if not output.is_relative_to(ROOT.resolve()):
        raise ValueError('Benchmark outputs must stay inside the workspace')
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('bubble_monitor', ROOT / 'scripts/benchmark-hrc-ci-target.py')
    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)
    original_command = monitor.phase_command
    def command(plan, name, **kwargs):
        cmd = original_command(plan, name, **kwargs)
        cmd[15] = '0'
        cmd[16] = str(args.scope.resolve())
        cmd[18] = '0'
        return cmd + ['1', '1', '0', '1']
    monitor.phase_command = command
    with args.source.open('rb') as stream:
        initial = struct.unpack_from('<Q', stream.read(24), 16)[0]
    inputs = [args.source, args.source.with_name('index.json'), args.tree, args.scope]
    report = dict(status='running', purpose='Fixed work; CI off; no claim of time-to-CI or HRC speed',
                  source_samples=initial, samples=args.samples, repeats=args.repeats,
                  input_sha256={str(p): sha(p) for p in inputs}, cases={
                      n: dict(exe=str(e), sha256=sha(e), threads=t) for n, e, t in cases}, trials=[])
    def save():
        monitor.dump(output / 'report.json', report)
    save()
    try:
        for repeat in range(args.repeats):
            order = cases if repeat % 2 == 0 else list(reversed(cases))
            for name, exe, threads in order:
                phase = f'{name}-r{repeat}'
                plan = dict(output=str(output), tree_binary=str(args.tree.resolve()),
                            resources_dir=str(ROOT / '.research-cache/abstractions'), seed=43,
                            build=dict(executable_path=str(exe)), mode='v4', formal_track_ci=False,
                            formal_target_ci=-1, formal_total_sample_cap=initial + args.samples,
                            maximum_additional_samples=args.samples, hard_seconds_per_phase=900,
                            memory_budget_bytes=8 << 30, training_threads=threads)
                with (output / (phase + '.runner.log')).open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
                    row = monitor.run_phase(plan, phase, resume=args.source)
                s = row['summary']
                assert s['iteration'] == initial + args.samples and s['stop_reason'] == 'sample_target'
                assert s['terminal_tables'] and s['terminal_settlements'] == 0
                row.update(variant=name, repeat=repeat, samples_per_second=args.samples / s['elapsed_seconds'])
                row['compute_seconds'] = s['elapsed_seconds'] - s['training_checkpoint_seconds']
                row['compute_samples_per_second'] = args.samples / row['compute_seconds']
                # Remove only this new trial's generated copies, after hashing.
                # Never remove source checkpoints or whole directories.
                for filename in ('checkpoint.bin', 'index.json'):
                    generated = (Path(row['output']) / filename).resolve()
                    if not generated.is_relative_to(output) or generated in [p.resolve() for p in inputs]:
                        raise ValueError('Generated output path escaped exclusive trial')
                    row[filename + '_sha256'] = sha(generated)
                    generated.unlink()
                report['trials'].append(row)
                save()
                print(json.dumps(dict(phase=phase, training_seconds=s['elapsed_seconds'],
                                      compute_million_per_second=row['compute_samples_per_second'] / 1e6,
                                      wall_seconds=row['wall_seconds'], mean_cpus=row['average_logical_cpus'])), flush=True)
        report['medians'] = {}
        for name, _, _ in cases:
            rows = [r for r in report['trials'] if r['variant'] == name]
            report['medians'][name] = {key: statistics.median(r[key] for r in rows) for key in (
                'wall_seconds', 'compute_seconds', 'compute_samples_per_second', 'samples_per_second', 'average_logical_cpus')}
        report['status'] = 'completed'
    except Exception as exc:
        report.update(status='failed', error=str(exc))
        raise
    finally:
        report['inputs_unchanged'] = all(sha(Path(p)) == digest for p, digest in report['input_sha256'].items())
        save()
    print(json.dumps(dict(status=report['status'], medians=report['medians'])), flush=True)


if __name__ == '__main__':
    main()
