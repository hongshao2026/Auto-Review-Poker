"""Bounded MTT-only ETW/JFR observations. Never cancels another WPR session."""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import win32api
import win32con
import win32gui
import win32process

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.research-cache/mtt-hotspots-pgo-20261109'
JDK = Path('D:/Tools/REA-Research/jdk-21.0.13+9/bin')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf8')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp():
    counter = ctypes.c_longlong()
    ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    return {'qpc': counter.value, 'utc': datetime.now(timezone.utc).isoformat()}


def jcmd(pid, *args):
    return subprocess.run([str(JDK / 'jcmd.exe'), str(pid), *args], capture_output=True,
                          text=True, encoding='utf8', errors='replace', timeout=45)


def visible(pid):
    values = []
    def root(hwnd, _):
        if win32process.GetWindowThreadProcessId(hwnd)[1] != pid or not win32gui.IsWindowVisible(hwnd):
            return
        def child(handle, _):
            if win32gui.IsWindowVisible(handle):
                text = win32gui.GetWindowText(handle)
                if text:
                    values.append(text)
        values.append(win32gui.GetWindowText(hwnd))
        win32gui.EnumChildWindows(hwnd, child, None)
    win32gui.EnumWindows(root, None)
    return values


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind', choices=('native', 'hrc'), required=True)
    p.add_argument('--stage', choices=('early', 'mature'), required=True)
    p.add_argument('--pid', type=int)
    p.add_argument('--ok', type=int)
    p.add_argument('--seconds', type=float, default=10)
    p.add_argument('--samples', type=int, default=100000000)
    p.add_argument('--name')
    p.add_argument('--output-root', type=Path, default=BASE)
    p.add_argument('--exe', type=Path, help='Optional frozen native solver binary')
    p.add_argument('--source', type=Path, help='Optional frozen native checkpoint')
    a = p.parse_args()
    if a.kind != 'native' and (a.exe or a.source):
        p.error('--exe and --source are only for native captures')
    base = a.output_root.resolve()
    out = (base / (a.name or f'{a.kind}-{a.stage}')).resolve()
    assert base.is_relative_to(ROOT.resolve()) and out.is_relative_to(base)
    out.mkdir(parents=True, exist_ok=False)
    status = subprocess.run(['wpr.exe', '-status'], capture_output=True, text=True)
    assert 'WPR is not recording' in status.stdout + status.stderr, 'Existing WPR recording left untouched'
    spec = importlib.util.spec_from_file_location('mtt_monitor', ROOT / 'scripts/benchmark-hrc-ci-target.py')
    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)
    helper = monitor.monitor_helpers()
    report = {'schema': 'mtt-profile-capture-v1', 'kind': a.kind, 'stage': a.stage,
              'status': 'preparing', 'requested_capture_seconds': a.seconds,
              'fixed_successful_cycles': a.samples, 'track_ci': True,
              'sampling_path': [0], 'training_threads': 20, 'observer_started': stamp()}
    wpr_started = False
    jfr_started = False
    process = None
    pid = a.pid
    handles = []
    try:
        if a.kind == 'native':
            prior = json.loads((ROOT / '.research-cache/bubble-round2-20261109/accepted-confirm/accepted-r0/command.json').read_text())
            source = (ROOT / '.research-cache/hand-bubble-20261108/initialization/checkpoint.bin' if a.stage == 'early'
                      else ROOT / '.research-cache/runs/91504bf5f41e43028c2ed1ce912df1cd/checkpoint.bin')
            if a.source:
                source = a.source.resolve()
            with source.open('rb') as stream:
                initial = struct.unpack_from('<Q', stream.read(24), 16)[0]
            command = list(prior)
            if a.exe:
                command[0] = str(a.exe.resolve())
            command[3], command[5], command[7] = str(initial + a.samples), str(out / 'native'), str(source)
            command[19] = str(a.samples)
            command[17] = '1'
            (out / 'native').mkdir()
            stdout = (out / 'stdout.jsonl').open('w', encoding='utf8')
            stderr = (out / 'stderr.log').open('w', encoding='utf8')
            handles.extend([stdout, stderr])
            report.update(command=command, source_checkpoint=str(source), source_sha256=sha(source),
                          executable_sha256=sha(Path(command[0])), initial_samples=initial)
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            pid = process.pid
            report['pid'] = pid
            dump(out / 'capture.json', report)
            print(json.dumps({'event': 'native_spawned', 'pid': pid, 'stage': a.stage}), flush=True)
            start = time.monotonic()
            while True:
                rows = [json.loads(line) for line in (out / 'stdout.jsonl').read_text(encoding='utf8').splitlines() if line.endswith('}')]
                started = next((row for row in rows if row.get('kind') == 'started'), None)
                if started:
                    report['native_started'] = started
                    break
                assert process.poll() is None, 'Native exited before started'
                assert time.monotonic() - start < 180, 'Native preparation exceeded observation bound'
                time.sleep(.2)
        else:
            assert pid and a.ok
            assert win32process.GetWindowThreadProcessId(a.ok)[1] == pid
            assert win32gui.GetClassName(a.ok) == 'Button' and win32gui.GetWindowText(a.ok) == 'OK'
            assert not any('MC-CFR' in text for text in visible(pid)), 'HRC already sampling'
            report.update(pid=pid, ok_hwnd=a.ok, before_ok=stamp())
            dump(out / 'capture.json', report)
            win32gui.PostMessage(a.ok, win32con.BM_CLICK, 0, 0)
            start = time.monotonic()
            while not any('MC-CFR' in text for text in visible(pid)):
                assert time.monotonic() - start < 30, 'HRC sampling not observed'
                time.sleep(.1)
        time.sleep(1)
        report['sampling_active_before_capture'] = stamp()
        proc = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)
        if a.kind == 'hrc':
            threads = jcmd(pid, 'Thread.print', '-l')
            (out / 'threads.txt').write_text(threads.stdout, encoding='utf8')
            threads.check_returncode()
            worker_tids = []
            for block in threads.stdout.split('\n\n'):
                if block.startswith('"ForkJoinPool-') and 'net.holdemresources.internal.mn' in block:
                    token = re.search(r'nid=(0x[0-9a-f]+|[0-9]+)', block).group(1)
                    worker_tids.append(int(token, 16 if token.startswith('0x') else 10))
            assert len(worker_tids) == 20, f'Expected 20 original mn workers, observed {worker_tids}'
            report['worker_tids'] = worker_tids
            settings = out / 'mtt.jfc'
            settings.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<configuration version="2.0" label="MTT scoped sample">
<event name="jdk.ExecutionSample"><setting name="enabled">true</setting><setting name="period">10 ms</setting></event>
<event name="jdk.NativeMethodSample"><setting name="enabled">true</setting><setting name="period">10 ms</setting></event>
<event name="jdk.ThreadPark"><setting name="enabled">true</setting><setting name="stackTrace">true</setting><setting name="threshold">0 ms</setting></event>
<event name="jdk.JavaMonitorEnter"><setting name="enabled">true</setting><setting name="stackTrace">true</setting><setting name="threshold">100 us</setting></event>
<event name="jdk.ThreadSleep"><setting name="enabled">true</setting><setting name="stackTrace">true</setting><setting name="threshold">0 ms</setting></event>
<event name="jdk.ThreadStart"><setting name="enabled">true</setting></event>
<event name="jdk.ThreadEnd"><setting name="enabled">true</setting></event>
<event name="jdk.GarbageCollection"><setting name="enabled">true</setting></event>
<event name="jdk.GCPhasePause"><setting name="enabled">true</setting></event>
<event name="jdk.Compilation"><setting name="enabled">true</setting><setting name="threshold">10 ms</setting></event>
</configuration>''', encoding='utf8')
            result = jcmd(pid, 'JFR.start', 'name=MTT_RESEARCH', f'settings={settings}', 'disk=true')
            report['jfr_start'] = {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
            result.check_returncode()
            assert 'Started recording' in result.stdout, result.stdout + result.stderr
            jfr_started = True
        profile = out / 'mtt-cpu.wprp'
        profile.write_text((ROOT / 'scripts/hrc-solver-cpu.wprp').read_text().replace('<Buffers Value="128"/>', '<Buffers Value="256"/>'), encoding='utf8')
        result = subprocess.run(['wpr.exe', '-start', str(profile) + '!SolverCPU'], capture_output=True, text=True, check=True)
        wpr_started = True
        report['wpr_start'] = result.stdout + result.stderr
        report['capture_begin'] = stamp()
        report['thread_cpu_before'] = monitor.thread_times(helper, pid)
        times = win32process.GetProcessTimes(proc)
        report['cpu_before'] = (times['KernelTime'] + times['UserTime']) / 1e7
        report['status'] = 'recording'
        dump(out / 'capture.json', report)
        print(json.dumps({'event': 'recording', 'kind': a.kind, 'stage': a.stage, 'pid': pid}), flush=True)
        time.sleep(a.seconds)
        report['capture_end'] = stamp()
        report['thread_cpu_after'] = monitor.thread_times(helper, pid)
        times = win32process.GetProcessTimes(proc)
        report['cpu_after'] = (times['KernelTime'] + times['UserTime']) / 1e7
        report['visible_at_capture_end'] = visible(pid) if a.kind == 'hrc' else None
        if a.kind == 'native':
            deltas = sorted(((after - report['thread_cpu_before'].get(tid, after), int(tid))
                             for tid, after in report['thread_cpu_after'].items()), reverse=True)
            assert len(deltas) >= 20 and deltas[19][0] > .1
            report['worker_tids'] = [tid for delta, tid in deltas[:20]]
            report['worker_identification'] = '20 CPU-active native threads in bounded training window; validate sampled solver frames'
        report['status'] = 'captured'
    except Exception as error:
        report.update(status='failed', error=repr(error))
        raise
    finally:
        if wpr_started:
            result = subprocess.run(['wpr.exe', '-stop', str(out / 'solver-cpu.etl'), 'MTT scoped CPU and scheduler diagnosis'],
                                    capture_output=True, text=True, timeout=90)
            report['wpr_stop'] = {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        if jfr_started:
            result = jcmd(pid, 'JFR.stop', 'name=MTT_RESEARCH', f'filename={out / "original.jfr"}')
            report['jfr_stop'] = {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        dump(out / 'capture.json', report)
    if a.kind == 'native':
        process.wait(timeout=180)
        for handle in handles:
            handle.close()
        rows = [json.loads(line) for line in (out / 'stdout.jsonl').read_text().splitlines()]
        report['finished'] = rows[-1]
        assert process.returncode == 0 and rows[-1]['iteration'] == report['initial_samples'] + a.samples
        assert sha(Path(report['source_checkpoint'])) == report['source_sha256']
    else:
        start = time.monotonic()
        while any('MC-CFR' in text for text in visible(pid)):
            assert time.monotonic() - start < 120, 'HRC fixed-work run has not ended; left running'
            time.sleep(.5)
        report['observed_idle'] = stamp()
    report['status'] = 'completed'
    report['observer_finished'] = stamp()
    dump(out / 'capture.json', report)
    print(json.dumps({'status': report['status'], 'output': str(out), 'worker_tids': report['worker_tids']}), flush=True)


if __name__ == '__main__':
    main()
