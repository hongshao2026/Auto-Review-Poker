"""Verify the already-running local app picks up the changed native source."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8769'


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = Request(BASE + path, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=120) as response:
        return json.load(response)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pe_section_hashes(path):
    data = Path(path).read_bytes()
    pe = struct.unpack_from('<I', data, 60)[0]
    count = struct.unpack_from('<H', data, pe + 6)[0]
    optional_size = struct.unpack_from('<H', data, pe + 20)[0]
    sections = {}
    for i in range(count):
        start = pe + 24 + optional_size + 40 * i
        name = data[start:start + 8].split(b'\0')[0].decode()
        size, offset = struct.unpack_from('<II', data, start + 16)
        sections[name] = hashlib.sha256(data[offset:offset + size]).hexdigest()
    return sections


def main():
    formal = json.loads((ROOT / 'reports/hrc-three40bb-ci10-node-lock-20261108.json').read_text(encoding='utf-8'))
    if formal['status'] != 'ci_target_reached':
        raise RuntimeError('Do not run the API compilation/smoke during the formal timing run')
    old_job = ROOT / '.runs/1d898413dc2e416ea087fc2f30202f5d.json'
    old_sha = sha(old_job)
    previous = json.loads((ROOT / '.runs/2b9cb5ede0554d21a2b5213145c80fcc.json').read_text(encoding='utf-8'))
    config = previous['config']
    config.update(iterations=1003, threads=2, stopping_mode='samples', sampling_stage='calculation')
    config.pop('target_ci', None)
    created = request('/api/jobs', {'config': config})
    job_id = created['id']
    started = time.monotonic()
    while True:
        state = request('/api/jobs/' + job_id)
        if state['status'] in ('completed', 'failed', 'cancelled'):
            break
        if time.monotonic() - started > 120:
            raise RuntimeError('API smoke exceeded 120s; job ' + job_id)
        time.sleep(.25)
    if state['status'] != 'completed':
        raise RuntimeError(json.dumps(state, ensure_ascii=False))
    exported = request('/api/jobs/' + job_id + '/export')
    summary = exported['summary']
    assert summary['iterations_completed'] == 1003 and summary['training_threads'] == 2
    assert summary['terminal_tables'] and summary['parallel_scheduler'] == 'independent_blocks'
    assert summary['terminal_settlements'] == 0
    stamp = json.loads((ROOT / 'analysis/hrc-native/build/build.json').read_text(encoding='utf-8'))
    benchmark = json.loads((ROOT / 'reports/hrc-throughput-round2-final-20261108.json').read_text(encoding='utf-8'))
    sections = {'api': pe_section_hashes(stamp['executable_path']),
                'measured': pe_section_hashes(benchmark['cases']['current'])}
    equal_code = sections['api']['.text'] == sections['measured']['.text']
    result = {'status': 'completed', 'job_id': job_id, 'summary': summary,
              'build': stamp, 'previous_ui_job_unchanged': sha(old_job) == old_sha,
              'node_header_sha256': sha(ROOT / 'native/hrc_node_mutex.hpp'),
              'native_text_section_equal_to_measured': equal_code,
              'native_pe_section_hashes': sections,
              'limits': ['The running service retains its previously imported Python build helper.',
                         'This changed CPP triggers a new build; future header-only changes require refreshing that Python process.']}
    assert result['previous_ui_job_unchanged'] and equal_code
    output = ROOT / 'reports/hrc-node-lock-api-smoke-20261108.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'job_id': job_id, 'status': result['status'],
                      'native_executable': stamp['executable_path'], 'report': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
