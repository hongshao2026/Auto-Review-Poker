"""Independent reference math for HRC bucket locks, frequency store and drift CI.

Mirrors audited my/mx/mz/mq numeric semantics. This module never loads HRC.
Native training uses the matching headers. NaN frequency targets mean unconstrained;
API JSON should encode them as null and convert at this boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


def _finite(values):
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in values)


def _normalize(values):
    result = [max(0., x) for x in values]
    total = sum(result)
    return [x / total for x in result] if total > 0 else [1 / len(values)] * len(values)


class BucketLocks:
    def __init__(self, actions, buckets, rows=None):
        if type(actions) is not int or not 2 <= actions <= 16 or type(buckets) is not int or buckets < 1:
            raise ValueError("Invalid lock dimensions")
        self.actions, self.buckets = actions, buckets
        self.rows = [None] * actions if rows is None else [None if r is None or len(r) == 0 else list(r) for r in rows]
        if len(self.rows) != actions or any(r is not None and (len(r) != buckets or not _finite(r) or any(not 0 <= p <= 1 for p in r)) for r in self.rows):
            raise ValueError("Lock probabilities must match dimensions and be finite in [0,1]")
        if any(sum(r[b] for r in self.rows if r is not None) > 1 + 1e-12 for b in range(buckets)):
            raise ValueError("Locked probabilities exceed one")

    @property
    def count(self):
        return sum(r is not None for r in self.rows)

    def compose(self, base, bucket, training=False, special=False):
        if len(base) != self.actions or not 0 <= bucket < self.buckets:
            raise ValueError("Lock dimensions mismatch")
        n, k = self.count, self.actions
        locked = [r is not None for r in self.rows]
        values = [r[bucket] if r is not None else math.nan for r in self.rows]
        mass = sum(v for v, flag in zip(values, locked) if flag)
        if training and special:
            values[0] = math.nan if n + 1 >= k else 0.
        if n == k:
            return values
        if mass >= 1:
            return [v if flag else 0. for v, flag in zip(values, locked)]
        if n == k - 1:
            return [v if flag else 1 - mass for v, flag in zip(values, locked)]
        threshold = 0.
        if training and 0 < mass < 1:
            if sum(flag and v > 0 for flag, v in zip(locked, values)) > 1:
                best = max((a for a in range(k) if not locked[a]), key=lambda a: base[a])
                return [v if flag else (1 - mass if a == best else 0.) for a, (v, flag) in enumerate(zip(values, locked))]
            threshold = -sum(base[a] * values[a] / (1 - values[a]) for a in range(k) if locked[a] and values[a] < 1)
        positive = [0. if flag else max(0., base[a] - threshold) for a, flag in enumerate(locked)]
        total = sum(positive)
        first = locked.index(False)
        result = [values[a] if locked[a] else ((1 - mass) * positive[a] / total if total else (1 - mass if a == first else 0.)) for a in range(k)]
        if total and abs(sum(result) - 1) >= 1e-12:
            raise RuntimeError("Unexpected locked strategy sum")
        return result

    def edit(self, action, values):
        if not 0 <= action < self.actions or len(values) != self.buckets or not _finite(values):
            raise ValueError("Invalid lock edit")
        self.rows[action] = [min(1., max(0., v)) for v in values]
        for b in range(self.buckets):
            total = sum(row[b] for row in self.rows if row is not None)
            if total > 1:
                scale = (1 - self.rows[action][b]) / (total - self.rows[action][b])
                for a, row in enumerate(self.rows):
                    if a != action and row is not None:
                        row[b] *= scale
        return self

    def unlock(self, action):
        if not 0 <= action < self.actions:
            raise ValueError("Invalid lock action")
        self.rows[action] = None

    def lock_current(self, action, display):
        if not 0 <= action < self.actions or len(display) != self.buckets or not _finite(display) or any(not 0 <= p <= 1 for p in display):
            raise ValueError("Invalid current lock probabilities")
        if self.rows[action] is None:
            self.rows[action] = list(display)


class FrequencyStore:
    def __init__(self, buckets, actions, targets=None, edges=None, underlying_format=23):
        if type(actions) is not int or not 2 <= actions <= 16 or type(buckets) is not int or buckets < 1:
            raise ValueError("Invalid frequency dimensions")
        self.buckets, self.actions, self.underlying_format = buckets, actions, underlying_format
        self.targets = [math.nan if x is None else float(x) for x in (targets if targets is not None else [None] * actions)]
        self.edges = list(edges) if edges is not None else [0.] * actions
        if len(self.targets) != actions or len(self.edges) != actions or not _finite(self.edges):
            raise ValueError("Invalid frequency dimensions or edges")
        if any(not math.isnan(t) and not 0 <= t <= 1 for t in self.targets) or sum(t for t in self.targets if not math.isnan(t)) > 1 + 1e-12:
            raise ValueError("Invalid frequency targets")
        self.raw = [0.] * (1 + actions + buckets * (2 * actions + 1))
        self.edge_sums = self.edges[:]
        self.shared_sums = [0.] * actions
        self.updates = 0
        self.minimum, self.maximum = float.fromhex('0x1.fffffep127'), 2.**-149

    def offset(self, b):
        if not 0 <= b < self.buckets:
            raise ValueError("Invalid frequency bucket")
        return 1 + self.actions + b * (2 * self.actions + 1)

    def relative_ev(self, b):
        r, k = self.offset(b), self.actions
        d = self.raw[r + k]
        return [(self.raw[r + a] - self.raw[r]) / d for a in range(k)] if d > 0 else [math.nan] * k

    def strategy(self, b, special=False):
        ev = self.relative_ev(b)
        best = int(special)
        for a in range(best, self.actions):
            ev[a] += self.edges[a]
            if ev[best] < ev[a]:
                best = a
        return [float(a == best) for a in range(self.actions)]

    def display(self, b):
        start = self.offset(b) + self.actions + 1
        return _normalize(self.raw[start:start + self.actions])

    def flush(self):
        self.raw[0] = float(self.updates)
        self.raw[1:1 + self.actions] = self.shared_sums
        self.edges[:] = self.edge_sums

    def sync_from_raw(self):
        self.updates = math.floor(self.raw[0] + .5)
        self.shared_sums[:] = self.raw[1:1 + self.actions]
        self.edge_sums[:] = self.edges

    def aggregate(self):
        self.flush()
        return _normalize(self.raw[1:1 + self.actions])

    def update(self, b, p, q, w, z, refresh=lambda _: True):
        if len(p) != self.actions or len(q) != self.actions or not _finite([w, z, *p, *q]):
            raise ValueError("Invalid frequency update")
        if w <= 0:
            return
        r, k = self.offset(b), self.actions
        value = sum(p[a] * q[a] for a in range(k) if p[a] > 0)
        self.updates += 1
        t = self.raw[0] + 1
        if refresh(t):
            self.raw[0] = t = float(self.updates)
        for a in range(k):
            self.raw[r + a] += w * (q[a] - value)
            self.raw[r + k + 1 + a] += t * p[a]
        self.raw[r + k] += w
        if z > 0:
            cache = refresh(math.sqrt(t))
            step = z / t**(1 / math.sqrt(2))
            self.minimum = min(self.minimum, *q)
            self.maximum = max(self.maximum, *q)
            span = max(self.maximum - self.minimum, 0.)
            for a in range(k):
                if not math.isnan(self.targets[a]):
                    self.edge_sums[a] += span * step * (self.targets[a] - p[a])
                    if cache:
                        self.edges[a] = self.edge_sums[a]
                self.shared_sums[a] += z * t * p[a]

    def reset(self, regret, average):
        k = self.actions
        if regret:
            self.minimum, self.maximum = float.fromhex('0x1.fffffep127'), 2.**-149
            self.edges[:] = [0. if not math.isnan(t) else e for t, e in zip(self.targets, self.edges)]
        if average:
            for a in range(k):
                self.raw[1 + a] *= 1e-20
            for b in range(self.buckets):
                for a in range(k):
                    self.raw[self.offset(b) + k + 1 + a] *= 1e-20
            self.sync_from_raw()
        if regret:
            for b in range(self.buckets):
                for a in range(k + 1):
                    self.raw[self.offset(b) + a] *= 1e-20
            self.raw[0] = 0.
            self.sync_from_raw()


@dataclass
class CIRecord:
    ordinal: int
    timestamp: int
    samples: int
    ci: float


class CITracker:
    """mq recent-policy-drift statistic; snapshots=[(count, flat_probabilities)]."""
    def __init__(self, snapshots=(), now=0):
        self.restart(snapshots, now)

    def restart(self, snapshots, now):
        self.previous = [(float(n), list(p)) for n, p in snapshots]
        if any(not math.isfinite(n) or n < 0 for n, _ in self.previous):
            raise ValueError("Invalid CI count")
        self.total = sum(n for n, _ in self.previous)
        self.history, self.first_time = [], None
        self.first_record = None
        self.ci, self.speed_per_ms = math.nan, 0.
        self.last_time, self.interval = now, 15000

    def update(self, now, samples, snapshots, duration=0):
        if now - self.last_time < self.interval:
            return False
        if len(snapshots) != len(self.previous) or duration < 0:
            raise ValueError("Invalid CI dimensions/time")
        total = numerator = denominator = 0.
        for (count, policy), (old_count, old_policy) in zip(snapshots, self.previous):
            if not math.isfinite(count) or count < old_count or len(policy) != len(old_policy) or not _finite(policy):
                raise ValueError("Invalid CI snapshot; restart after count reset")
            weight = math.sqrt(count - old_count)
            distance = sum(abs(a - b) for a, b in zip(policy, old_policy)) / 2
            total += count
            numerator += weight * distance
            denominator += weight
        self.previous = [(float(n), list(p)) for n, p in snapshots]
        if total - self.total > 0:
            raw = math.sqrt(numerator / denominator * len(snapshots) / (total - self.total) * 1e8)
            if self.first_time is None:
                self.ci, ordinal, self.first_time = raw, 0, now
            else:
                alpha = min(self.history[-1].ordinal * .05, .75)
                self.ci = alpha * self.ci + (1 - alpha) * raw
                self.speed_per_ms = (samples - self.history[-1].samples) / (now - self.last_time)
                ordinal = self.history[-1].ordinal + 1
            self.history.append(CIRecord(ordinal, now, samples, self.ci))
            if self.first_record is None:
                self.first_record = self.history[-1]
            cutoff = now - int(min((now - self.first_time) * .75, 7200000.))
            while len(self.history) > 3 and self.history[0].timestamp < cutoff:
                self.history.pop(0)
        self.total, self.interval, self.last_time = total, max(15000, duration * 50), now + duration
        return True

    def progress(self, target, reference):
        if reference is None or reference.ci < self.ci:
            return 0.
        if self.ci <= target:
            return 1.
        return max(0., 1 - (target**-1.7 - self.ci**-1.7) / (target**-1.7 - reference.ci**-1.7))
