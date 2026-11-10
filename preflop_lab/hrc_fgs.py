"""Independent finite future-game simulation for the audited threshold model.

Chance weights may be read from the user's local, hash-verified research input.
No saved strategies or utilities are used. The 169-threshold next-hand model
is separate from the full action-tree MCCFR model. See research/HRC-FGS.md.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import itertools
import math
from pathlib import Path
import struct
import time
import zipfile

import numpy as np

_RESULTS = {1: ((1,),), 2: ((1, 1), (1, 2), (2, 1)),
            3: ((1, 1, 1), (1, 1, 3), (1, 3, 1), (1, 2, 2),
                (1, 2, 3), (1, 3, 2), (2, 1, 2), (2, 2, 1),
                (2, 1, 3), (2, 3, 1), (3, 1, 1), (3, 1, 2), (3, 2, 1))}
_PERMUTATIONS = {}
for _n in (2, 3):
    for _permutation in itertools.permutations(range(_n)):
        _PERMUTATIONS[_permutation] = tuple(_RESULTS[_n].index(tuple(rank[j] for j in _permutation)) for rank in _RESULTS[_n])


def _f32(x):
    return float(np.float32(x))


def _hand_index(label):
    ranks = "23456789TJQKA"
    a, b = sorted((ranks.index(label[0]), ranks.index(label[1])), reverse=True)
    return 13 * a + b if a == b or label.endswith("s") else 13 * b + a


class ChanceTables:
    """Cumulative two/three-player threshold probabilities and showdown masses."""
    def __init__(self, marginal, two, three, provenance=None):
        self.marginal = np.asarray(marginal, dtype="<f8")
        self.two = np.asarray(two, dtype="<f8").reshape(14365, 4)
        self.three = np.asarray(three, dtype="<f8").reshape(818805, 14)
        self.provenance = provenance or {}
        if self.marginal.shape != (169,) or not np.isfinite(self.marginal).all():
            raise ValueError("Invalid FGS marginal table")
        if not np.isfinite(self.two).all() or not np.isfinite(self.three).all():
            raise ValueError("Invalid FGS cumulative chance table")

    @staticmethod
    def _entry(indices):
        order = tuple(sorted(range(len(indices)), key=lambda i: (-indices[i], i)))
        a, b, *c = [indices[i] for i in order]
        index = a * (a + 1) // 2 + b if not c else a * (a + 1) * (a + 2) // 6 + b * (b + 1) // 2 + c[0]
        return index, _PERMUTATIONS[order]

    def mass(self, indices):
        if len(indices) == 1:
            return float(self.marginal[indices[0]])
        index, _ = self._entry(indices)
        return float((self.two if len(indices) == 2 else self.three)[index, -1])

    def expected(self, indices, utilities):
        index, permutation = self._entry(indices)
        row = (self.two if len(indices) == 2 else self.three)[index]
        value = 0.0
        for j, p in enumerate(permutation):
            value += float(row[p]) * utilities[j]
        return value / float(row[-1]) if row[-1] else math.nan

    def write(self, path):
        """Write a derived research cache; never package this user's data as source."""
        with Path(path).open("wb") as stream:
            stream.write(b"FGSCHN01")
            stream.write(self.marginal.tobytes())
            stream.write(self.two.tobytes())
            stream.write(self.three.tobytes())

    @classmethod
    def read(cls, path):
        with Path(path).open("rb") as stream:
            if stream.read(8) != b"FGSCHN01":
                raise ValueError("Unrecognized FGS chance cache")
            values = np.frombuffer(stream.read(), dtype="<f8")
        if len(values) != 169 + 14365 * 4 + 818805 * 14:
            raise ValueError("Truncated or trailing FGS chance cache")
        return cls(values[:169], values[169:169 + 14365 * 4], values[169 + 14365 * 4:])

    @classmethod
    def from_installation(cls, plugins):
        plugins = Path(plugins)
        members = [
            ("net.holdemresources.calculator_4.1.0.202603231401.jar", "net/holdemresources/sngnash/data/handranking/necombined.range", "871775a8393968ac6be770835c1cce744aae91723c3181e1c7fdf5d53ceb52cc"),
            ("net.holdemresources.preflopdata.holdem_1.4.1.jar", "net/holdemresources/handevaluation/preflop/hands/data/2wh.dat", "f329b9633decff877074b6dc5ff924c437e4a632cf168b35d789441fe65fc151"),
            ("net.holdemresources.preflopdata.holdem_1.4.1.jar", "net/holdemresources/handevaluation/preflop/hands/data/3wh.dat", "949cf28d7c78ad63063c33f372b8af121bd316d55e41662ebeaca02ddee2915d"),
        ]
        buffers, provenance = [], []
        for jar, member, digest in members:
            with zipfile.ZipFile(plugins / jar) as archive:
                data = archive.read(member)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"Unreviewed FGS resource: {member}")
            buffers.append(data)
            provenance.append(dict(jar=str(plugins / jar), member=member, sha256=digest, bytes=len(data)))
        labels = buffers[0].decode("ascii").splitlines()
        if len(labels) != 169 or len(set(labels)) != 169:
            raise ValueError("Invalid 169-hand ordering")
        order = np.array([_hand_index(label) for label in labels], dtype=np.int64)
        if sorted(order) != list(range(169)):
            raise ValueError("Nonpermutation hand ordering")
        raw2 = np.frombuffer(buffers[1], dtype="<f8").reshape(14365, 3)
        raw3 = np.frombuffer(buffers[2], dtype="<f8").reshape(818805, 13)
        counts = [6 if len(label) == 2 else 4 if label.endswith("s") else 12 for label in labels]
        marginal = np.cumsum(np.asarray(counts, dtype=np.float32) / np.float32(1326), dtype=np.float64)
        two = np.empty((14365, 4))
        previous2 = np.zeros((169, 3))
        for i, first in enumerate(order):
            current2 = np.empty((169, 3))
            for j, second in enumerate(order):
                index, permutation = cls._entry((int(first), int(second)))
                current2[j] = raw2[index, list(permutation)]
            np.cumsum(current2, axis=0, out=current2)
            if i:
                current2 += previous2
            begin = i * (i + 1) // 2
            two[begin:begin + i + 1, :3] = current2[:i + 1]
            two[begin:begin + i + 1, 3] = np.add.accumulate(current2[:i + 1], axis=1)[:, -1]
            previous2 = current2
        three = np.empty((818805, 14))
        previous3 = np.zeros((169, 169, 13))
        permutation_arrays = {p: np.asarray(v) for p, v in _PERMUTATIONS.items() if len(p) == 3}
        for i, first in enumerate(order):
            current3 = np.empty((169, 169, 13))
            for j, second in enumerate(order):
                hands = np.column_stack((np.full(169, first), np.full(169, second), order))
                permutations = np.argsort(-hands, axis=1, kind="stable")
                sorted_hands = np.take_along_axis(hands, permutations, axis=1)
                a, b, c = sorted_hands.T
                rows = raw3[a * (a + 1) * (a + 2) // 6 + b * (b + 1) // 2 + c]
                mapped = np.empty_like(rows)
                for p, permutation in permutation_arrays.items():
                    selected = np.all(permutations == p, axis=1)
                    mapped[selected] = rows[selected][:, permutation]
                mapped[np.isnan(mapped)] = 0
                np.cumsum(mapped, axis=0, out=mapped)
                if i:
                    mapped += previous3[j]
                if j:
                    mapped += current3[j - 1]
                if i and j:
                    mapped -= previous3[j - 1]
                current3[j] = mapped
                if j <= i:
                    begin = i * (i + 1) * (i + 2) // 6 + j * (j + 1) // 2
                    three[begin:begin + j + 1, :13] = mapped[:j + 1]
                    three[begin:begin + j + 1, 13] = np.add.accumulate(mapped[:j + 1], axis=1)[:, -1]
            previous3 = current3
        return cls(marginal, two, three, {"resources": provenance, "hand_order": labels})


class ThresholdSolver:
    """Simultaneous smoothed best replies in the original restricted next hand."""
    def __init__(self, tables, utilities, remaining, posted, checkpoint=None):
        self.tables = tables
        self.utilities = utilities  # participant tuple -> [player][showdown result]
        self.n = len(remaining)
        self.thresholds = {key: (50 if len(key) == 1 else 20 if len(key) == 2 else 5)
                           for count in (1, 2, 3) for key in itertools.combinations(range(self.n), count)}
        self.thresholds[(self.n - 1,)] = 168
        self.locked = set()
        small, big = self.n - 2, self.n - 1
        def lock(key, threshold):
            self.thresholds[key] = threshold
            self.locked.add(key)
        if remaining[small] == 0:
            for push in range(small):
                lock((push, small), 168)
                for call in range(push + 1, small):
                    lock((push, call, small), 168)
                    for over in range(call + 1, small):
                        lock((push, call, over), 0)
        for push in range(big):
            if remaining[big] > 0 and posted[push] + remaining[push] > posted[big]:
                continue
            lock((push, big), 168)
            for call in range(push + 1, big):
                if remaining[big] > 0 and posted[call] + remaining[call] > posted[big]:
                    continue
                lock((push, call, big), 168)
                if remaining[big] == 0:
                    for over in range(call + 1, big):
                        lock((push, call, over), 0)
        if remaining[small] == remaining[big] == 0:
            for push in range(small - 1):
                for call in range(push + 1, small):
                    lock((push, call), 0)
        self.smoothed = {k: float(v) for k, v in self.thresholds.items()}
        self.smoothing_mass = 1.0
        self.iteration = 0
        self.checkpoint = checkpoint

    def _threshold_path(self, participants):
        return tuple(self.thresholds[participants[:i]] for i in range(1, len(participants) + 1))

    def _showdown(self, player, participants):
        if len(participants) == 1:
            return self.utilities[participants][player][0]
        return self.tables.expected(self._threshold_path(participants), self.utilities[participants][player])

    def value(self, player, participants=(), next_player=0, folded_continuation=None):
        if len(participants) == 3:
            return self._showdown(player, participants)
        if next_player >= self.n or (not participants and next_player == self.n - 1):
            return self._showdown(player, participants or (self.n - 1,))
        child = participants + (next_player,)
        numerator = self.tables.mass(self._threshold_path(child))
        denominator = self.tables.mass(self._threshold_path(participants)) if participants else 1.0
        chance = numerator / denominator if denominator else math.nan
        folded = folded_continuation
        if folded is None:
            folded = self.value(player, participants, next_player + 1)
        if not chance > 0:
            return folded
        active = self.value(player, child, next_player + 1)
        return active * chance + folded * (1.0 - chance)

    def sweep(self):
        if self.checkpoint:
            self.checkpoint()
        self.smoothing_mass = _f32(self.smoothing_mass + _f32(0.11) * math.log(self.iteration + 10))
        weight = _f32(1.0 / self.smoothing_mass)
        complement = _f32(1.0 - weight)
        for count, minimum in ((1, 14), (2, 8), (3, 3)):
            width = max(169 // (1 + self.iteration), minimum)
            for key in itertools.combinations(range(self.n), count):
                if count == 1 and key[0] == self.n - 1:
                    continue
                original = best = self.thresholds[key]
                if key not in self.locked:
                    player, previous = key[-1], key[:-1]
                    fallback = self.value(player, previous, player + 1)
                    maximum = float(np.nextafter(np.float32(0), np.float32(1)))
                    candidate = original
                    while candidate >= max((original if count == 3 else best) - width, 0):
                        self.thresholds[key] = candidate
                        value = self.value(player, previous, player, fallback)
                        if value > maximum:
                            maximum, best = value, candidate
                        candidate -= 1
                    candidate = original + 1
                    while candidate < min((original if count == 3 else best) + width, 169):
                        self.thresholds[key] = candidate
                        value = self.value(player, previous, player, fallback)
                        if value > maximum:
                            maximum, best = value, candidate
                        candidate += 1
                    self.thresholds[key] = original
                    if count == 1:
                        best = max(best, 1)
                self.smoothed[key] = _f32(_f32(best * weight) + _f32(self.smoothed[key] * complement))
        for key, value in self.smoothed.items():
            self.thresholds[key] = math.floor(value + 0.5)
        self.iteration += 1

    def solve(self, iterations):
        for _ in range(iterations):
            self.sweep()
        return [self.value(player) for player in range(self.n)]


@dataclass(frozen=True)
class Context:
    stacks: tuple[int, ...]
    bounties: tuple[float, ...] = ()
    depth: int = 0
    skip_sb: bool = False


@dataclass(frozen=True)
class Config:
    payouts: tuple[float, ...]
    big_blind: int
    small_blind: int
    ante: int = 0
    ante_type: str = "REGULAR"  # REGULAR, BB_ANTE_FIRST, BB_BLIND_FIRST
    straddle: str = "OFF"  # OFF, SINGLE, DOUBLE, BUTTON
    moving_button: bool = False
    depth: int = 1
    depth3way: int = 1
    next_level_at: int | None = None
    next_level: tuple[int, int, int] | None = None
    bounty_mode: str = "NONE"  # NONE, FIXED, PROGRESSIVE
    immediate_fraction: float = 1.0
    cache_capacity: int = 5000
    max_states: int = 20000
    max_sweeps: int = 2000000
    max_seconds: float = 60.0
    terminal_cache_capacity: int = 65536


@dataclass(frozen=True)
class Outcome:
    stacks: tuple[int, ...]
    winner_masks: tuple[int, ...]
    participants: int
    tied_award: bool


class FgsResourceLimit(RuntimeError):
    """No partial equity is returned as a completed FGS result."""


def forced_state(context: Context, config: Config):
    n = len(context.stacks)
    if not 2 <= n <= 10:
        raise ValueError("FGS forced bets require 2..10 players")
    remaining, posted, dead = list(context.stacks), [0] * n, [0] * n
    big, small, ante = config.big_blind, config.small_blind, config.ante
    if config.next_level_at is not None and context.depth >= config.next_level_at:
        big, small, ante = config.next_level
    pool = 0
    def pay(player, amount, destination):
        paid = min(remaining[player], amount)
        remaining[player] -= paid
        destination[player] += paid
    if config.ante_type == "REGULAR":
        for i in range(n):
            pay(i, ante, dead)
    elif config.ante_type == "BB_ANTE_FIRST":
        pool = min(remaining[-1], ante)
        remaining[-1] -= pool
    if not context.skip_sb:
        pay(n - 2, small, posted)
    pay(n - 1, big, posted)
    if config.ante_type == "BB_BLIND_FIRST":
        pool = min(remaining[-1], ante)
        remaining[-1] -= pool
    if config.straddle in ("SINGLE", "DOUBLE"):
        pay(0, max(2 * big - posted[0], 0), posted)
        if config.straddle == "DOUBLE":
            pay(1, max(4 * big - posted[1], 0), posted)
    elif config.straddle == "BUTTON":
        button = 0 if n == 2 else n - (2 if context.skip_sb else 3)
        pay(button, max(2 * big - posted[button], 0), posted)
    return remaining, posted, dead, pool


def allin_outcome(context: Context, config: Config, participants, ranks):
    """Settle a future-hand participant subset, including forced dead money."""
    remaining, posted, antes, pool = forced_state(context, config)
    n = len(remaining)
    participants = tuple(participants)
    strengths = dict(zip(participants, ranks))  # lower numerical rank wins
    if not 1 <= len(participants) <= 3 or len(strengths) != len(participants):
        raise ValueError("FGS outcome requires 1..3 unique participants")
    contributions = [posted[i] + antes[i] for i in range(n)]
    for i in participants:
        contributions[i] += remaining[i]
        remaining[i] = 0
    # Relevant winner caps ascend within a tied hand rank; equal caps award
    # integer remainders to the largest original seat index.
    ordered = sorted(participants, key=lambda i: (strengths[i], contributions[i], -i))
    final, masks, covered, tied = remaining[:], [0] * n, 0, False
    for position, first in enumerate(ordered):
        cap = contributions[first]
        if position and cap <= covered:
            continue
        winners = []
        for i in ordered[position:]:
            if strengths[i] != strengths[first]:
                break
            winners.append(i)
        tied |= len(winners) > 1
        pot = pool if position == 0 else 0
        mask = sum(1 << i for i in winners)
        for i, amount in enumerate(contributions):
            if position and amount <= covered:
                continue
            pot += min(amount - covered, cap - covered)
            if remaining[i] == 0 and amount <= cap and (i not in strengths or strengths[i] > strengths[first]):
                masks[i] = mask
        share, remainder = divmod(pot, len(winners))
        for i in winners:
            final[i] += share
        final[first] += remainder
        covered = cap
    for i, contribution in enumerate(contributions):
        final[i] += max(contribution - covered, 0)
        if final[i]:
            masks[i] = 0
    if sum(final) != sum(context.stacks) or any(s < 0 for s in final):
        raise ArithmeticError("FGS terminal failed chip conservation")
    return Outcome(tuple(final), tuple(masks), len(participants), tied)


def _icm(stacks, prizes):
    n = len(stacks)
    values = [0.0] * n
    states = {0: 1.0}
    for prize in prizes[:n]:
        next_states = {}
        for mask, reach in states.items():
            alive = [i for i in range(n) if not mask & (1 << i)]
            total = sum(stacks[i] for i in alive)
            for i in alive:
                chance = reach * stacks[i] / total
                values[i] += prize * chance
                next_mask = mask | (1 << i)
                next_states[next_mask] = next_states.get(next_mask, 0.0) + chance
        states = next_states
    return values


def ordinary_terminal(context: Context, config: Config, outcome: Outcome):
    alive = [i for i, s in enumerate(outcome.stacks) if s]
    dead = sorted((i for i, s in enumerate(outcome.stacks) if not s), key=lambda i: -context.stacks[i])
    immediate, heads = [0.0] * len(context.stacks), [0.0] * len(context.stacks)
    offset = 0
    while offset < len(dead):
        end = offset + 1
        while end < len(dead) and context.stacks[dead[end]] == context.stacks[dead[offset]]:
            end += 1
        share = sum(config.payouts[len(alive) + offset:len(alive) + end]) / (end - offset)
        for i in dead[offset:end]:
            immediate[i] += share
        offset = end
    if config.bounty_mode != "NONE":
        for i in alive:
            heads[i] = context.bounties[i]
        alpha = config.immediate_fraction if config.bounty_mode == "PROGRESSIVE" else 1.0
        for victim in dead:
            winners = [i for i in alive if outcome.winner_masks[victim] & (1 << i)]
            if not winners:
                raise ValueError("Eliminated bounty player has no winning opponent")
            share = context.bounties[victim] / len(winners)
            for i in winners:
                immediate[i] += alpha * share
                if config.bounty_mode == "PROGRESSIVE":
                    heads[i] += (1 - alpha) * share
    future = _icm([outcome.stacks[i] for i in alive], config.payouts)
    total_chips, pool = sum(outcome.stacks), sum(heads)
    values = immediate[:]
    for i, equity in zip(alive, future):
        values[i] += equity + pool * outcome.stacks[i] / total_chips
    return values, immediate, tuple(heads)


def next_context(context: Context, outcome: Outcome, config: Config, heads=()):
    alive = [i for i, s in enumerate(outcome.stacks) if s]
    n = len(outcome.stacks)
    skip = context.skip_sb if n < 2 else False
    if n > 1:
        rotations = 1
        if config.moving_button and n > 2:
            rotations += sum(outcome.stacks[i] == 0 for i in (n - 2, n - 1))
            if len(alive) == 2:
                rotations += 1
        else:
            skip = outcome.stacks[-1] == 0 and len(alive) > 2
        rotations %= len(alive)
        alive = alive[rotations:] + alive[:rotations]
    next_heads = tuple(heads[i] for i in alive) if config.bounty_mode != "NONE" else ()
    child = Context(tuple(outcome.stacks[i] for i in alive), next_heads, context.depth + 1, skip)
    return child, tuple(alive)


class Calculator:
    def __init__(self, config: Config, tables: ChanceTables):
        if not 0 <= config.depth <= 10 or not 0 <= config.depth3way <= 10:
            raise ValueError("FGS depths must be between 0 and 10")
        if config.big_blind <= 0 or config.small_blind < 0 or config.ante < 0:
            raise ValueError("Invalid FGS blind amounts")
        if config.ante_type not in ("REGULAR", "BB_ANTE_FIRST", "BB_BLIND_FIRST") or config.straddle not in ("OFF", "SINGLE", "DOUBLE", "BUTTON"):
            raise ValueError("Unsupported FGS forced bet rule")
        if not config.payouts or any(not math.isfinite(p) or p < 0 for p in config.payouts) or any(a < b for a, b in zip(config.payouts, config.payouts[1:])):
            raise ValueError("Invalid FGS payouts")
        if config.bounty_mode not in ("NONE", "FIXED", "PROGRESSIVE") or not 0 <= config.immediate_fraction <= 1:
            raise ValueError("Invalid FGS bounty configuration")
        if (config.next_level_at is None) != (config.next_level is None):
            raise ValueError("Future blind schedule requires both depth and amounts")
        if config.next_level is not None and (len(config.next_level) != 3 or config.next_level[0] <= 0 or min(config.next_level) < 0 or config.next_level_at < 0):
            raise ValueError("Invalid future blind level")
        if config.cache_capacity < 0 or min(config.max_states, config.max_sweeps, config.max_seconds) <= 0:
            raise ValueError("FGS resource budgets must be positive")
        self.config, self.tables = config, tables
        self.caches = [OrderedDict() for _ in range(config.depth + 1)]
        self.terminals = OrderedDict()
        self._active_calls = 0
        self.reset_budget()

    def reset_budget(self):
        if self._active_calls:
            raise RuntimeError("Cannot reset an active FGS budget")
        self.stats = {"states": 0, "sweeps": 0, "cache_hits": 0, "terminal_calls": 0, "terminal_cache_hits": 0}
        self._work_seconds = 0.0
        self._work_started = 0.0

    @contextmanager
    def _work_scope(self):
        if self._active_calls == 0:
            self._work_started = time.monotonic()
        self._active_calls += 1
        try:
            yield
        finally:
            self._active_calls -= 1
            if self._active_calls == 0:
                self._work_seconds += time.monotonic() - self._work_started

    @property
    def work_seconds(self):
        return self._work_seconds + (time.monotonic() - self._work_started if self._active_calls else 0.0)

    def _checkpoint(self, sweep=False):
        if sweep:
            self.stats["sweeps"] += 1
        if self.stats["states"] > self.config.max_states or self.stats["sweeps"] > self.config.max_sweeps or self.work_seconds > self.config.max_seconds:
            raise FgsResourceLimit("FGS resource budget exhausted; result is incomplete")

    def _validate_context(self, context):
        if not 1 <= len(context.stacks) <= 10 or any(type(s) is not int or s <= 0 for s in context.stacks):
            raise ValueError("FGS requires 1..10 positive integer stacks")
        if context.depth < 0:
            raise ValueError("FGS context depth cannot be negative")
        if self.config.bounty_mode != "NONE":
            if len(context.bounties) != len(context.stacks) or any(not math.isfinite(b) or b < 0 for b in context.bounties):
                raise ValueError("FGS requires one nonnegative bounty per survivor")
            if self.config.bounty_mode == "FIXED" and any(b != context.bounties[0] for b in context.bounties):
                raise ValueError("Fixed KO requires equal bounties")

    def terminal(self, context: Context, outcome: Outcome):
        self._validate_context(context)
        if len(outcome.stacks) != len(context.stacks) or len(outcome.winner_masks) != len(context.stacks) or not 1 <= outcome.participants <= len(context.stacks):
            raise ValueError("Invalid FGS outcome dimensions")
        if any(type(s) is not int or s < 0 for s in outcome.stacks) or sum(outcome.stacks) != sum(context.stacks):
            raise ValueError("Invalid FGS terminal chip total")
        key = (context, outcome)
        if key in self.terminals:
            self.stats["terminal_cache_hits"] += 1
            self.terminals.move_to_end(key)
            return list(self.terminals[key])
        with self._work_scope():
            values = self._terminal(context, outcome)
        if self.config.terminal_cache_capacity:
            self.terminals[key] = tuple(values)
            if len(self.terminals) > self.config.terminal_cache_capacity:
                self.terminals.popitem(last=False)
        return values

    def _terminal(self, context: Context, outcome: Outcome):
        self.stats["terminal_calls"] += 1
        self._checkpoint()
        values, immediate, heads = ordinary_terminal(context, self.config, outcome)
        if context.depth < self.config.depth and not outcome.tied_award and (context.depth < self.config.depth3way or outcome.participants < 3):
            child, mapping = next_context(context, outcome, self.config, heads)
            continuation = self.equities(child)
            values = immediate
            for original, value in zip(mapping, continuation):
                values[original] += value
        return values

    def equities(self, context: Context):
        self._validate_context(context)
        if len(context.stacks) == 1:
            return ordinary_terminal(context, self.config, Outcome(context.stacks, (0,) * len(context.stacks), 1, False))[0]
        if context.depth > self.config.depth:
            with self._work_scope():
                self._checkpoint()
                return ordinary_terminal(context, self.config, Outcome(context.stacks, (0,) * len(context.stacks), 1, False))[0]
        cache = self.caches[context.depth]
        if context in cache:
            self.stats["cache_hits"] += 1
            cache.move_to_end(context)
            return list(cache[context])
        with self._work_scope():
            return self._equities(context, cache)

    def _equities(self, context, cache):
        self.stats["states"] += 1
        self._checkpoint()
        n = len(context.stacks)
        utilities = {}
        for count in (1, 2, 3):
            for participants in itertools.combinations(range(n), count):
                columns = [self.terminal(context, allin_outcome(context, self.config, participants, ranks)) for ranks in _RESULTS[count]]
                utilities[participants] = [list(row) for row in zip(*columns)]
        remaining, posted, _, _ = forced_state(context, self.config)
        solver = ThresholdSolver(self.tables, utilities, remaining, posted, lambda: self._checkpoint(True))
        values = solver.solve(200 if context.depth <= 1 else 50)
        tolerance = max(sum(abs(x) for x in values) * 1e-7, 1e-10)
        values = [0.0 if -tolerance <= x < 0 else x for x in values]
        if any(not math.isfinite(x) or x < 0 for x in values):
            raise ArithmeticError("Invalid FGS equity estimate")
        if self.config.cache_capacity:
            cache[context] = tuple(values)
            if len(cache) > self.config.cache_capacity:
                cache.popitem(last=False)
        return values
