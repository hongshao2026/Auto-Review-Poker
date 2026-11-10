"""Compare isolated original bytecode and the unmodified native traversal.

Only explicit synthetic trees, buckets and payoff vectors enter either side.
The C++ harness includes the production source; it does not rewrite that source
or touch an active training executable. No HRC application or licensed service
is launched. The strict class allow-list is inherited from the prior probe.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/hrc-deep/nested-traversal'
JDK = Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
JAR = Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')
RNG = JAR.parent / 'net.holdemresources.calculator.mavendependencies_0.2.0/org.apache.commons/commons-rng-client-api-1.6.jar'
ZIG = Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
MASK = (1 << 64) - 1


def stream(seed):
    def rot(x, k):
        return ((x << k) | (x >> (64-k))) & MASK
    s = []
    for _ in range(4):
        seed = (seed + 0x9e3779b97f4a7c15) & MASK
        z = seed
        z = ((z ^ (z >> 30)) * 0xbf58476d1ce4e5b9) & MASK
        z = ((z ^ (z >> 27)) * 0x94d049bb133111eb) & MASK
        s.append(z ^ (z >> 31))
    while True:
        result, t = rot((s[1]*5) & MASK, 7)*9 & MASK, s[1] << 17 & MASK
        s[2] ^= s[0]
        s[3] ^= s[1]
        s[1] ^= s[2]
        s[0] ^= s[3]
        s[2] ^= t
        s[3] = rot(s[3], 45)
        yield result


def find_seed(predicate):
    for seed in range(1, 100_000):
        rng = stream(seed)
        if predicate([(next(rng) >> 11) * 2**-53 for _ in range(3)]):
            return seed
    raise AssertionError('seed not found')


def cases():
    special_seed = find_seed(lambda u: u[0] >= .01 and u[1] < .01)
    explore_seed = find_seed(lambda u: u[0] < .01)
    profiles = {}
    regular = [
        'NODE 0 0 0 0 1 2', 'NODE 1 1 0 0 3 4',
        'NODE 2 0 1 0 5 6', 'NODE 3 0 2 0 7 8',
        'NODE 4 1 3 0 9 10', 'NODE 5 1 2 0 11 12',
        'NODE 6 0 3 0 13 14',
    ] + [f'LEAF {i} {v} {-v}' for i, v in enumerate([3, -11, 7, 19, -5, 13, -17, 23], 7)]
    profiles['regular'] = regular
    profiles['other_actor'] = ['NODE 0 1 0 0 1 2', *regular[1:]]
    profiles['special2'] = ['NODE 0 0 1 2 1 2', 'NODE 1 1 1 0 3 4', *regular[2:]]
    profiles['special1'] = ['NODE 0 0 1 1 1 2', 'NODE 1 1 2 0 3 4',
                            'LEAF 2 17 -17', 'LEAF 3 9 -9', 'LEAF 4 -11 11']
    profiles['special3'] = ['NODE 0 0 1 2 1 2 3', 'NODE 1 1 2 0 4 5',
                            'NODE 2 0 2 0 6 7', 'NODE 3 0 3 0 8 9',
                            'LEAF 4 5 -5', 'LEAF 5 -13 13', 'LEAF 6 19 -19',
                            'LEAF 7 -7 7', 'LEAF 8 23 -23', 'LEAF 9 -11 11']
    invocations = [(-1, 0, 1), (0, 0, 0), (0, 0, 2.75), (1, 0, 1), (0, 2, 1)]
    fixtures = []
    for profile, tree in profiles.items():
        for mode in (3, 4):
            for target, depth, marker in invocations:
                for seed in dict.fromkeys((42, 43, special_seed, explore_seed)):
                    name = f'{profile}.v{mode}.target{target}.depth{depth}.marker{marker}.seed{seed}'
                    fixtures.append({'name': name, 'profile': profile, 'mode': mode,
                                     'target': target, 'depth': depth, 'marker': marker,
                                     'seed': seed, 'steps': 16, 'tree': tree})
    lines = ['# Synthetic nested traversal fixtures; never read from an HRC strategy archive.']
    for f in fixtures:
        lines.extend([f"CASE {f['name']} {f['seed']} {f['mode']} {f['target']} {f['depth']} {f['marker']} {f['steps']}",
                      *f['tree'], 'END'])
    return fixtures, '\n'.join(lines)+'\n', special_seed, explore_seed


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fixtures, contents, special_seed, explore_seed = cases()
    data = OUT / 'synthetic-cases.txt'
    data.write_text(contents, encoding='utf-8')
    sources = [ROOT / 'scripts/java/OriginalTraversalProbe.java',
               ROOT / 'scripts/java/OriginalNestedTraversalProbe.java',
               ROOT / 'scripts/native/nested_traversal_probe.cpp',
               ROOT / 'native/hrc_research_solver.cpp', ROOT / 'native/hrc_cards.hpp']
    original_native_hash = sha(sources[3])
    compiler = ZIG if ZIG.exists() else Path(r'D:\Tools\REA-Research\zig-x86_64-windows-0.15.2\zig.exe')
    executable = OUT / 'nested_native_probe.exe'
    commands = [
        [str(JDK / 'javac.exe'), '-d', str(OUT), *map(str, sources[:2])],
        [str(compiler), 'c++', '-O2', '-std=c++17', '-ffp-contract=off', str(sources[2]), '-o', str(executable)],
        [str(JDK / 'java.exe'), '-cp', str(OUT), 'OriginalNestedTraversalProbe', str(JAR), str(RNG), str(data)],
        [str(executable), str(data)],
    ]
    outputs = []
    for index, command in enumerate(commands):
        run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        (OUT / f'{index}-stdout.jsonl').write_text(run.stdout, encoding='utf-8')
        (OUT / f'{index}-stderr.txt').write_text(run.stderr, encoding='utf-8')
        if run.returncode:
            raise RuntimeError(f'Command {index} failed: {run.stderr[-6000:]}')
        outputs.append(run.stdout)
    original_records = [json.loads(line) for line in outputs[2].splitlines()]
    original = [r for r in original_records if r.get('kind') == 'nested_result']
    native = [json.loads(line) for line in outputs[3].splitlines()]
    expected = sum(f['steps'] for f in fixtures)
    if len(original) != expected or len(native) != expected:
        raise AssertionError(f'Record count mismatch: {len(original)}, {len(native)}, {expected}')
    comparisons = numeric_values = 0
    max_error = 0.0
    failures = []
    stale_counter_snapshots = 0
    bounds = set()
    specifications = {f['name']: f for f in fixtures}
    by_key = {}
    for a, b in zip(original, native):
        comparisons += 1
        key = (a['case'], a['step'])
        by_key[key] = (a, b)
        if key != (b['case'], b['step']) or a['rng_calls'] != b['rng_calls'] or len(a['value']) != len(b['value']):
            failures.append({'case': key, 'kind': 'identity_or_rng_calls'})
        bounds.update(a['bounded_arguments'])
        for x, y in zip(a['value'], b['value']):
            numeric_values += 1
            max_error = max(max_error, abs(x-y))
            if not (math.isfinite(x) and math.isfinite(y)) or abs(x-y) > 1e-10 + abs(x)*1e-13:
                failures.append({'case': key, 'kind': 'return', 'original': x, 'native': y})
        if len(a['nodes']) != len(b['nodes']):
            failures.append({'case': key, 'kind': 'node_count'})
        spec = specifications[a['case']]
        street = {int(line.split()[1]): int(line.split()[3]) for line in spec['tree'] if line.startswith('NODE')}
        for x, y in zip(a['nodes'], b['nodes']):
            if x['id'] != y['id'] or x['updates'] != y['updates'] or len(x['raw']) != len(y['raw']):
                failures.append({'case': key, 'kind': 'node_identity_updates_length', 'id': x['id']})
            if street[x['id']] == 0 and x['raw'][0] != x['updates']:
                stale_counter_snapshots += 1
            for i, (u, v) in enumerate(zip(x['raw'], y['raw'])):
                numeric_values += 1
                max_error = max(max_error, abs(u-v))
                if not (math.isfinite(u) and math.isfinite(v)) or abs(u-v) > 1e-10 + abs(u)*1e-13:
                    failures.append({'case': key, 'kind': 'raw', 'node': x['id'], 'index': i, 'original': u, 'native': v})
    coverage = {'cached_counter_stale_snapshots': stale_counter_snapshots,
                'predicate_and_exploration_bounds': sorted(bounds)}
    assert stale_counter_snapshots > 0 and {2, 3, 4}.issubset(bounds)
    for profile in ('special1', 'special2'):
        name = f'{profile}.v4.target-1.depth0.marker1.seed{special_seed}'
        original_first, native_first = by_key[(name, 1)]
        alternate = next(n for n in original_first['nodes'] if n['id'] == 1)
        expected_updates = 0 if profile == 'special1' else 1
        assert alternate['updates'] == expected_updates
        coverage[f'{profile}_one_percent_seed_first_alternate_updates'] = alternate['updates']
        coverage[f'{profile}_first_native_traversal_calls'] = native_first['traversal_calls']
    zero_marker_post = 0
    for a in original:
        f = specifications[a['case']]
        if f['target'] < 0 or f['marker'] != 0:
            continue
        for n in a['nodes']:
            line = next(line for line in f['tree'] if line.startswith(f"NODE {n['id']} "))
            parts = line.split()
            if int(parts[3]) > 0 and n['updates']:
                k = len(parts)-5
                assert all(x == 0 for x in n['raw'][1:1+k])
                zero_marker_post += 1
    coverage['postflop_updates_without_marker_preserve_zero_average'] = zero_marker_post
    assert zero_marker_post > 0 and sha(sources[3]) == original_native_hash
    assert not any(r.get('kind') == 'loaded_resource' for r in original_records)
    report = {'probe': 'nested-original-vs-current-native', 'passed': not failures,
              'fixture_cases': len(fixtures), 'snapshot_comparisons': comparisons,
              'numeric_values_compared': numeric_values, 'max_abs_error': max_error,
              'failures': failures, 'coverage': coverage, 'commands': commands,
              'sources': {str(p.relative_to(ROOT)): sha(p) for p in sources},
              'jar_sha256': sha(JAR), 'rng_api_sha256': sha(RNG),
              'fixture_sha256': sha(data), 'native_executable_sha256': sha(executable),
              'special_branch_seed': special_seed, 'exploration_seed': explore_seed,
              'loaded_original_classes': [r for r in original_records if r.get('kind') == 'loaded_class'],
              'loaded_original_resources': [r for r in original_records if r.get('kind') == 'loaded_resource'],
              'scope': {'synthetic_leaf_vectors': True, 'synthetic_cached_buckets': True,
                        'synthetic_cached_ranks': True,
                        'context_weight': 1, 'native_source_unchanged': True,
                        'application_started': False, 'live_training_files_touched': False,
                        'not_tested': ['real card or abstraction mapping in this fixture',
                                       'multithreaded HRC ordering', 'GUI/CI counter refresh schedule',
                                       'nonunit context weights/range-restricted traversal',
                                       'equilibrium convergence or full product equivalence']}}
    report_path = ROOT / 'reports/hrc-original-nested-traversal-validation.json'
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'fixture_cases', 'snapshot_comparisons',
                                          'numeric_values_compared', 'max_abs_error', 'coverage')}, indent=2))
    if failures:
        print(json.dumps(failures[:10], indent=2))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
