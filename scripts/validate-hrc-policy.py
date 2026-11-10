"""Reproduce original my/mz vs independent native/Python numeric snapshots."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-retained',action='store_true',help='Recheck current native/Python code against retained original snapshots without running Java')
    args=parser.parse_args()
    h = runpy.run_path(str(ROOT / 'tests/test_hrc_policy.py'))
    locks, freq = h['lock_fixtures'](), h['frequency_fixtures']()
    lines = [h['lock_line'](c) for c in locks] + [h['frequency_line'](c) for c in freq]
    out = ROOT / 'analysis/hrc-deep/probes'
    out.mkdir(parents=True, exist_ok=True)
    inputs = out / 'policy-inputs.tsv'
    input_text='\n'.join(lines) + '\n'
    java = Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
    jar = Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')
    rng = Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator.mavendependencies_0.2.0\org.apache.commons\commons-rng-client-api-1.6.jar')
    classes = ROOT / 'analysis/hrc-deep/java-policy'
    source = ROOT / 'scripts/java/OriginalPolicyProbe.java'
    report_path=ROOT/'reports/hrc-original-policy-validation.json'
    original_output=out/'policy-original-output.jsonl'
    if args.replay_retained:
        previous=json.loads(report_path.read_text())
        if not previous['passed'] or previous['probe_sha256']!=hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError('Retained original probe provenance differs')
        if inputs.read_text()!=input_text:raise ValueError('Retained original inputs differ')
        command=previous['command']
        jar_hash,rng_hash=previous['jar_sha256'],previous['rng_sha256']
        original_text=original_output.read_text()
    else:
        inputs.write_text(input_text)
        classes.mkdir(exist_ok=True)
        subprocess.run([str(java.with_name('javac.exe')), '-d', str(classes), str(source)], check=True)
        command = [str(java), '-cp', str(classes), 'OriginalPolicyProbe', str(jar), str(rng), str(inputs)]
        process = subprocess.run(command, text=True, capture_output=True)
        original_output.write_text(process.stdout)
        if process.returncode:raise RuntimeError(process.stderr)
        original_text=process.stdout
        jar_hash,rng_hash=hashlib.sha256(jar.read_bytes()).hexdigest(),hashlib.sha256(rng.read_bytes()).hexdigest()
    records = [json.loads(line) for line in original_text.splitlines()]
    originals = [r for r in records if 'id' in r]
    independent = h['run_lines'](lines)
    (out / 'policy-independent-output.jsonl').write_text('\n'.join(map(json.dumps, independent))+'\n')
    reference = [h['lock_expected'](c) for c in locks] + [h['frequency_expected'](c) for c in freq]
    if not len(originals)==len(independent)==len(reference):raise ValueError('Missing policy snapshot cases')
    errors = []
    def compare(a, b):
        if isinstance(a, dict):
            assert a.keys() == b.keys()
            for key in a: compare(a[key], b[key])
        elif isinstance(a, list):
            assert len(a) == len(b)
            for x, y in zip(a, b): compare(x, y)
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            if math.isnan(a): assert math.isnan(b)
            else:
                errors.append(abs(a-b))
                assert abs(a-b) <= 1e-10 * max(1, abs(a)), (a,b)
        else: assert a == b
    results = []
    for oracle, native, python in zip(originals, independent, reference):
        try:
            compare(oracle, native); compare(oracle, python)
            results.append({'id': oracle['id'], 'passed': True})
        except AssertionError as e:
            results.append({'id': oracle['id'], 'passed': False, 'error': str(e)})
    report = {'passed': all(r['passed'] for r in results), 'lock_cases': len(locks), 'frequency_cases': len(freq),
              'frequency_snapshots': sum(len(c['steps'])+1 for c in freq), 'numeric_comparisons': len(errors),
              'max_abs_error': max(errors), 'command': command, 'jar_sha256': jar_hash,
              'rng_sha256': rng_hash, 'replayed_retained_original':args.replay_retained,
              'original_output_sha256':hashlib.sha256(original_output.read_bytes()).hexdigest(),
              'inputs_sha256':hashlib.sha256(inputs.read_bytes()).hexdigest(),
              'header_sha256': hashlib.sha256((ROOT/'native/hrc_policy.hpp').read_bytes()).hexdigest(),
              'python_sha256': hashlib.sha256((ROOT/'preflop_lab/hrc_policy.py').read_bytes()).hexdigest(),
              'probe_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'class_hashes': [r for r in records if r.get('kind') == 'class'], 'cases': results,
              'scope': 'Unmodified original my/mx lock composition/edit, mz initialization/update/cache/flush/reset/display/EV. Synthetic arrays, scripted RNG. No solver traversal, saved policies, application or licensing initialization. Single-thread CAS-success semantics.'}
    report_path.write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('class_hashes','cases','command')},indent=2))
    if not report['passed']:
        print([r for r in results if not r['passed']][:10]);raise SystemExit(1)


if __name__ == '__main__':
    main()
