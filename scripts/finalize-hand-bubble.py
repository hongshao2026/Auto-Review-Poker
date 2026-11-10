"""Finish this one already-running case: retain status, compare, publish.

This finite helper does not start/restart any solver or change its stop target.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / '.research-cache/hand-bubble-20261108'
LIVE = ROOT / 'reports/hrc-hand-bubble-live-status.json'


def save(payload):
    temporary = LIVE.with_suffix('.json.part')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(LIVE)


def progress():
    path = CASE / 'formal/stdout.jsonl'
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size-131072))
        lines = stream.read().decode('utf-8', errors='replace').splitlines()
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get('kind') in ('progress', 'finished'):
            ci = row.get('ci') or {}
            return dict(samples=row['iteration'], elapsed_seconds=row['elapsed_seconds'],
                        ci=ci.get('value'), target_ci=10, heuristic_eta_seconds=ci.get('eta_seconds'),
                        scope=row.get('sampling_scope'), path=[0],
                        precision_target_reached=row.get('stop_reason') == 'ci_target' and row.get('target_reached', False))
    return {}


def main():
    deadline = time.monotonic() + 7 * 3600
    while time.monotonic() < deadline:
        report = json.loads((CASE / 'run-report.json').read_text())
        current = dict(updated_utc=datetime.now(timezone.utc).isoformat(),
                       status=report['status'], progress=progress(),
                       original_policy_used_for_training=False,
                       initialization_job_id='c91b410871fa4388851c857bf6dca100')
        save(current)
        if report['status'] != 'running':
            if not (CASE / 'formal/summary.json').exists():
                raise RuntimeError('Native phase failed without a finished checkpoint; see run-report.json')
            subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts/compare-hand-bubble.py'), 'formal'], check=True, cwd=ROOT)
            subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts/publish-hand-bubble.py'), 'formal'], check=True, cwd=ROOT)
            current.update(processing_status='completed', formal_job_id='c91b410871fa4388851c857bf6dca101')
            save(current)
            print(json.dumps(current, ensure_ascii=False), flush=True)
            return
        time.sleep(15)
    raise TimeoutError('Finalizer watchdog expired; solver was not terminated and its files were retained')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        save(dict(status='finalizer_error', error=str(error), updated_utc=datetime.now(timezone.utc).isoformat()))
        raise
