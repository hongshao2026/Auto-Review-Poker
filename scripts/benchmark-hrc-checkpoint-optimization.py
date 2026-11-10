"""Bounded old/new checkpoint benchmark on the identical 494055-node 9p40 tree.

Uses our own retained 10m checkpoint, never HRC strategies. CI is disabled to
isolate I/O throughput; this is not a measurement of time to CI10. Alternating
order balances cache/thermal effects. Serial trials require exact binary AND
index equality; parallel trials validate coherent counts, not byte equality.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_native import build, prepare

BASELINE = ROOT/'analysis/hrc-native/build/hrc_research_solver-2daac8135134f017a7b5.exe'
BASELINE_SHA = '2954da952edbd9694d4e8f7f63331ba9d11d36ddd7e53c9f95632a706d22e058'
TREE = ROOT/'.research-cache/deep-tree-optimization-20261106/nine40bb_large_chip/tree.bin'
SOURCE = ROOT/'.research-cache/nine40bb-ci10-independent-20261106/initialization/checkpoint.bin'
RESOURCES = ROOT/'.research-cache/abstractions'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding='utf-8')


def emit(obj): print(json.dumps(obj), flush=True)


def load_helpers():
    spec = importlib.util.spec_from_file_location('ci_benchmark', ROOT/'scripts/benchmark-hrc-ci-target.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module, module.monitor_helpers()


def run_one(exe, folder, *, tree=TREE, resume=SOURCE, goal=14_000_000,
            threads=8, periodic_cancel=False):
    folder.mkdir(parents=True, exist_ok=False)
    initial = 0
    if resume:
        with resume.open('rb') as f:
            f.seek(16); initial = struct.unpack('<Q', f.read(8))[0]
    command = [str(exe), str(tree), str(RESOURCES), str(goal), '43', str(folder),
               'v4', str(resume) if resume else '-', '0', '0', '-1', '-1',
               '45' if periodic_cancel else '-1', str(6 << 30), str(threads), '1', '-', '0', '1']
    dump(folder/'command.json', command)
    module, helper = load_helpers()
    started = time.perf_counter(); peak = 0; last_io = None; periodic_saved = None
    last_message = started; cancelled = False
    with (folder/'stdout.jsonl').open('w', encoding='utf-8') as out, \
         (folder/'stderr.log').open('w', encoding='utf-8') as err, \
         (folder/'monitor.jsonl').open('w', encoding='utf-8') as monitor:
        process = subprocess.Popen(command, stdout=out, stderr=err, text=True)
        emit({'kind': 'trial_started', 'trial': folder.name, 'pid': process.pid})
        while process.poll() is None:
            memory = helper.Memory(); memory.cb = ctypes.sizeof(memory)
            if helper.psapi.GetProcessMemoryInfo(process._handle, ctypes.byref(memory), memory.cb):
                peak = max(peak, memory.PeakWorkingSetSize)
            io = module.IoCounters()
            if helper.kernel.GetProcessIoCounters(process._handle, ctypes.byref(io)):
                last_io = {name: getattr(io, name) for name, _ in io._fields_}
            elapsed = time.perf_counter()-started
            monitor.write(json.dumps({'wall_seconds': elapsed, 'working_set_bytes': memory.WorkingSetSize,
                'cpu_seconds': helper.cpu_seconds(process._handle), 'io': last_io})+'\n')
            monitor.flush()
            if periodic_cancel and not cancelled:
                try:
                    index = json.loads((folder/'index.json').read_text())
                    if index['samples'] > initial:
                        periodic_saved = index['samples']
                        (folder/'cancel.request').write_text('cancel\n', encoding='ascii'); cancelled = True
                except (FileNotFoundError, ValueError): pass
            if time.perf_counter()-last_message >= 20:
                emit({'kind': 'trial_running', 'trial': folder.name, 'wall_seconds': round(elapsed, 1)})
                last_message = time.perf_counter()
            time.sleep(.1)
        process.wait()
        elapsed = time.perf_counter()-started
        cpu = helper.cpu_seconds(process._handle)
        io = module.IoCounters()
        if helper.kernel.GetProcessIoCounters(process._handle, ctypes.byref(io)):
            last_io = {name: getattr(io, name) for name, _ in io._fields_}
    rows = [json.loads(line) for line in (folder/'stdout.jsonl').read_text().splitlines() if line.strip()]
    last = next((r for r in reversed(rows) if r['kind'] == 'finished'), None)
    if process.returncode or last is None:
        raise RuntimeError(f'{folder}: {(folder/"stderr.log").read_text()[-3000:]}')
    if periodic_cancel:
        if periodic_saved is None or last['stop_reason'] != 'cancelled':
            raise ValueError('No successful periodic checkpoint observed before graceful cancel')
    elif last['iteration'] != goal or last['stop_reason'] != 'sample_target':
        raise ValueError('Fixed sample benchmark did not finish exactly')
    with (folder/'checkpoint.bin').open('rb') as f:
        f.seek(16); saved = struct.unpack('<Q', f.read(8))[0]
    if saved != last['iteration']: raise ValueError('Final checkpoint counter mismatch')
    index = json.loads((folder/'index.json').read_text())
    if index['samples'] != saved or index['training_threads'] != threads:
        raise ValueError('Index/checkpoint mismatch')
    # Root is visited by every full-tree sample, across all workers.
    node = next(n for n in index['nodes'] if n['id'] == 0)
    if node['updates'] != saved: raise ValueError('Lost root updates')
    with (folder/'checkpoint.bin').open('rb') as f:
        f.seek(node['visits_offset']); counts = struct.unpack(f'<{node["buckets"]}Q', f.read(8*node['buckets']))
    if sum(counts) != saved: raise ValueError('Lost root bucket visits')
    result = {'trial': folder.name, 'executable': str(exe), 'wall_seconds': elapsed,
        'process_cpu_seconds': cpu, 'average_logical_cpus': cpu/elapsed if cpu is not None else None,
        'peak_working_set_bytes': peak, 'io': last_io, 'initial_samples': initial,
        'new_samples': saved-initial, 'native_seconds': last['elapsed_seconds'],
        'new_samples_per_native_second': (saved-initial)/last['elapsed_seconds'],
        'checkpoint_bytes': (folder/'checkpoint.bin').stat().st_size,
        'checkpoint_sha256': sha(folder/'checkpoint.bin'), 'index_sha256': sha(folder/'index.json'),
        'periodic_saved_samples': periodic_saved, 'final_counts_valid': True, 'summary': last}
    dump(folder/'measurement.json', result)
    emit({k: result[k] for k in ('trial', 'wall_seconds', 'native_seconds', 'new_samples', 'io')})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=2, choices=(1, 2, 3))
    args = parser.parse_args(); output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if sha(BASELINE) != BASELINE_SHA: raise ValueError('Historical binary SHA mismatch')
    optimized = build()
    source_sha = sha(SOURCE)
    manifest = json.loads(TREE.with_name('manifest.json').read_text())
    if manifest['nodes'] != 494055 or manifest['players'] != 9: raise ValueError('Wrong tree')
    report = {'schema': 'hrc-checkpoint-optimization-v1', 'started_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'running', 'tree': manifest, 'tree_binary_sha256': sha(TREE),
        'source_checkpoint': str(SOURCE), 'source_sha256': source_sha, 'training_threads': 8,
        'ci_enabled': False, 'ci10_time_measured': False, 'original_strategy_read': False,
        'scope': 'full_tree', 'executables': {name: {'path': str(exe), 'sha256': sha(exe)}
            for name, exe in [('baseline', BASELINE), ('optimized', optimized)]},
        'trials': [], 'correctness': {}}
    target = output/'report.json'; dump(target, report)
    # Serialization equality across every node in the real full tree, with an
    # identical serial random stream. Exclude these from speedup aggregates.
    exact = {}
    for name, exe in [('baseline', BASELINE), ('optimized', optimized)]:
        exact[name] = run_one(exe, output/f'exact-fulltree-{name}', goal=10_002_000, threads=1)
    for field in ('checkpoint_sha256', 'index_sha256'):
        if exact['baseline'][field] != exact['optimized'][field]:
            raise ValueError(f'Full-tree exact serial equality failed: {field}')
    report['correctness']['fulltree_serial_bytes_equal'] = True
    report['correctness']['fulltree_serial'] = exact
    dump(target, report)
    for repeat in range(args.repeats):
        order = [('baseline', BASELINE), ('optimized', optimized)]
        if repeat % 2: order.reverse()
        for name, exe in order:
            row = run_one(exe, output/f'round-{repeat+1}-{name}')
            row.update(variant=name, repeat=repeat+1); report['trials'].append(row); dump(target, report)
    # Exercise real 30-second autosaving and graceful cancellation separately
    # on a small tree; no fake clock or forced process kill is involved.
    test_spec = importlib.util.spec_from_file_location('test_kernel', ROOT/'tests/test_hrc_kernel.py')
    test_module = importlib.util.module_from_spec(test_spec); test_spec.loader.exec_module(test_module)
    prepared = prepare(test_module.hu_tree(), output/'periodic-input')
    periodic = run_one(optimized, output/'periodic-cancel', tree=Path(prepared['tree_binary']),
                       resume=None, goal=1_000_000_000, threads=1, periodic_cancel=True)
    report['correctness']['actual_periodic_and_cancel'] = periodic
    source_unchanged = sha(SOURCE) == source_sha
    if not source_unchanged: raise ValueError('Source checkpoint mutated')
    report['correctness']['source_unchanged'] = source_unchanged
    medians = {}
    for name in ('baseline', 'optimized'):
        rows = [r for r in report['trials'] if r['variant'] == name]
        medians[name] = {key: statistics.median(r[key] for r in rows) for key in
            ('wall_seconds', 'native_seconds', 'new_samples_per_native_second', 'peak_working_set_bytes', 'average_logical_cpus')}
        medians[name]['checkpoint_seconds'] = statistics.median(r['summary']['checkpoint_seconds'] for r in rows)
        medians[name]['checkpoint_writes'] = statistics.median(r['summary']['checkpoint_writes'] for r in rows)
        for key in ('write_bytes', 'write_ops'):
            medians[name][key] = statistics.median(r['io'][key] for r in rows)
    report.update(status='completed', finished_utc=datetime.now(timezone.utc).isoformat(), medians=medians,
        wall_speedup=medians['baseline']['wall_seconds']/medians['optimized']['wall_seconds'],
        native_speedup=medians['baseline']['native_seconds']/medians['optimized']['native_seconds'])
    dump(target, report)
    destination = ROOT/'reports/hrc-checkpoint-optimization-20261106.json'; dump(destination, report)
    emit({'status': 'completed', 'report': str(destination), 'wall_speedup': report['wall_speedup'], 'native_speedup': report['native_speedup']})


if __name__ == '__main__': main()
