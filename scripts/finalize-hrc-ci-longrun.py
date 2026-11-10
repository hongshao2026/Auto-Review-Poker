"""Remove the owned CI observation hook after the selected long run finishes.

Waits outside the chat with no sampling deadline. Never stops HRC or sampling.
Uses the audited v2 agent and original process handle, not a reused PID alone.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def main():
    import win32api, win32con, win32event, win32process
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--check-only', action='store_true')
    a = p.parse_args(); folder = a.output.resolve()
    handoff = json.loads((folder/'gui-handoff.json').read_text(encoding='utf-8'))
    manifest = json.loads(Path(handoff['active_observer_manifest']).read_text(encoding='utf-8'))
    command = handoff['cleanup_command_argv']; pid = handoff['pid']
    expected = ['--add-modules', 'jdk.attach', '-cp', manifest['classes'],
                'HrcCiAttach', str(pid), manifest['agent'], 'stop']
    if command[1:] != expected: raise ValueError('Unexpected cleanup command')
    for key in ('agent', 'sink'):
        if hashlib.sha256(Path(manifest[key]).read_bytes()).hexdigest() != manifest[key+'_sha256']:
            raise ValueError('Observation artifact identity mismatch')
    proc = win32api.OpenProcess(0x100000 | 0x0400, False, pid)
    creation = str(win32process.GetProcessTimes(proc)['CreationTime'])
    state = json.loads((folder/'status.json').read_text(encoding='utf-8'))
    if state['pid'] != pid or state['process_creation'] != creation:
        raise ValueError('Selected HRC process identity changed')
    if a.check_only:
        print(json.dumps({'validated': True, 'pid': pid, 'command': command})); return
    result = {'pid': pid, 'process_creation': creation, 'hook_removed': False}
    try:
        while True:
            if win32event.WaitForSingleObject(proc, 0) == win32con.WAIT_OBJECT_0:
                result['status'] = 'original_process_exited_hook_no_longer_loaded'; break
            state = json.loads((folder/'status.json').read_text(encoding='utf-8'))
            terminal = state['status']
            if terminal in ('completed_and_saved', 'ci_target_reached_save_needs_attention',
                            'idle_without_verified_ci_target'):
                run = subprocess.run(command, capture_output=True, text=True, timeout=45)
                (folder/'hook-cleanup-stdout.log').write_text(run.stdout, encoding='utf-8')
                (folder/'hook-cleanup-stderr.log').write_text(run.stderr, encoding='utf-8')
                rows = [json.loads(line) for line in (folder/'agent-events.jsonl').read_text().splitlines()]
                removed = any(r.get('event') == 'removed_and_original_class_restored' and
                              r.get('remove_returned_true') is True for r in rows)
                result.update(status='cleaned_up' if run.returncode == 0 and removed else 'cleanup_needs_attention',
                    hook_removed=run.returncode == 0 and removed, returncode=run.returncode,
                    target_status=terminal, ci_target_reached=state['ci_target_reached'])
                break
            if terminal == 'monitor_error_sampling_not_cancelled':
                result['status'] = 'monitor_needs_attention_hook_retained_for_running_job'; break
            time.sleep(30)
    except Exception as exc:
        result.update(status='cleanup_needs_attention', error=str(exc))
    finally:
        win32api.CloseHandle(proc)
        (folder/'finalizer-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__': main()
