"""Summarize measured bubble optimization candidates without CPU work."""
import json
import hashlib
import statistics
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.research-cache/bubble-round2-20261109'


def main():
    stages = {}
    for name in ('thread-sweep', 'hotspot-screen', 'confirm', 'dedup-confirm', 'edges-confirm',
                 'serial-parity', 'accepted-confirm'):
        path = BASE / name / 'report.json'
        if path.exists():
            source = json.loads(path.read_text(encoding='utf-8'))
            stages[name] = dict(path=str(path), status=source['status'], samples=source['samples'],
                                repeats=source['repeats'], inputs_unchanged=source.get('inputs_unchanged'),
                                medians=source.get('medians'), cases=source['cases'])
            stages[name]['median_training_seconds'] = {variant:statistics.median(
                row['summary']['elapsed_seconds'] for row in source['trials'] if row['variant']==variant)
                for variant in source['cases'] if any(row['variant']==variant for row in source['trials'])}
            if name == 'serial-parity':
                hashes = {r['variant']: r['checkpoint.bin_sha256'] for r in source['trials']}
                stages[name].update(checkpoint_hashes=hashes, exact_full_checkpoint_equal=len(set(hashes.values())) == 1)
    threads = json.loads((BASE / 'thread-sweep/report.json').read_text())
    scaling = []
    for row in threads['trials']:
        samples = [json.loads(line) for line in (Path(row['output']) / 'monitor.jsonl').read_text().splitlines()]
        start = next(s for s in samples if s['wall_seconds'] >= row['loading_setup_and_initial_save_seconds'])
        end = samples[-1]
        scaling.append(dict(threads=row['summary']['training_threads'],
                            compute_samples_per_second=row['compute_samples_per_second'],
                            observed_training_logical_cpus=(end['cpu_seconds']-start['cpu_seconds'])/(end['wall_seconds']-start['wall_seconds'])))
    report = dict(schema='bubble-optimization-round2-v1',
                  scope='8 seats, MTT ICM bubble, EP after UTG folds, frozen own mature checkpoint',
                  hardware='Intel i5-13600KF: 14 physical cores, 20 logical processors',
                  baseline='033dc7741886ae9e70743c99ae3b17d9666db17410f98e3da00c6f04c4b40808',
                  stages=stages, exploratory_thread_scaling=scaling,
                  outcome_table_estimates={name: json.loads((BASE / filename).read_text()) for name, filename in (
                      ('bubble', 'terminal-dedup-estimate.json'), ('nine40bb', 'nine-terminal-dedup-estimate.json'))},
                  dedup_exhaustive_validation=json.loads((BASE / 'dedup-validation.json').read_text()),
                  board_rank_validation=json.loads((BASE / 'board-rank-validation.json').read_text()),
                  decisions={
                      'accepted': 'Reusable per-worker deal output and existing combo-card lookup; preserve draws and numeric rules',
                      'board_rank': 'No measured speed improvement; not enabled',
                      'terminal_dedup': '84% smaller table but no speed gain; experimental only, not enabled',
                      'terminal_edges': 'About 0.4% in two observations; insufficient gain, not enabled',
                      'pure3': 'Only a short screening result; not enabled'},
                  limits=[
                      'All speed ratios here compare our frozen kernels, not newly timed original HRC.',
                      'Fixed successful sampling cycles with CI off do not establish a new time-to-CI10.',
                      'Two repeats are limited evidence; CPU frequency and OS scheduling were not fixed.',
                      'Thread sweep was exploratory: some early trials overlapped candidate compilation. Confirmation runs did not.',
                      'Sampled phase clocks include observer cost and nested work; they are not additive exclusive CPU shares.',
                      'No hardware cache-miss or memory-bandwidth counters were collected; a memory bandwidth limit is not established.'])
    if 'accepted-confirm' in stages and stages['accepted-confirm'].get('medians'):
        medians=stages['accepted-confirm']['medians']
        report['accepted_speedup'] = dict(
            training=stages['accepted-confirm']['median_training_seconds']['baseline']/stages['accepted-confirm']['median_training_seconds']['accepted'],
            compute=medians['baseline']['compute_seconds']/medians['accepted']['compute_seconds'],
            total_wall=medians['baseline']['wall_seconds']/medians['accepted']['wall_seconds'])
    manifest = BASE / 'accepted/manifest.json'
    if manifest.exists():
        accepted = json.loads(manifest.read_text())
        baseline = json.loads((ROOT / 'analysis/hrc-native/build/identities' / report['baseline'] / 'build.json').read_text())
        old = baseline['identity_spec']['source_files']
        new = accepted['identity_spec']['source_files']
        report['accepted_build'] = dict(identity=accepted['build_identity'], exe_sha256=accepted['executable_sha256'],
            native_files_changed=sorted(k for k in set(old)|set(new) if old.get(k)!=new.get(k)),
            matches_current_source=all(hashlib.sha256((ROOT/'native'/k).read_bytes()).hexdigest()==v['sha256'] for k,v in new.items()),
            compiler_and_flags_unchanged=all(baseline['identity_spec'][k]==accepted['identity_spec'][k] for k in ('compiler','ordered_flags')))
    tests = ROOT / 'reports/hrc-bubble-round2-tests-20261109.xml'
    if tests.exists():
        suites = ET.parse(tests).getroot().findall('.//testsuite')
        report['regression'] = dict(path=str(tests), **{name:sum(int(s.attrib.get(name,0)) for s in suites)
            for name in ('tests','failures','errors','skipped')})
    target=ROOT / 'reports/hrc-bubble-optimization-round2-20261109.json'
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(report=str(target), accepted_speedup=report.get('accepted_speedup'),
                          serial_parity=stages.get('serial-parity',{}).get('exact_full_checkpoint_equal'))))


if __name__ == '__main__':
    main()
