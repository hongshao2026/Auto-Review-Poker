"""Measured full-tree CI benchmark. Preparation is harmless; --execute runs it.

No original policies, original leaf values, tree reduction, or kernel variants.
The only production change for this run is the 4 -> 8 GiB budget domain check.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TREE = ROOT/'.research-cache/deep-tree-optimization-20261106/nine40bb_large_chip'
RESOURCES = ROOT/'.research-cache/abstractions'
REPORT = ROOT/'reports/hrc-nine40bb-ci10-independent-20261106.json'
DEFAULT_OUT = ROOT/'.research-cache/nine40bb-ci10-independent-20261106'
ORIGINAL_SETTINGS = ROOT/'analysis/hrc-desktop/nine40bb-large-ci-settings-20261106.json'


def now(): return datetime.now(timezone.utc).isoformat()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def preflight(output):
    build = json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text())
    manifest = json.loads((TREE/'manifest.json').read_text())
    resources = json.loads((RESOURCES/'manifest.json').read_text())
    settings = json.loads(ORIGINAL_SETTINGS.read_text())
    expected = settings['engine']['configuration']['abstractions']
    for profile in resources['profiles']:
        original = next(x for x in expected if x['street'] == profile['street'])
        if (profile['id'], profile['buckets']) != (original['id'], original['buckets']):
            raise ValueError('Original/static abstraction resource mismatch')
    if (manifest['nodes'], manifest['decision_nodes']) != (494055, 233802):
        raise ValueError('This benchmark requires the complete nine-player 40BB tree')
    executable = Path(build['executable_path'])
    if not executable.is_file() or sha(executable) != build['executable_sha256']:
        raise ValueError('Prebuilt executable hash mismatch; benchmark does not compile')
    return {'schema': 'independent-fulltree-ci-target-benchmark-v1', 'prepared_utc': now(),
        'status': 'ready_not_started', 'output': str(output), 'build': build,
        'tree': manifest, 'tree_binary': str(TREE/'tree.bin'),
        'original_settings': str(ORIGINAL_SETTINGS), 'resource_profiles': resources['profiles'],
        'resource_ids_match_original_settings': True,
        'original_strategy_read': False, 'original_leaf_values_read': False,
        'fresh_zero': True, 'scope': 'full_tree', 'mode': 'v4', 'seed': 43,
        'training_threads': 8, 'initialization_samples': 10000000,
        'formal_target_ci': 10, 'formal_total_sample_cap': 1000000000,
        'hard_seconds_per_phase': 3600, 'reset_regret': False, 'reset_average': False,
        'memory_budget_bytes': 6 << 30, 'default_memory_budget_unchanged': True,
        'memory_preflight': {'prior_same_tree_8thread_estimate_bytes': 3686596834,
            'three_preflop_ci_snapshots_reservation_bytes': 680891456,
            'estimated_total_bytes': 4367488290, 'excess_over_4gib_bytes': 72520994,
            'estimate_is_not_peak_rss': True},
        'production_change': {'file': 'native/hrc_research_solver.cpp',
            'before': 'max_memory>(uint64_t(4)<<30)', 'after': 'max_memory>(uint64_t(8)<<30)',
            'error_after': 'Native memory budget must be between 1 MiB and 8 GiB',
            'algorithm_changed': False},
        'timing_boundaries': {'phase_wall': 'Popen to exit, includes loading and all saves',
            'native_elapsed': 'training stage including CI and periodic/final checkpoint I/O',
            'loading_and_setup': 'Popen to started event; includes initial saves and initial CI snapshot',
            'ci_snapshot_cost': 'Not separately instrumented; history and adaptive interval retained',
            'checkpoint_seconds': 'Native timer including binary and JSON index writes; no fsync'},
        'comparison_limits': ['Independent RNG and asynchronous update order differ from HRC.',
            'CI is policy drift, not exploitability or a statistical confidence interval.',
            'HRC has no equivalent explicit native memory budget.',
            'Full node/path/terminal equality audit is a separate post-run check.'], 'phases': {}}


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class ThreadEntry(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
        ('thread_id', wintypes.DWORD), ('process_id', wintypes.DWORD),
        ('base_priority', wintypes.LONG), ('delta_priority', wintypes.LONG), ('flags', wintypes.DWORD)]


def process_environment(module,handle):
    """Observe scheduling restrictions; never change priority/power/affinity."""
    k=module.kernel;result={}
    k.GetProcessAffinityMask.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
    own,system=ctypes.c_size_t(),ctypes.c_size_t()
    if k.GetProcessAffinityMask(handle,ctypes.byref(own),ctypes.byref(system)):
        result.update(process_affinity_mask=own.value,system_affinity_mask=system.value)
    k.GetPriorityClass.argtypes=[wintypes.HANDLE];k.GetPriorityClass.restype=wintypes.DWORD
    result['priority_class']=k.GetPriorityClass(handle)
    class Power(ctypes.Structure):
        _fields_=[('version',wintypes.DWORD),('control_mask',wintypes.DWORD),('state_mask',wintypes.DWORD)]
    power=Power(1,0,0)
    k.GetProcessInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    if k.GetProcessInformation(handle,4,ctypes.byref(power),ctypes.sizeof(power)):
        result['power_throttling']={name:getattr(power,name) for name,_ in Power._fields_}
    return result


def system_cpu_times(module):
    values=[wintypes.FILETIME() for _ in range(3)]
    k=module.kernel;k.GetSystemTimes.argtypes=[ctypes.POINTER(wintypes.FILETIME)]*3
    if k.GetSystemTimes(*[ctypes.byref(value) for value in values]):
        return {name:((value.dwHighDateTime<<32)|value.dwLowDateTime)*1e-7
                for name,value in zip(('idle_seconds','kernel_seconds_including_idle','user_seconds'),values)}
    return None


def request_high_qos(module,handle):
    # Scoped to the newly spawned benchmark child. No global power policy,
    # affinity or priority change. Microsoft documents control=1/state=0.
    class Power(ctypes.Structure):
        _fields_=[('version',wintypes.DWORD),('control_mask',wintypes.DWORD),('state_mask',wintypes.DWORD)]
    power=Power(1,1,0);k=module.kernel
    k.SetProcessInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    ok=bool(k.SetProcessInformation(handle,4,ctypes.byref(power),ctypes.sizeof(power)))
    return {'requested':'high_qos','succeeded':ok,'win32_error':0 if ok else ctypes.get_last_error()}


def monitor_helpers():
    spec = importlib.util.spec_from_file_location('performance_audit', ROOT/'scripts/audit-hrc-performance.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    k = module.kernel
    k.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IoCounters)]
    k.GetProcessIoCounters.restype = wintypes.BOOL
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Thread32First.argtypes = k.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    k.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenThread.restype = wintypes.HANDLE
    k.GetThreadTimes.argtypes = [wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return module


def thread_times(module, pid):
    k = module.kernel; result = {}
    snap = k.CreateToolhelp32Snapshot(4, 0)
    if snap == ctypes.c_void_p(-1).value: return result
    entry = ThreadEntry(); entry.size = ctypes.sizeof(entry)
    try:
        valid = k.Thread32First(snap, ctypes.byref(entry))
        while valid:
            if entry.process_id == pid:
                handle = k.OpenThread(0x0800, False, entry.thread_id)
                if handle:
                    values = [wintypes.FILETIME() for _ in range(4)]
                    if k.GetThreadTimes(handle, *[ctypes.byref(x) for x in values]):
                        result[str(entry.thread_id)] = sum((v.dwHighDateTime<<32)|v.dwLowDateTime for v in values[2:])*1e-7
                    k.CloseHandle(handle)
            valid = k.Thread32Next(snap, ctypes.byref(entry))
    finally: k.CloseHandle(snap)
    return result


def phase_command(plan, name, *, resume=None):
    folder = Path(plan['output'])/name
    initial = name == 'initialization'
    samples = plan.get('initialization_samples', 10000000) if initial else plan.get('formal_total_sample_cap', 1000000000)
    track_ci = bool(plan.get('initialization_track_ci', False)) if initial else bool(plan.get('formal_track_ci', True))
    command = [plan['build']['executable_path'], str(plan.get('tree_binary', TREE/'tree.bin')),
        str(plan.get('resources_dir', RESOURCES)), str(samples), str(plan.get('seed', 43)),
        str(folder), plan.get('mode', 'v4'), str(resume) if resume else '-',
        '0', '0', '-1', '-1' if initial else str(plan.get('formal_target_ci', 10)),
        str(plan.get('hard_seconds_per_phase', 3600)), str(plan.get('memory_budget_bytes', 6<<30)),
        str(plan.get('training_threads', 8)), '1', '-', str(int(track_ci)), '1']
    if not initial and 'maximum_additional_samples' in plan:
        command.append(str(plan['maximum_additional_samples']))
    return command


def run_phase(plan, name, *, resume=None):
    folder = Path(plan['output'])/name; folder.mkdir(exist_ok=False)
    command = phase_command(plan, name, resume=resume)
    dump(folder/'command.json', command)
    helper = monitor_helpers(); started = time.perf_counter(); wall_start = now()
    peak = 0; peak_commit = 0; last_cpu = 0.; last_time = 0.; peak_threads = {}
    rows = []; seen_ci = set(); started_wall = None; partial = ''; environment_after_started=None
    with (folder/'stdout.jsonl').open('w', encoding='utf-8') as out, (folder/'stderr.log').open('w', encoding='utf-8') as err, \
         (folder/'monitor.jsonl').open('w', encoding='utf-8') as monitor, (folder/'events.jsonl').open('w', encoding='utf-8') as events, \
         (folder/'ci-snapshots.jsonl').open('w', encoding='utf-8') as ci_file:
        process = subprocess.Popen(command, stdout=out, stderr=err, text=True)
        qos=request_high_qos(helper,process._handle) if plan.get('high_qos') else None
        environment=process_environment(helper,process._handle)
        if qos:environment['explicit_power_request']=qos
        dump(folder/'process.json', {'pid': process.pid, 'started_utc': wall_start, 'command': command})
        print(json.dumps({'kind': 'phase_spawned', 'phase': name, 'pid': process.pid, 'output': str(folder)}), flush=True)
        with (folder/'stdout.jsonl').open('r', encoding='utf-8') as reader:
            while True:
                elapsed = time.perf_counter()-started
                memory = helper.Memory(); memory.cb = ctypes.sizeof(memory)
                valid_memory = helper.psapi.GetProcessMemoryInfo(process._handle, ctypes.byref(memory), memory.cb)
                cpu = helper.cpu_seconds(process._handle)
                io = IoCounters(); helper.kernel.GetProcessIoCounters(process._handle, ctypes.byref(io))
                threads = thread_times(helper, process.pid)
                for tid, value in threads.items(): peak_threads[tid] = max(value, peak_threads.get(tid, 0))
                sample = {'wall_seconds': elapsed, 'cpu_seconds': cpu,
                    'logical_cpus_interval': (cpu-last_cpu)/(elapsed-last_time) if cpu is not None and elapsed>last_time else None,
                    'thread_cpu_seconds': threads, 'io': {n: getattr(io, n) for n, _ in io._fields_}}
                sample['system_cpu_times']=system_cpu_times(helper)
                if valid_memory:
                    peak = max(peak, memory.PeakWorkingSetSize); peak_commit = max(peak_commit, memory.PeakPagefileUsage)
                    sample.update(working_set_bytes=memory.WorkingSetSize, peak_working_set_bytes=peak,
                        private_commit_bytes=memory.PagefileUsage, page_faults=memory.PageFaultCount)
                temporaries = {}
                for filename in ('checkpoint.tmp', 'index.tmp'):
                    try: temporaries[filename] = (folder/filename).stat().st_size
                    except FileNotFoundError: pass
                sample['checkpoint_temporaries'] = temporaries
                monitor.write(json.dumps(sample)+'\n'); monitor.flush()
                # Observe exit before draining: if it exits after the read this
                # iteration, one final loop still drains the finished line.
                exited = process.poll() is not None
                partial += reader.read()
                lines = partial.split('\n'); partial = lines.pop()
                for line in lines:
                    if not line.strip(): continue
                    try: row = json.loads(line)
                    except ValueError: continue
                    rows.append(row); wrapped = {'observed_wall_seconds': elapsed, 'event': row}
                    events.write(json.dumps(wrapped)+'\n'); events.flush()
                    if row.get('kind') == 'started':
                        started_wall = elapsed
                        environment_after_started=process_environment(helper,process._handle)
                    ci = row.get('ci') or {}
                    for record in ci.get('history', []):
                        ordinal = record['ordinal']
                        if ordinal not in seen_ci:
                            seen_ci.add(ordinal); ci_file.write(json.dumps({'observed_wall_seconds': elapsed,
                                'adaptive_interval_ms': ci.get('interval_ms'), **record})+'\n'); ci_file.flush()
                    if row.get('kind') != 'progress': print(json.dumps({'phase': name, **row}), flush=True)
                last_cpu = cpu or last_cpu; last_time = elapsed
                if exited: break
                time.sleep(.25)
        process.wait()
    elapsed = time.perf_counter()-started; cpu = helper.cpu_seconds(process._handle)
    finished = next((r for r in reversed(rows) if r.get('kind') == 'finished'), None)
    result = {'phase': name, 'pid': process.pid, 'started_utc': wall_start, 'finished_utc': now(),
        'returncode': process.returncode, 'wall_seconds': elapsed, 'process_cpu_seconds': cpu,
        'process_environment':environment,
        'process_environment_after_started':environment_after_started,
        'average_logical_cpus': cpu/elapsed if cpu is not None else None,
        'thread_cpu_seconds_observed_max': peak_threads, 'peak_working_set_bytes': peak,
        'peak_private_commit_bytes': peak_commit, 'loading_setup_and_initial_save_seconds': started_wall,
        'last_io_counters': {n: getattr(io, n) for n, _ in io._fields_},
        'summary': finished, 'output': str(folder), 'command': command}
    if finished:
        # Preserve the unmodified native finished event for independent
        # comparison tools; do not synthesize fields from the product API.
        dump(folder/'summary.json', finished)
        c = finished.get('checkpoint_seconds', 0); training_c = finished.get('training_checkpoint_seconds', 0)
        result['initial_checkpoint_seconds'] = c-training_c
        result['setup_excluding_checkpoint_seconds_estimate'] = started_wall-(c-training_c) if started_wall is not None else None
        result['training_checkpoint_fraction'] = training_c/finished['elapsed_seconds'] if finished['elapsed_seconds'] else None
        result['checkpoint_total_fraction_of_wall'] = c/elapsed
    dump(folder/'measurement.json', result)
    if process.returncode or not finished: raise RuntimeError(f'{name} failed; retained logs at {folder}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(); output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any((output/name).exists() for name in ('initialization', 'formal')):
        raise ValueError('Exclusive benchmark directory already contains a run; refusing overwrite')
    plan = preflight(output); dump(output/'plan.json', plan); dump(REPORT, plan)
    if not args.execute:
        print(json.dumps({'status': 'READY', 'output': str(output), 'report': str(REPORT)})); return
    plan['status'] = 'running'; plan['started_utc'] = now(); dump(REPORT, plan)
    start = time.perf_counter()
    try:
        initialization = run_phase(plan, 'initialization'); plan['phases']['initialization'] = initialization
        dump(REPORT, plan)
        if initialization['summary']['iteration'] != 10000000 or initialization['summary']['stop_reason'] != 'sample_target':
            raise RuntimeError('Initialization did not complete exactly 10m; formal run not started')
        formal = run_phase(plan, 'formal', resume=output/'initialization/checkpoint.bin')
        plan['phases']['formal'] = formal
        final = formal['summary']; value = (final.get('ci') or {}).get('value')
        reached = final.get('stop_reason') == 'ci_target' and final.get('target_reached') and value is not None and value < 10
        plan.update(status='ci_target_reached' if reached else 'stopped_without_ci_target', ci_target_reached=bool(reached),
            formal_training_ci_seconds=final['elapsed_seconds'], formal_wall_seconds=formal['wall_seconds'])
    except Exception as exc:
        plan.update(status='failed', error=str(exc)); raise
    finally:
        plan.update(finished_utc=now(), total_wall_seconds=time.perf_counter()-start)
        dump(REPORT, plan); dump(output/'report.json', plan)
    print(json.dumps({'status': plan['status'], 'report': str(REPORT)}), flush=True)


if __name__ == '__main__': main()
