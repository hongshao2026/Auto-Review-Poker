from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import subprocess

import pytest

from preflop_lab.hrc_policy import BucketLocks, FrequencyStore

ROOT = Path(__file__).resolve().parents[1]


def build_probe():
    sources = [ROOT / p for p in ('scripts/native/policy_probe.cpp', 'native/hrc_policy.hpp', 'native/hrc_ci.hpp')]
    digest = hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest()
    directory = ROOT / 'analysis/hrc-native/policy-build'
    directory.mkdir(parents=True, exist_ok=True)
    exe, stamp = directory / 'policy_probe.exe', directory / 'build.sha256'
    if not exe.exists() or not stamp.exists() or stamp.read_text() != digest:
        zig = Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
        result = subprocess.run([str(zig), 'c++', '-O3', '-std=c++17', '-ffp-contract=off', str(sources[0]), '-o', str(exe)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        stamp.write_text(digest)
    return exe


def csv(values):
    return ','.join('NaN' if math.isnan(x) else str(x) for x in values) or '-'


def run_lines(lines):
    result = subprocess.run([str(build_probe())], input='\n'.join(lines)+'\n', text=True, capture_output=True, check=True)
    return [json.loads(line) for line in result.stdout.splitlines()]


def close(actual, expected, tolerance=1e-11):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for k in expected:
            close(actual[k], expected[k], tolerance)
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected):
            close(a, e, tolerance)
    elif isinstance(expected, (int, float)):
        if math.isnan(expected):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(expected, rel=tolerance, abs=tolerance)
    else:
        assert actual == expected


def lock_fixtures():
    rng = random.Random(71205)
    cases = []
    for k in (2, 3, 4, 7, 16):
        for variant in range(24):
            h = 3
            flags = rng.sample(range(k), 1 + variant % k)
            rows = [None] * k
            weights = [[rng.random() for _ in flags] for _ in range(h)]
            for a in flags:
                rows[a] = [w[flags.index(a)] / sum(w) * (1. if variant % 5 == 0 else .7) for w in weights]
            if variant % 6 == 0:
                rows[flags[0]] = [0.] * h
            r = [[rng.uniform(-10, 10) for _ in range(k)] for _ in range(h)]
            av = [[rng.randint(0, 10) for _ in range(k)] for _ in range(h)]
            if variant % 8 == 0:
                r = [[-1.] * k for _ in range(h)]
                av = [[0.] * k for _ in range(h)]
            special = variant % 3 == 0
            # Original special-fold path overwrites locked action0 inconsistently;
            # test that exceptional path separately, keep numeric fixtures valid.
            if rows[0] is not None:
                special = False
            edits = []
            if variant % 4 == 0:
                edits.append((rng.randrange(k), [rng.uniform(-.3, 1.3) for _ in range(h)]))
                if edits[-1][0] == 0:
                    special = False
            case = {'id': f'locks_{k}_{variant}', 'k': k, 'h': h, 'rows': rows, 'r': r, 'a': av, 'special': special, 'edits': edits}
            cases.append(case)
    cases.append({'id': 'toggle_capture_unlock', 'k': 3, 'h': 2, 'rows': [[.2,.4], None, None],
                  'r': [[1,2,3],[2,3,4]], 'a': [[1,2,3],[3,2,1]], 'special': False, 'edits': [(1,'+'),(0,'-')]})
    return cases


def lock_line(c):
    return '\t'.join(['L', c['id'], str(c['k']), str(c['h']), csv(sum(c['r'], [])), csv(sum(c['a'], [])),
                      '/'.join(csv(r or []) for r in c['rows']), ';'.join(f'{a}:{v if isinstance(v,str) else csv(v)}' for a, v in c['edits']) or '-', str(int(c['special']))])


def lock_expected(c):
    locks = BucketLocks(c['k'], c['h'], c['rows'])
    for a, values in c['edits']:
        if values == '-':
            locks.unlock(a)
        elif values == '+':
            locks.lock_current(a, [locks.compose(c['a'][b], b)[a] for b in range(c['h'])])
        else:
            locks.edit(a, values)
    return {'id': c['id'], 'display': [locks.compose(c['a'][b], b) for b in range(c['h'])],
            'training': [locks.compose(c['r'][b], b, True, c['special']) for b in range(c['h'])], 'rows': [r or [] for r in locks.rows]}


def frequency_fixtures():
    rng = random.Random(170123)
    cases = []
    for k in (2, 3, 7):
        for variant in range(8):
            targets = [math.nan if (a + variant) % 3 == 0 else .7 / k for a in range(k)]
            edges = [rng.uniform(-2, 2) for _ in range(k)]
            steps = []
            for i in range(35):
                p = [rng.random() for _ in range(k)]
                p = [v / sum(p) for v in p]
                q = [rng.uniform(-10, -1 if variant == 0 else 20) for _ in range(k)]
                steps.append([i % 3, 0 if i == 5 else rng.choice([.1, .5, 1, 3]), rng.choice([0, .25, 1]),
                              0 if variant % 2 else (-1 if variant % 3 else 1), p, q, i % 11 == 10,
                              i == 25 and variant & 1, i == 25 and variant & 2])
            cases.append({'id': f'frequency_{k}_{variant}', 'k': k, 'h': 3, 'targets': targets, 'edges': edges, 'steps': steps})
    return cases


def frequency_line(c):
    return '\t'.join(['F', c['id'], str(c['h']), str(c['k']), csv(c['targets']), csv(c['edges']),
                      '|'.join(';'.join(map(str, [b, w, z, rng, csv(p), csv(q), int(bool(flush)), int(bool(rr)), int(bool(ra))])) for b, w, z, rng, p, q, flush, rr, ra in c['steps'])])


def frequency_snapshot(s):
    return {'raw': s.raw[:], 'edges': s.edges[:], 'edge_sums': s.edge_sums[:], 'shared_sums': s.shared_sums[:],
            'updates': s.updates, 'minimum': s.minimum, 'maximum': s.maximum,
            'strategy': [s.strategy(b) for b in range(s.buckets)], 'special': [s.strategy(b, True) for b in range(s.buckets)],
            'display': [s.display(b) for b in range(s.buckets)], 'ev': [s.relative_ev(b) for b in range(s.buckets)]}


def frequency_expected(c):
    s = FrequencyStore(c['h'], c['k'], c['targets'], c['edges'])
    out = [frequency_snapshot(s)]
    for b, w, z, rng, p, q, flush, rr, ra in c['steps']:
        s.update(b, p, q, w, z, lambda x: rng % math.floor(math.sqrt(x)) == 0)
        if flush:
            s.flush()
        if rr or ra:
            s.reset(rr, ra)
        out.append(frequency_snapshot(s))
    return {'id': c['id'], 'snapshots': out}


def test_native_locks_match_reference():
    cases = lock_fixtures()
    for actual, case in zip(run_lines([lock_line(c) for c in cases]), cases):
        close(actual, lock_expected(case))


def test_native_frequency_matches_reference():
    cases = frequency_fixtures()
    for actual, case in zip(run_lines([frequency_line(c) for c in cases]), cases):
        close(actual, frequency_expected(case))


def test_lock_shift_and_multi_lock_best_response_are_distinct():
    single = BucketLocks(3, 1, [[.4], None, None])
    # Shift makes both unlocked regrets nonpositive; original chooses FIRST,
    # rather than maximum, on zero residual positive mass.
    assert single.compose([-9, -2, 2], 0, True) == [0.4, 0.6, 0.]
    assert single.compose([-3, -2, 4], 0, True) == [0.4, 0., 0.6]
    assert single.compose([0, 2, 2], 0, False) == [.4, .3, .3]
    multi = BucketLocks(4, 1, [[.1], [.2], None, None])
    assert multi.compose([10, 3, 1, 2], 0, True) == pytest.approx([.1, .2, 0, .7])


def test_lock_edit_clamps_and_scales_other_locks():
    lock = BucketLocks(3, 2, [[.4, .2], [.3, .3], None])
    lock.edit(2, [.8, 2])
    assert [r[0] for r in lock.rows] == pytest.approx([.4 * .2 / .7, .3 * .2 / .7, .8])
    assert [r[1] for r in lock.rows] == [0., 0., 1.]
    lock.unlock(1)
    assert lock.count == 2


def test_special_virtual_fold_lock_exposes_original_invalid_mass():
    lock = BucketLocks(4, 1, [[.3], None, None, None])
    with pytest.raises(RuntimeError, match='sum'):
        lock.compose([1, 2, 3, 4], 0, True, True)
    full = BucketLocks(2, 1, [[.2], [.8]])
    assert math.isnan(full.compose([1, 1], 0, True, True)[0])


def test_frequency_updates_have_unweighted_regret_and_weighted_average():
    s = FrequencyStore(1, 2, [.25, None])
    s.update(0, [.5, .5], [4, 0], 1, 1)
    s.update(0, [1, 0], [0, 8], 2, 0)
    r = s.offset(0)
    assert s.raw[r:r+5] == [2., 14., 3., 2.5, .5]
    assert s.shared_sums == [.5, .5]
    assert s.updates == 2


def test_native_toggle_captures_composed_display():
    line = 'L\ttoggle\t3\t2\t1,2,3,2,3,4\t1,2,3,3,2,1\t0.2,0.4/-/-\t1:+;0:-\t0'
    actual = run_lines([line])[0]
    locks = BucketLocks(3, 2, [[.2, .4], None, None])
    averages = [[1,2,3],[3,2,1]]
    locks.lock_current(1, [locks.compose(averages[b], b)[1] for b in range(2)])
    locks.unlock(0)
    assert actual['rows'][1] == pytest.approx([.32,.4])
    close(actual['display'], [locks.compose(averages[b], b) for b in range(2)])


@pytest.mark.parametrize('call', [lambda: BucketLocks(2, 1, [[.8], [.8]]), lambda: BucketLocks(2, 1, [[math.nan], None]),
                                  lambda: FrequencyStore(1, 2, [1, .1]), lambda: FrequencyStore(1, 2, [.2, None], [0, math.inf])])
def test_bad_configuration_rejected(call):
    with pytest.raises(ValueError):
        call()


def test_retained_original_policy_validation():
    path = ROOT / 'reports/hrc-original-policy-validation.json'
    if not path.exists():
        pytest.skip('Run original policy validation to produce retained evidence')
    report = json.loads(path.read_text())
    assert report['passed']
    assert report['lock_cases'] >= 120 and report['frequency_snapshots'] >= 864
    assert report['header_sha256'] == hashlib.sha256((ROOT / 'native/hrc_policy.hpp').read_bytes()).hexdigest()
