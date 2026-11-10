"""Attribute sampled MTT node-lock conflicts to owners, buckets and tree paths."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import runpy
import struct

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.research-cache/mtt-contention-20261109'
CASE = ROOT / '.research-cache/hand-bubble-20261108'
POSITIONS = ('UTG', 'EP', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB')
STREETS = ('preflop', 'flop', 'turn', 'river')
STRIPES = (4, 8, 16)
RECORD = struct.Struct('<IIII')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def percent(part, total):
    return 100 * part / total if total else None


def decode(path, index):
    data = path.read_bytes()
    magic, workers, interval = struct.unpack_from('<III', data)
    assert (magic, workers, interval) == (0x314b4c48, 20, 512)
    pos, sizes = 12, []
    nodes, delays = defaultdict(Counter), defaultdict(list)
    for worker in range(workers):
        count, dropped = struct.unpack_from('<QQ', data, pos)
        assert 0 < count <= 1 << 18 and dropped == 0, (worker, count, dropped)
        sizes.append(count)
        pos += 16
        end = pos + count * RECORD.size
        for node, request, holder, wait_ns in RECORD.iter_unpack(memoryview(data)[pos:end]):
            meta = index[node]
            bucket, access = request >> 2, request & 3
            assert access in (1, 2, 3) and bucket < meta['buckets'] and meta['actions'] > 1
            stats = nodes[node]
            stats['attempts'] += 1
            stats['write_attempts' if access > 1 else 'read_attempts'] += 1
            if holder == 0:
                assert wait_ns == 0
                continue
            other_bucket, other_access = holder >> 2, holder & 3
            assert other_access in (1, 2, 3) and other_bucket < meta['buckets'] and wait_ns < 0xffffffff
            same = bucket == other_bucket
            kind = ('ww_same' if same else 'ww_different') if access > 1 and other_access > 1 else (
                'rr' if access == other_access else 'rw')
            stats['conflicts'] += 1
            stats['wait_ns'] += wait_ns
            stats[kind] += 1
            stats[kind + '_wait_ns'] += wait_ns
            if kind == 'ww_different':
                if access == 3 and other_access == 3:
                    stats['ww_different_both_marked_postflop'] += 1
                for stripes in STRIPES:
                    if bucket % stripes != other_bucket % stripes:
                        stats[f'stripes_{stripes}_separate'] += 1
            delays[kind].append(wait_ns)
        pos = end
    assert pos == len(data) and sum(sizes) == sum(n['attempts'] for n in nodes.values())
    return nodes, delays, sizes, hashlib.sha256(data).hexdigest()


def describe(tree, hrc, node):
    original = hrc[node]
    native = tree['nodes'][node]
    assert native['actor'] == original['actor'] and native['street'] == original['street']
    actions = []
    cursor = node
    while hrc[cursor]['parent_id'] != -1:
        actions.extend(reversed(hrc[cursor]['incoming_actions']))
        cursor = hrc[cursor]['parent_id']
    history = []
    for action in reversed(actions):
        label = POSITIONS[action['actor']] + ' ' + action['kind']
        if action['kind'] in ('raise', 'call'):
            label += f" {action['amount_internal'] / tree['big_blind']:.3g} BB"
        if action['allin_flag']:
            label += ' all-in'
        history.append(label)
    return {'node': node, 'path': original['path'], 'street': STREETS[original['street']],
            'actor': POSITIONS[original['actor']], 'history': history}


def distribution(values):
    values.sort()
    return {f'p{p}_ns': values[(len(values) - 1) * p // 100] for p in (50, 90, 99, 100)}


def cpu_during_training(folder, trial):
    with (folder / trial['phase'] / 'monitor.jsonl').open(encoding='utf-8') as stream:
        samples = [json.loads(line) for line in stream]
    first = next(s for s in samples if s['wall_seconds'] >= trial['loading_setup_and_initial_save_seconds'])
    last = samples[-1]
    cpu = last['cpu_seconds'] - first['cpu_seconds']
    a, b = first['system_cpu_times'], last['system_cpu_times']
    busy = sum(b[k] - a[k] for k in ('kernel_seconds_including_idle', 'user_seconds')) - (
        b['idle_seconds'] - a['idle_seconds'])
    return {'solver_cpu_seconds_sampled': cpu,
            'other_mean_logical_cpus': (busy - cpu) / (last['wall_seconds'] - first['wall_seconds'])}


def summarize(stage, tree, hrc, manifest):
    folder = CACHE / stage
    benchmark = read(folder / 'report.json')
    assert benchmark['status'] == 'completed' and benchmark['inputs_unchanged']
    trials = {trial['variant']: trial for trial in benchmark['trials']}
    probe, baseline = trials['probe'], trials['baseline']
    for trial in (probe, baseline):
        summary = trial['summary']
        assert summary['training_threads'] == 20 and summary['sampling_path'] == [0]
        assert summary['sampling_root_node_id'] == 1 and summary['scope_effective_samples'] == benchmark['samples']
        assert summary['terminal_tables'] and summary['unlocked_strategy_reads'] and summary['ci'] is None
    assert benchmark['cases']['probe']['sha256'] == manifest['executable_sha256']
    assert benchmark['cases']['baseline']['sha256'] == manifest['baseline_executable_sha256']
    index = {item['id']: item for item in read(CASE / 'formal/index.json')['nodes']}
    raw = folder / probe['phase'] / 'lock-probe.bin'
    by_node, delays, workers, sha = decode(raw, index)
    total = Counter()
    streets, formats = defaultdict(Counter), defaultdict(Counter)
    for node, stats in by_node.items():
        item = index[node]
        assert item['buckets'] == tree['nodes'][node]['buckets']
        total.update(stats)
        streets[STREETS[item['street']]].update(stats)
        formats[str(item['format'])].update(stats)
    assert total['conflicts'] == sum(len(values) for values in delays.values())
    highest_delays = sorted((value for values in delays.values() for value in values), reverse=True)

    def top(order):
        ids = sorted(by_node, key=lambda node: (-by_node[node][order], node))[:20]
        rows = []
        for node in ids:
            stats = by_node[node]
            if not stats[order]:
                break
            row = describe(tree, hrc, node)
            row.update(format=index[node]['format'], buckets=index[node]['buckets'], counters=dict(stats),
                       conflict_pct=percent(stats['conflicts'], stats['attempts']),
                       share_of_all_wait_pct=percent(stats['wait_ns'], total['wait_ns']))
            rows.append(row)
        return rows

    hottest = top('ww_different')
    hot_three = hottest[:3]
    hot_conflicts = sum(row['counters']['conflicts'] for row in hot_three)
    hot_separated = sum(row['counters']['stripes_8_separate'] for row in hot_three)
    return {
        'source_samples': benchmark['source_samples'], 'additional_samples': benchmark['samples'],
        'probe_compute_seconds': probe['compute_seconds'], 'baseline_compute_seconds': baseline['compute_seconds'],
        'compute_delta_pct': percent(probe['compute_seconds'] - baseline['compute_seconds'], baseline['compute_seconds']),
        'cpu': {name: cpu_during_training(folder, trial) for name, trial in trials.items()},
        'workers': workers, 'sample_interval': 512, 'sampled_nodes': len(by_node), 'counters': dict(total),
        'conflict_pct': percent(total['conflicts'], total['attempts']),
        'ww_different_pct_of_all_conflicts': percent(total['ww_different'], total['conflicts']),
        'ww_different_pct_of_ww': percent(total['ww_different'], total['ww_different'] + total['ww_same']),
        'ww_different_pct_of_wait': percent(total['ww_different_wait_ns'], total['wait_ns']),
        'stripe_pair_separation_pct_of_all_conflicts': {
            str(n): percent(total[f'stripes_{n}_separate'], total['conflicts']) for n in STRIPES},
        'three_hottest_nodes': {
            'ids': [row['node'] for row in hot_three],
            'pct_of_all_conflicts': percent(hot_conflicts, total['conflicts']),
            'eight_stripe_pair_separation_pct_of_all_conflicts': percent(hot_separated, total['conflicts']),
        },
        'by_street': dict(streets), 'by_format': dict(formats),
        'wait_distributions': {kind: distribution(values) for kind, values in delays.items()},
        'ten_longest_waits_pct_of_all_wait': percent(sum(highest_delays[:10]), total['wait_ns']),
        'top_by_wait': top('wait_ns'), 'top_by_different_bucket_write_conflicts': hottest,
        'raw': str(raw.relative_to(ROOT)), 'raw_sha256': sha,
        'benchmark': str((folder / 'report.json').relative_to(ROOT)),
    }


def main():
    tree = read(CASE / 'input/tree.json')
    inspector = runpy.run_path(str(ROOT / 'scripts/inspect-hrc-save.py'))
    hrc, _ = inspector['parse_tree']((CASE / 'gametree.dat').read_bytes())
    assert len(hrc) == len(tree['nodes']) and tree['big_blind'] == 300000
    manifest = read(CACHE / 'probe/manifest.json')
    report = {
        'workload': 'Hand bubble MTT ICM, EP decision after UTG folds, 20 workers',
        'probe_build': manifest,
        'stages': {stage: summarize(stage, tree, hrc, manifest) for stage in ('early', 'mature')},
        'measurement_boundaries': [
            'One randomized lock request per worker per 512 requests. Lock-free strategy reads are excluded.',
            'Contested means the first CAS observed a held lock. The holder tag describes that exact CAS; '
            'the timed wait may include later holders, spinning or scheduler delay.',
            'The diagnostic executable replaces the exchange with a tagged CAS and adds sampling/timing overhead.',
            'Cross-bucket pairs and stripe separation count opportunities under the observed first owner only. '
            'They do not establish removal of shared counters, lack of cache-line sharing or speedup.',
        ],
    }
    dest = ROOT / 'reports/hrc-mtt-node-contention-20261109.json'
    dest.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    for stage, result in report['stages'].items():
        print(stage, {key: result[key] for key in ('source_samples', 'counters', 'compute_delta_pct',
              'conflict_pct', 'ww_different_pct_of_ww', 'ww_different_pct_of_wait')})
        for row in result['top_by_wait'][:8]:
            print(row)
    print(dest)


if __name__ == '__main__':
    main()
