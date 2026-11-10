"""Watch one explicitly authorized HRC CI run without a sampling time limit.

Never clicks Cancel or restarts HRC. Numeric CI comes from the audited mr hook.
After CI<target AND stable original idle, Save As is allowed only when the
dialog's default filename identifies the selected working document exactly.
No foreground/global keyboard input or whole-desktop capture is used.
"""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import time
import zipfile


def local_now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def dump(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def valid_ci(row, start):
    ci = row.get('ci')
    return (row.get('event') == 'original_mr_constructor' and
            type(row.get('index')) is int and row['index'] >= 0 and
            type(row.get('original_epoch_millis')) is int and row['original_epoch_millis'] >= start and
            type(ci) in (int, float) and math.isfinite(ci) and ci >= 0)


def matching_edit(rows, filename):
    return [r for r in rows if r['class'] == 'Edit' and r['enabled'] and
            PureWindowsPath(r['text']).name.casefold() == filename.casefold()]


def classify(rows, seen, idle_count, ci, target, foreign, cpu_busy=False):
    active = cpu_busy or any('MC-CFR' in r['text'] or ': Monte Carlo Sampling' in r['text'] or
                 r['text'] == 'Sampling...' for r in rows)
    idle = any('No operations to display' in r['text'] for r in rows)
    seen = seen or active
    idle_count = idle_count+1 if seen and idle and not active else 0
    reached = ci is not None and ci < target and not foreign
    return active, seen, idle_count, reached and idle_count >= 2


def archive_identity(path):
    with zipfile.ZipFile(path) as archive:
        for name in ('settings.json', 'state.json', 'gametree.dat', 'nodedata.dat', 'idx.dat'):
            if archive.namelist().count(name) != 1:
                raise ValueError('Missing/duplicate archive member: '+name)
        settings = archive.read('settings.json'); tree = archive.read('gametree.dat')
        json.loads(settings); json.loads(archive.read('state.json'))
        return {'settings_sha256': hashlib.sha256(settings).hexdigest(),
                'gametree_sha256': hashlib.sha256(tree).hexdigest(),
                'nodes': int.from_bytes(tree[:4], 'little', signed=True)}


def main():
    import os
    import win32api, win32con, win32event, win32gui, win32process
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args(); folder = a.output.resolve()
    cfg = json.loads((folder/'start.json').read_text(encoding='utf-8'))
    pid, main_window = cfg['pid'], cfg['main_hwnd']
    start = cfg['run_start_epoch_millis']; target = cfg['target_ci']
    working = Path(cfg['working_archive']).resolve()
    final = folder/'nine40bb-fulltree-ci-below10-final.hrcz'
    if final.exists() or (folder/'monitor-instance.json').exists():
        raise ValueError('Existing monitor/output; inspect before starting another instance')
    if win32process.GetWindowThreadProcessId(main_window)[1] != pid:
        raise ValueError('Main window belongs to another process')
    identity = archive_identity(working)
    if identity['nodes'] != 494055: raise ValueError('Wrong full tree')
    proc = win32api.OpenProcess(0x100000 | 0x0410, False, pid)
    creation = str(win32process.GetProcessTimes(proc)['CreationTime'])
    power = ctypes.windll.kernel32.SetThreadExecutionState
    power.argtypes = [ctypes.c_uint32]; power.restype = ctypes.c_uint32
    held = bool(power(0x80000001))  # System required; display may still turn off.
    state = dict(status='monitoring', pid=pid, main_hwnd=main_window, monitor_pid=os.getpid(),
        started_local=local_now(), target_ci=target, sampling_time_limit_seconds=None,
        idle_sleep_prevention_held=held, process_creation=creation,
        working_archive=str(working), final_archive=None, ci_target_reached=False,
        ci_numeric_source='original mr constructor arguments', last_ci=None,
        original_run_samples=None, foreign_sampling_observed=False)
    dump(folder/'monitor-instance.json', state)
    events = (folder/'monitor-events.jsonl').open('a', encoding='utf-8', buffering=1)
    def event(kind, **data):
        events.write(json.dumps({'local_time': local_now(), **data, 'event': kind}, ensure_ascii=False)+'\n')
    def rows(parent=None):
        result = []
        def add(h, root=False):
            if win32process.GetWindowThreadProcessId(h)[1] == pid and win32gui.IsWindowVisible(h):
                result.append(dict(hwnd=h, root=root, text=win32gui.GetWindowText(h),
                    **{'class': win32gui.GetClassName(h)}, enabled=bool(win32gui.IsWindowEnabled(h))))
        if parent is not None:
            win32gui.EnumChildWindows(parent, lambda h, _: add(h), None)
        else:
            roots = []
            def top(h, _):
                if win32process.GetWindowThreadProcessId(h)[1] == pid and win32gui.IsWindowVisible(h):
                    roots.append(h)
            win32gui.EnumWindows(top, None)
            for h in roots:
                add(h, True); win32gui.EnumChildWindows(h, lambda c, _: add(c), None)
        return result
    def save_final():
        before = rows()
        if any(r['root'] and r['class'] == '#32770' for r in before):
            raise ValueError('Unexpected modal dialog; final save requires attention')
        win32gui.PostMessage(main_window, win32con.WM_COMMAND, 123, 0)
        deadline = time.monotonic()+30; dialog = None
        while time.monotonic() < deadline:
            dialogs = [r for r in rows() if r['root'] and r['class'] == '#32770']
            if len(dialogs) == 1:
                dialog = dialogs[0]['hwnd']; break
            time.sleep(.25)
        if dialog is None: raise ValueError('Save As dialog not observed')
        candidates = matching_edit(rows(dialog), working.name)
        if len(candidates) != 1:
            # Only dismiss this known dialog. Never enter a path for another hand.
            win32gui.PostMessage(dialog, win32con.WM_COMMAND, 2, 0)
            raise ValueError('Save As default filename does not identify the working hand')
        edit = candidates[0]['hwnd']; button = win32gui.GetDlgItem(dialog, 1)
        if not button or not win32gui.IsWindowEnabled(button): raise ValueError('Save control unavailable')
        if final.exists(): raise ValueError('Final output already exists; refusing overwrite')
        win32gui.SendMessageTimeout(edit, win32con.WM_SETTEXT, 0, str(final), win32con.SMTO_ABORTIFHUNG, 2000)
        if win32gui.GetWindowText(edit) != str(final): raise ValueError('Save path was not accepted')
        win32gui.PostMessage(button, win32con.BM_CLICK, 0, 0)
        event('final_save_requested', path=str(final), default_filename_verified=True)
        deadline = time.monotonic()+600; previous = None; stable = 0
        while time.monotonic() < deadline:
            if final.exists() and not win32gui.IsWindow(dialog):
                stat = final.stat(); current = (stat.st_size, stat.st_mtime_ns)
                stable = stable+1 if current == previous else 0; previous = current
                if stable >= 2:
                    actual = archive_identity(final)
                    if actual != identity: raise ValueError('Final archive settings/tree mismatch')
                    return dict(path=str(final), bytes=stat.st_size, sha256=sha(final), **actual)
            time.sleep(2)
        raise ValueError('Final save did not finish within its separate 10-minute I/O bound')
    seen = False; idle = 0; offset = 0; partial = b''; ci = None; foreign = False
    errors = 0; started = time.monotonic(); last_event = started-60
    times = win32process.GetProcessTimes(proc)
    previous_cpu = (times['KernelTime']+times['UserTime'])/1e7
    event('monitor_started', power_request_held=held, **identity)
    try:
        while True:
            if win32event.WaitForSingleObject(proc, 0) == win32con.WAIT_OBJECT_0:
                state['status'] = 'process_exited_before_verified_saved_result'; break
            try:
                path = folder/'original-ci.jsonl'
                if path.exists():
                    with path.open('rb') as stream:
                        stream.seek(offset); chunk = stream.read(); offset = stream.tell()
                    data = (partial+chunk).split(b'\n'); partial = data.pop()
                    for line in data:
                        try: record = json.loads(line)
                        except ValueError: continue
                        if valid_ci(record, start):
                            ci = record['ci']; state.update(last_ci=ci,
                                original_run_samples=record.get('original_samples'),
                                last_ci_epoch_millis=record['original_epoch_millis'])
                            event('ci_observed', record=record)
                current = rows()
                times = win32process.GetProcessTimes(proc)
                cpu = (times['KernelTime']+times['UserTime'])/1e7
                cpu_busy = cpu-previous_cpu > 2.5; previous_cpu = cpu
                foreign |= any(': Monte Carlo Sampling' in r['text'] and
                               not r['text'].startswith(working.name+':') for r in current)
                active, seen, idle, complete = classify(current, seen, idle, ci, target, foreign, cpu_busy)
                state.update(updated_local=local_now(), active=active, seen_sampling=seen,
                    process_cpu_seconds=cpu, cpu_busy=cpu_busy,
                    elapsed_wall_seconds=(time.time_ns()//1000000-start)/1000,
                    foreign_sampling_observed=foreign,
                    visible_progress=[r['text'] for r in current if 'CI' in r['text']])
                if complete:
                    state.update(status='ci_target_reached_saving', ci_target_reached=True,
                        completed_local=local_now(), completion_epoch_millis=time.time_ns()//1000000)
                    dump(folder/'status.json', state)
                    try:
                        state['final_archive'] = save_final(); state['status'] = 'completed_and_saved'
                    except Exception as exc:
                        state.update(status='ci_target_reached_save_needs_attention', save_error=str(exc))
                    break
                if idle >= 3:
                    state['status'] = 'idle_without_verified_ci_target'; break
                if time.monotonic()-last_event >= 60:
                    event('heartbeat', last_ci=ci, active=active, original_run_samples=state['original_run_samples'])
                    last_event = time.monotonic()
                errors = 0
            except Exception as exc:
                errors += 1; event('observation_error', error=str(exc), consecutive=errors)
                if errors >= 12:
                    state.update(status='monitor_error_sampling_not_cancelled', error=str(exc)); break
            dump(folder/'status.json', state)
            time.sleep(5)
    finally:
        power(0x80000000); state['idle_sleep_prevention_held'] = False
        state['monitor_finished_local'] = local_now(); dump(folder/'status.json', state)
        event('monitor_finished', status=state['status']); events.close(); win32api.CloseHandle(proc)
    print(json.dumps(state, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
