"""Publish a verified local build to the observed, inactive legacy cache alias.

Keeps port 8769 running. Only this invocation's newly generated native artifact
may be replaced; its original bytes and the global stamp are backed up first.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab import hrc_native as native
from preflop_lab.hrc_benchmarks import config_for

OUT = ROOT / '.research-cache/cpu-round4-20261108/live-deployment'
BASE_URL = 'http://127.0.0.1:8769'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def request(path, data=None):
    encoded = json.dumps(data).encode() if data is not None else None
    with urlopen(Request(BASE_URL + path, data=encoded,
                         headers={'Content-Type': 'application/json'}), timeout=30) as response:
        return json.load(response)


def native_processes():
    class Entry(c.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
                    ('heap', c.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                    ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD),
                    ('name', w.WCHAR * 260)]
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [w.HANDLE, c.POINTER(Entry)]
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == c.c_void_p(-1).value:
        raise OSError('Cannot inspect native process use')
    result = []
    try:
        entry = Entry(); entry.size = c.sizeof(entry)
        valid = kernel.Process32FirstW(snapshot, c.byref(entry))
        while valid:
            if entry.name.lower().startswith('hrc_research_solver-'):
                handle = kernel.OpenProcess(0x1000, False, entry.pid)
                if not handle:
                    raise OSError('Cannot inspect matching native process')
                try:
                    size = w.DWORD(32768); buffer = c.create_unicode_buffer(size.value)
                    if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, c.byref(size)):
                        raise OSError('Cannot resolve matching native executable')
                    result.append({'pid': entry.pid, 'path': buffer.value})
                finally:
                    kernel.CloseHandle(handle)
            valid = kernel.Process32NextW(snapshot, c.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return result


def no_active_jobs():
    active = [job['id'] for job in request('/api/jobs')['jobs']
              if job['status'] in ('running', 'cancelling')]
    if active:
        raise RuntimeError('Live jobs are active; leaving them untouched: ' + ','.join(active))


def smoke(label):
    cfg = config_for('hu10bb', iterations=5_000_000)
    cfg['threads'] = 2
    created = request('/api/jobs', {'config': cfg})
    seen = {}
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        for process in native_processes():
            seen[process['pid']] = process
        job = request('/api/jobs/' + created['id'])
        if job['status'] not in ('running', 'cancelling'):
            break
        time.sleep(.03)
    else:
        raise RuntimeError('Smoke job has not finished; no cache publication performed')
    (OUT / (label + '-job.json')).write_text(json.dumps(job, indent=2) + '\n')
    assert job['status'] == 'completed', job.get('error')
    assert job['summary']['iterations_completed'] == 5_000_000
    assert job['summary']['native_qos_requested'] and job['summary']['native_qos_active']
    assert seen, 'Native executable was not observed; refusing inferred cache key'
    return {'id': created['id'], 'status': job['status'], 'observed_processes': list(seen.values()),
            'native_qos_active': job['summary']['native_qos_active']}


def main():
    OUT.mkdir(exist_ok=False)
    accepted = json.loads((OUT.parent / 'accepted/production-build.json').read_text())
    canonical = Path(accepted['executable_path'])
    assert sha(canonical) == accepted['executable_sha256']
    for name, metadata in accepted['identity_spec']['source_files'].items():
        assert sha(ROOT / 'native' / name) == metadata['sha256']
    no_active_jobs()
    before = {path.resolve() for path in native.BUILD.glob('hrc_research_solver-*.exe')}
    started_ns = time.time_ns()
    result = {'status': 'observing', 'build_identity': accepted['build_identity']}
    report = OUT / 'report.json'
    result['before'] = smoke('before')
    stamp_path = native.BUILD / 'build.json'
    observed = json.loads(stamp_path.read_text())
    legacy = observed['source_sha256']
    alias = (native.BUILD / ('hrc_research_solver-' + legacy[:20] + '.exe')).resolve()
    paths = {Path(p['path']).resolve() for p in result['before']['observed_processes']}
    assert paths == {alias}, 'Global stamp does not describe the actually observed child'
    assert alias not in before and alias.stat().st_mtime_ns >= started_ns
    assert alias.parent == native.BUILD.resolve()
    no_active_jobs()
    assert not native_processes(), 'Native child remains active; leaving its image untouched'
    shutil.copy2(alias, OUT / 'before-legacy.exe')
    shutil.copy2(stamp_path, OUT / 'before-build.json')
    result.update(observed_legacy_source_sha256=legacy, alias_path=str(alias),
                  previous_alias_sha256=sha(alias), canonical_sha256=sha(canonical))
    report.write_text(json.dumps(result, indent=2) + '\n')
    staging = alias.with_name(alias.name + '.round4.pending')
    shutil.copy2(canonical, staging)
    assert sha(staging) == accepted['executable_sha256']
    assert json.loads(stamp_path.read_text()) == observed
    assert not native_processes()
    staging.replace(alias)
    alias_record = {'schema': 'hrc-live-legacy-alias-v1',
                    'publication_id': 'round4-live-8769-20261108',
                    'observed_legacy_source_sha256': legacy,
                    'build_identity': accepted['build_identity'],
                    'source_files': accepted['identity_spec']['source_files'],
                    'canonical_executable_sha256': accepted['executable_sha256'],
                    'alias_executable_sha256': sha(alias), 'alias_executable_path': str(alias)}
    global_record = dict(accepted, source_sha256=legacy,
                         canonical_legacy_source_sha256=accepted['source_sha256'],
                         source_sha256_semantics='observed_live_legacy_alias_key',
                         live_legacy_alias=alias_record)
    native._native_write_json(stamp_path, global_record)
    assert native.build() == canonical
    preserved = json.loads(stamp_path.read_text())
    assert preserved['source_sha256'] == legacy and preserved['live_legacy_alias'] == alias_record
    before_stat = alias.stat()
    result['after'] = smoke('after')
    assert {Path(p['path']).resolve() for p in result['after']['observed_processes']} == {alias}
    assert alias.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert sha(alias) == accepted['executable_sha256']
    assert json.loads(stamp_path.read_text()) == preserved
    assert json.loads(canonical.with_name('build.json').read_text()) == accepted
    result.update(status='passed', source_inventory_unchanged=True, no_service_restart=True,
                  new_helper_preserves_alias=True, old_helper_reused_optimized_bytes=True,
                  limits=['Compatibility publication applies to these frozen inputs only; future changes require re-verification.'])
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
