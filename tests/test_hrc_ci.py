from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import runpy

import pytest

from preflop_lab.hrc_policy import CITracker, CIRecord

ROOT = Path(__file__).resolve().parents[1]
HELPERS = runpy.run_path(str(ROOT / 'tests/test_hrc_policy.py'))


def ci_fixtures():
    cases = []
    rng = random.Random(771)
    for nodes in (1, 2, 4):
        initial = [(100., [.5, .5, .5, .5]) for _ in range(nodes)]
        count = [100.] * nodes
        steps, now, samples = [], 0, 100
        for i in range(70):
            # Irregular spacing avoids coinciding exactly with the 75% cutoff,
            # where a real millisecond of wall-clock jitter changes retention.
            now += (2000000 if i in (30, 31, 32, 33) else 20000) + rng.randint(71, 937)
            samples += rng.randint(1000, 5000)
            policies = []
            for n in range(nodes):
                count[n] += 0 if i == 7 or n == 1 and i % 3 == 0 else rng.randint(100, 1000)
                x, y = rng.random(), rng.random()
                policies.append([x, 1-x, y, 1-y])
            steps.append([now, samples, 0, list(count), policies, 0])
        # New worker restarts CI snapshot/history, preserving store contents.
        now += 20000
        steps.append([now, samples, 0, list(count), policies, 1])
        now += 20000
        count = [x + 100 for x in count]
        steps.append([now, samples+1000, 0, count, [[.25, .75, .1, .9] for _ in count], 0])
        cases.append({'id': f'ci_{nodes}', 'initial': initial, 'steps': steps})
    return cases


def ci_line(c):
    csv = HELPERS['csv']
    return '\t'.join(['C', c['id'], csv([s[0] for s in c['initial']]), '/'.join(csv(s[1]) for s in c['initial']),
                      '|'.join(';'.join(map(str, [now, samples, duration, csv(counts), '/'.join(csv(p) for p in policies), restart]))
                               for now, samples, duration, counts, policies, restart in c['steps'])])


def expected(c):
    tracker = CITracker(c['initial'])
    out = []
    for now, samples, duration, counts, policies, restart in c['steps']:
        snapshots = list(zip(counts, policies))
        if restart:
            tracker.restart(snapshots, now)
        accepted = tracker.update(now, samples, snapshots, duration)
        out.append({'accepted': accepted, 'ci': tracker.ci, 'speed': tracker.speed_per_ms*1000,
                    'interval': tracker.interval, 'last_time': tracker.last_time,
                    'history': [[r.ordinal, r.timestamp, r.samples, r.ci] for r in tracker.history],
                    'progress': [tracker.progress(t, tracker.first_record) for t in (1, 5, 50, 500)]})
    return {'id': c['id'], 'snapshots': out}


def test_native_ci_matches_reference_with_window_and_restarts():
    cases = ci_fixtures()
    for actual, case in zip(HELPERS['run_lines']([ci_line(c) for c in cases]), cases):
        HELPERS['close'](actual, expected(case))


def test_ci_uses_sqrt_visits_and_unweighted_bucket_tv():
    tracker = CITracker([(0, [.5,.5]), (0, [.5,.5,.5,.5])])
    assert not tracker.update(14999, 1, [])
    assert tracker.update(15000, 100, [(100, [1,0]), (400, [1,0,1,0])])
    assert tracker.ci == pytest.approx(math.sqrt(((10*.5+20*1)/30)*2/500*1e8))
    assert tracker.speed_per_ms == 0


def test_ci_progress_and_no_progress_poll():
    tracker = CITracker([(0, [.5,.5])])
    tracker.update(15000, 100, [(100, [1,0])])
    first = tracker.history[0]
    assert tracker.progress(tracker.ci, first) == 1
    assert tracker.progress(tracker.ci/2, first) == 0
    assert tracker.progress(1, None) == 0
    old_ci = tracker.ci
    tracker.update(30000, 100, [(100, [.4,.6])])
    assert len(tracker.history) == 1 and tracker.ci == old_ci
    tracker.update(45000, 200, [(200, [.4,.6])])
    assert tracker.ci == 0


def test_ci_slow_poll_interval_and_reset_validation():
    tracker = CITracker([(100, [.5,.5])])
    tracker.update(15000, 1000, [(200, [1,0])], duration=1000)
    assert tracker.interval == 50000 and tracker.last_time == 16000
    assert not tracker.update(65000, 2000, [(300, [0,1])])
    with pytest.raises(ValueError, match='restart'):
        tracker.update(66000, 2000, [(1, [0,1])])
    tracker.restart([(1, [0,1])], 66000)
    assert math.isnan(tracker.ci) and not tracker.history


def test_retained_original_ci_validation():
    path = ROOT/'reports/hrc-original-ci-validation.json'
    if not path.exists():
        pytest.skip('Run original CI validation to produce evidence')
    report = json.loads(path.read_text())
    assert report['passed'] and report['snapshots'] >= 216
    assert report['header_sha256'] == hashlib.sha256((ROOT/'native/hrc_ci.hpp').read_bytes()).hexdigest()
