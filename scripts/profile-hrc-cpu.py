"""Short isolated native diagnostic. Does not join/stop another WPR recording."""
import contextlib
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.research-cache/architecture-review-20261108/etw-cpu'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',required=True)
    parser.add_argument('--scenario',choices=['three','nine'],default='three')
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--samples',type=int,default=10_000_000)
    parser.add_argument('--resume',type=Path)
    args=parser.parse_args();OUT=args.output.resolve()
    status = subprocess.run(['wpr.exe', '-status'], capture_output=True, text=True)
    if 'WPR is not recording' not in status.stdout + status.stderr:
        raise RuntimeError('Existing/unknown WPR recording; leaving it untouched.')
    OUT.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('ci_monitor', ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)
    source = ROOT/('.research-cache/three40bb-ci10-independent-20261107' if args.scenario=='three'
                   else '.research-cache/nine40bb-ci10-independent-20261106')
    plan_path=source/'plan.json' if args.scenario=='three' else ROOT/'reports/hrc-nine40bb-ci10-independent-20261106.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    exe = ROOT/'.research-cache/throughput-round3-20261108/accepted/hrc_round3_accepted.exe'
    initial = args.resume.resolve() if args.resume else (ROOT/'.research-cache/three40bb-ci10-round3-20261108/current20/formal/checkpoint.bin'
              if args.scenario=='three' else source/'initialization/checkpoint.bin')
    import struct
    with initial.open('rb') as stream: initial_samples=struct.unpack_from('<Q',stream.read(24),16)[0]
    if sha(exe) != 'b47b89ff5a28a5c5913a0d629d6c5925496e41c5918161fc969feae6fc4680d1':
        raise RuntimeError('Frozen accepted EXE mismatch')
    reference_build = plan['build']
    accepted = json.loads((exe.parent/'manifest.json').read_text(encoding='utf-8'))
    plan['build'] = dict(accepted['build'], executable_path=str(exe))
    plan.update(output=str(OUT), training_threads=20, formal_track_ci=False,
                formal_target_ci=-1, formal_total_sample_cap=initial_samples+args.samples,
                maximum_additional_samples=args.samples, hard_seconds_per_phase=120,memory_budget_bytes=8<<30)
    result = dict(status='prepared', purpose='Current kernel on/off-CPU and sampled hotspots; not CI10 timing',
                  executable_sha256=sha(exe), initial_checkpoint=str(initial),
                  initial_sha256_before=sha(initial), plan=plan, source_plan_reference_build=reference_build,
                  sources=['https://learn.microsoft.com/en-us/windows-hardware/test/wpt/authoring-recording-profiles',
                           'https://learn.microsoft.com/en-us/windows-hardware/test/wpt/systemprovider',
                           'https://learn.microsoft.com/en-us/windows-hardware/test/wpt/cpu-analysis'])
    monitor.dump(OUT/'report.json', result)
    started = False
    try:
        profile=ROOT/'scripts/hrc-solver-cpu.wprp'
        if args.scenario=='nine':
            configured=profile.read_text(encoding='utf-8').replace('<Buffers Value="128"/>','<Buffers Value="256"/>')
            profile=OUT/'solver-cpu.wprp';profile.write_text(configured,encoding='utf-8')
        capture = subprocess.run(['wpr.exe', '-start', str(profile)+'!SolverCPU'],
                                 capture_output=True, text=True, check=True)
        started = True
        result['wpr_start_output'] = capture.stdout + capture.stderr
        result['status'] = 'recording'
        monitor.dump(OUT/'report.json', result)
        with (OUT/'runner.log').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
            result['native'] = monitor.run_phase(plan, 'sampled', resume=initial)
        result['status'] = 'native_completed'
    except Exception as error:
        result.update(status='failed', error=str(error))
        raise
    finally:
        if started:
            stopped = subprocess.run(['wpr.exe', '-stop', str(OUT/'solver-cpu.etl'),
                                      'Short isolated accepted solver CPU diagnosis'],
                                     capture_output=True, text=True, timeout=90)
            result['wpr_stop_returncode'] = stopped.returncode
            result['wpr_stop_output'] = stopped.stdout + stopped.stderr
        result['initial_unchanged'] = sha(initial) == result['initial_sha256_before']
        monitor.dump(OUT/'report.json', result)
    print(json.dumps({key: result[key] for key in ['status', 'initial_unchanged', 'wpr_stop_returncode']}))


if __name__ == '__main__':
    main()
