"""Independent sequential numeric reference for audited storage formats 25/27/31.

Used by the original-bytecode differential oracle and checkpoint integration.
It preserves cached counters, deferred shared sums and float32 roundtrips;
it does not model Java concurrent races or weak CAS spurious failures.
"""
from __future__ import annotations

import hashlib
import math
import struct


def _normalize(values, special=False):
    start = int(special)
    output = [0.0] * len(values)
    positive = [max(0.0, x) for x in values[start:]]
    total = sum(positive)
    if total > 0:
        output[start:] = [x / total for x in positive]
    elif not special:
        output = [1 / len(values)] * len(values)
    elif len(values) == 3 and values[1] == values[2]:
        output[1:] = [.5, .5]
    else:
        output[max(range(start, len(values)), key=values.__getitem__)] = 1.0
    return output


class ExtendedStore:
    def __init__(self, format, buckets, actions, data=None):
        if format not in (25, 27, 31) or type(buckets) is not int or buckets < 1 or type(actions) is not int or not 2 <= actions <= 100:
            raise ValueError("Unsupported store format or dimensions")
        self.format, self.h, self.k = format, buckets, actions
        self.width = actions if format == 25 else 2 * actions + int(format == 31)
        self.header = [0.0] * (actions + 1)
        self.rows = [[0.0] * self.width for _ in range(buckets)]
        self.counter = 0
        self.shared = [0.0] * actions
        if data is not None:
            self.restore(data)

    def _load_adders(self):
        self.counter = math.floor(self.header[0] + .5)
        if self.format == 31:
            self.shared = self.header[1:].copy()

    def flatten(self):
        return self.header + [x for row in self.rows for x in row]

    def restore(self, data):
        count = self.k + 1 + self.h * self.width
        if len(data) != 4 * count:
            raise ValueError("Serialized store length differs from dimensions")
        flat = list(struct.unpack(f"<{count}f", data))
        self.header = flat[:self.k + 1]
        self.rows = [flat[self.k + 1 + b * self.width:self.k + 1 + (b + 1) * self.width] for b in range(self.h)]
        self._load_adders()

    def flush(self):
        if self.format != 25:
            self.header[0] = float(self.counter)
        if self.format == 31:
            self.header[1:] = self.shared

    def serialize(self):
        self.flush()
        flat = self.flatten()
        return struct.pack(f"<{len(flat)}f", *flat)

    def set_count(self, count):
        self.header[0] = count
        self._load_adders()

    def update(self, bucket, weight, marker, rng_value, probabilities, utilities):
        if weight <= 0:
            return
        expected = sum(p * u for p, u in zip(probabilities, utilities) if p > 0)
        if self.format == 25:
            self.header[0] += 1
            multiplier = self.header[0]
            self.counter = math.floor(multiplier + .5)
        else:
            self.counter += 1
            multiplier = self.header[0] + 1
            if rng_value % math.floor(math.sqrt(multiplier)) == 0:
                multiplier = float(self.counter)
                self.header[0] = multiplier
        row = self.rows[bucket]
        weighted = weight * multiplier
        for a in range(self.k):
            row[a] += weighted * (utilities[a] - expected)
            if self.format != 25:
                row[self.k + int(self.format == 31) + a] += multiplier * probabilities[a]
        if self.format == 31:
            row[self.k] += weighted
        if marker > 0:
            marked = marker * multiplier
            for a in range(self.k):
                if self.format == 31:
                    self.shared[a] += marked * probabilities[a]
                else:
                    self.header[a + 1] += marked * probabilities[a]

    def discount_average(self, factor):
        self.header[1:] = [x * factor for x in self.header[1:]]
        if self.format != 25:
            for row in self.rows:
                start = self.k + int(self.format == 31)
                row[start:] = [x * factor for x in row[start:]]
        if self.format == 31:
            self._load_adders()  # Deliberately uses the possibly stale header.

    def reset(self, regret, average):
        if average:
            self.discount_average(1e-20)
        if regret:
            stop = self.k + int(self.format == 31)
            for row in self.rows:
                row[:stop] = [x * 1e-20 for x in row[:stop]]
            self.set_count(0.0)

    def shared_display(self):
        if self.format == 31:
            self.flush()
        return _normalize(self.header[1:])

    def converted_to_27(self):
        if self.format != 25:
            raise ValueError("Only 25 to 27 conversion is defined")
        target = ExtendedStore(27, self.h, self.k)
        target.header = self.header.copy()
        target._load_adders()
        target.rows = [row + _normalize(row) for row in self.rows]
        return target

    def snapshot(self, selected):
        rows = [self.rows[b].copy() for b in selected]
        training = [_normalize(row[:self.k]) for row in rows]
        special = [_normalize(row[:self.k], True) for row in rows]
        display = [_normalize(row[-self.k:]) for row in rows]
        ev = [None if self.format != 31 else
              [(row[a] - row[0]) / row[self.k] for a in range(self.k)] if row[self.k] > 0 else
              ["NaN"] * self.k for row in rows]
        flat = self.flatten()
        chunks = []
        if self.format == 31:
            capacity = 16384 - 16384 % self.width
            left = self.h * self.width
            chunks = [self.k + 1]
            while left:
                chunks.append(min(left, capacity))
                left -= chunks[-1]
        return dict(format=self.format, header=self.header.copy(), counter=self.counter,
                    shared_adders=self.shared.copy() if self.format == 31 else self.header[1:].copy(),
                    rows=rows, training=training, special=special, display=display, ev=ev, chunks=chunks,
                    raw_sha256=hashlib.sha256(struct.pack(f"<{len(flat)}d", *flat)).hexdigest())
