"""Validate hot-bucket checkpoint compatibility, then run matched throughput and CI trials."""
import argparse
import contextlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / '.research-cache/hand-bubble-20261108'
CACHE = ROOT / '.research-cache/mtt-hot-buckets-20261109'
BASELINE = ROOT / '.research-cache/bubble-round2-20261109/accepted/solver.exe'
TREE = CASE / 'input/tree.bin'
SCOPE = CASE / 'sampling-scope.bin'
HOT_NODES = (1, 2, 3)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_monitor():
    spec = importlib.util.spec_from_file_location('monitor', ROOT / 'scripts/benchmark-hrc-ci-target.py')
    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)
    original_command = monitor.phase_command

    def command(plan, name, **kwargs):
        result = original_command(plan, name, **kwargs)
        result[15] = '0'
        result[16] = str(SCOPE)
        result[18] = '0'
        return result + ['1', '1', '0', '1']

    monitor.phase_command = command
    return monitor


def snapshot(path):
    metadata = read(path.with_name('index.json'))
    with path.open('rb') as stream:
        magic, tree, samples = struct.unpack('<8sQQ', stream.read(24))
        assert magic == b'HRSOLV03' and tree == 17353740244742836947 and metadata['samples'] == samples
        nodes = {}
        for node_id in range(4):
            node = metadata['nodes'][node_id]
            assert node['id'] == node_id and node['format'] == 23 and node['buckets'] == 169
            stream.seek(node['visits_offset'] - 12)
            updates, store = struct.unpack('<QI', stream.read(12))
            assert (updates, store) == (node['updates'], node['format'])
            visits = struct.unpack('<169Q', stream.read(169 * 8))
            assert stream.tell() == node['raw_offset']
            raw = struct.unpack(f'<{node["raw_count"]}d', stream.read(node['raw_count'] * 8))
            assert all(math.isfinite(value) for value in raw) and 0 <= raw[0] <= updates
            nodes[node_id] = {'updates': updates, 'visits': visits, 'raw': raw, 'actions': node['actions']}
    return samples, nodes


def verify_checkpoint(before, after, additional):
    first_samples, original = snapshot(before)
    final_samples, changed = snapshot(after)
    assert final_samples - first_samples == additional
    assert original[0] == changed[0], 'UTG outside selected subtree must stay frozen'
    result = {}
    for node_id in HOT_NODES:
        a, b = original[node_id], changed[node_id]
        delta = b['updates'] - a['updates']
        by_bucket = [new - old for new, old in zip(b['visits'], a['visits'])]
        assert min(by_bucket) >= 0 and sum(by_bucket) == delta and 0 <= delta <= additional
        assert b['raw'][0] >= a['raw'][0]
        if node_id == 1:
            assert delta == additional, 'Each selected-root deal updates EP once'
        result[node_id] = {'update_delta': delta, 'sum_of_visit_deltas': sum(by_bucket),
                           'counter_published': b['raw'][0], 'updates': b['updates']}
    return result


def compare_ep(a, b):
    def policy(path):
        _, nodes = snapshot(path)
        n = nodes[1]
        k = n['actions']
        rows = []
        for bucket in range(169):
            start = 1 + (2 * k + 1) * bucket + k + 1
            weights = [max(0, v) for v in n['raw'][start:start+k]]
            total = sum(weights)
            rows.append([w / total for w in weights] if total else [1 / k] * k)
        return rows

    aa, bb = policy(a), policy(b)
    combos = [6 if row == col else 4 if row > col else 12 for row in range(13) for col in range(13)]

    def overall(rows):
        return [sum(c * row[action] for c, row in zip(combos, rows)) / 1326
                for action in range(len(rows[0]))]

    tv = [sum(abs(x - y) for x, y in zip(p, q)) / 2 for p, q in zip(aa, bb)]
    return {'actions': ['fold', 'raise_2bb', 'all_in'], 'baseline': overall(aa), 'striped8': overall(bb),
            'combo_weighted_total_variation_pp': 100 * sum(c * d for c, d in zip(combos, tv)) / 1326,
            'max_hand_total_variation_pp': 100 * max(tv)}


def training_cpu(folder, trial):
    events = (folder / trial['phase'] / 'monitor.jsonl').read_text(encoding='utf-8').splitlines()
    samples = [json.loads(line) for line in events]
    start = next(s for s in samples if s['wall_seconds'] >= trial['loading_setup_and_initial_save_seconds'])
    end = samples[-1]
    cpu = end['cpu_seconds'] - start['cpu_seconds']
    a, b = start['system_cpu_times'], end['system_cpu_times']
    busy = sum(b[k] - a[k] for k in ('kernel_seconds_including_idle', 'user_seconds')) - (
        b['idle_seconds'] - a['idle_seconds'])
    return {'solver_cpu_seconds_sampled': cpu,
            'other_mean_logical_cpus': (busy - cpu) / (end['wall_seconds'] - start['wall_seconds'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, default=CACHE / 'striped8/solver.exe')
    parser.add_argument('--ci-source', type=Path, default=CASE / 'formal/checkpoint.bin')
    parser.add_argument('--ci-hard-seconds', type=int, default=7200)
    args = parser.parse_args()
    output, candidate, ci_source = args.output.resolve(), args.candidate.resolve(), args.ci_source.resolve()
    assert output.is_relative_to(ROOT.resolve())
    monitor = load_monitor()
    manifest = read(candidate.with_name('manifest.json'))
    assert monitor.sha(candidate) == manifest['candidate_sha256']
    assert monitor.sha(BASELINE) == manifest['baseline_sha256']
    executables = {'baseline': BASELINE, 'striped8': candidate}
    initial = CASE / 'initialization/checkpoint.bin'
    inputs = {str(path): monitor.sha(path) for path in (TREE, SCOPE, initial, initial.with_name('index.json'),
              ci_source, ci_source.with_name('index.json'))}
    old_ci = (read(ci_source.with_name('index.json')).get('ci') or {}).get('value')
    assert old_ci is None or old_ci >= 10, 'CI trial must start above target when source CI is available'
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'builds': manifest, 'source_hashes': inputs, 'source_historical_ci': old_ci,
              'workload': 'Hand bubble, 20 threads, EP selected subtree [0]', 'stages': {}}

    def save():
        monitor.dump(output / 'report.json', report)

    def phase(name, label, source, additional, ci=False):
        with source.open('rb') as stream:
            stream.seek(16)
            starting, = struct.unpack('<Q', stream.read(8))
        plan = {'output': str(output), 'tree_binary': str(TREE), 'resources_dir': str(ROOT / '.research-cache/abstractions'),
                'seed': 43, 'build': {'executable_path': str(executables[label])}, 'mode': 'v4',
                'formal_track_ci': ci, 'formal_target_ci': 10 if ci else -1, 'formal_total_sample_cap': starting + additional,
                'maximum_additional_samples': max(1, additional), 'hard_seconds_per_phase': args.ci_hard_seconds if ci else 900,
                'memory_budget_bytes': 8 << 30, 'training_threads': 20}
        report['active_phase'] = name
        save()
        print(json.dumps({'status': 'phase_started', 'phase': name, 'initial_samples': starting}), flush=True)
        with (output / (name + '.runner.log')).open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
            result = monitor.run_phase(plan, name, resume=source)
        summary = result['summary']
        assert summary['sampling_path'] == [0] and summary['sampling_root_node_id'] == 1
        assert summary['training_threads'] == 20 and summary['unlocked_strategy_reads']
        assert summary.get('hot_bucket_stripes', 0) == (8 if label == 'striped8' else 0)
        assert summary.get('hot_bucket_node_count', 0) == (3 if label == 'striped8' else 0)
        completed = summary['iteration'] - starting
        assert completed == summary['scope_effective_samples'] and summary['terminal_settlements'] == 0
        if not ci:
            assert completed == additional and summary['stop_reason'] == 'sample_target'
        if additional:
            result['cpu_during_training'] = training_cpu(output, result)
        result['compute_seconds'] = summary['elapsed_seconds'] - summary['training_checkpoint_seconds']
        result['additional_samples'] = completed
        result['counter_validation'] = verify_checkpoint(source, output / name / 'checkpoint.bin', completed)
        result['checkpoint_sha256'] = monitor.sha(output / name / 'checkpoint.bin')
        if ci:
            with (output / name / 'ci-snapshots.jsonl').open(encoding='utf-8') as stream:
                first = next(stream, None)
            result['first_ci_snapshot'] = json.loads(first) if first else None
            value = (summary.get('ci') or {}).get('value')
            result['reached_ci10'] = summary['stop_reason'] == 'ci_target' and value is not None and value < 10
        report['stages'][name] = result
        save()
        print(json.dumps({'status': 'phase_complete', 'phase': name, 'samples': completed,
                          'compute_seconds': result['compute_seconds'], 'training_seconds': summary['elapsed_seconds'],
                          'ci': (summary.get('ci') or {}).get('value')}), flush=True)
        return output / name / 'checkpoint.bin'

    try:
        smoke = phase('striped8-smoke', 'striped8', initial, 2_000_000)
        for label in executables:
            resaved = phase(label + '-resave', label, smoke, 0)
            assert monitor.sha(resaved) == monitor.sha(smoke), f'{label} changed an unchanged binary checkpoint'
        phase('striped8-resume', 'striped8', smoke, 2_000_000)
        report['validation'] = 'passed'
        save()

        fixed = output / 'fixed'
        subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts/benchmark-hrc-bubble-round2.py'),
                        '--execute', '--output', str(fixed), '--samples', '50000000', '--repeats', '2',
                        '--source', str(ci_source), '--case', 'baseline', str(BASELINE), '20',
                        '--case', 'striped8', str(candidate), '20'], check=True)
        fixed_report = read(fixed / 'report.json')
        assert fixed_report['inputs_unchanged'] and fixed_report['status'] == 'completed'
        for row in fixed_report['trials']:
            summary = row['summary']
            assert summary['sampling_path'] == [0] and summary['training_threads'] == 20
            assert summary.get('hot_bucket_stripes', 0) == (8 if row['variant'] == 'striped8' else 0)
            assert summary.get('hot_bucket_node_count', 0) == (3 if row['variant'] == 'striped8' else 0)
            row['cpu_during_training'] = training_cpu(fixed, row)
        report['fixed_work'] = fixed_report
        save()

        endings = {label: phase(label + '-ci10', label, ci_source, 20_000_000_000, ci=True)
                   for label in ('striped8', 'baseline')}
        report['ep_policy_comparison'] = compare_ep(endings['baseline'], endings['striped8'])
        report['status'] = 'completed' if all(report['stages'][f'{label}-ci10']['reached_ci10']
                                              for label in executables) else 'incomplete_ci'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        report['inputs_unchanged'] = all(monitor.sha(Path(path)) == digest for path, digest in inputs.items())
        save()
    assert report['inputs_unchanged']


if __name__ == '__main__':
    main()
