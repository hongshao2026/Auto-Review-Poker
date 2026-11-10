"""Independent fixed-board HRC mode-1 chance model.

Weighted seats are independently drawn, then the WHOLE weighted assignment is
rejected on overlap. Uniform seats (including folded/dead-card seats) follow.
No original strategy, terminal utility or resource table is used here.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import math

from .hrc_dynamic import COMBOS, DECK_MASK, validate_history


class ChanceResourceLimit(RuntimeError):
    pass


class ChanceCancelled(RuntimeError):
    pass


def validated_ranges(ranges, players=None, board_mask=0):
    """Return blocked, unscaled 1326-combo weights; None means uniform.

    Keeping input scale avoids changing CDF rounding. All actual seats must be
    included, even if they have folded. Active flags belong to bucket mapping,
    never to this deal model.
    """
    if not isinstance(ranges, (list, tuple)) or not 1 <= len(ranges) <= 10:
        raise ValueError('Expected ranges for 1..10 actual seats')
    if players is not None and (type(players) is not int or len(ranges) != players):
        raise ValueError('Range count differs from player count')
    if type(board_mask) is not int or not 0 <= board_mask <= DECK_MASK:
        raise ValueError('Invalid board mask')
    result = []
    for row in ranges:
        if row is None:
            result.append(None)
            continue
        if len(row) != 1326:
            raise ValueError('Each range requires 1326 combo weights')
        weights = []
        total = 0.0
        for weight, mask in zip(row, COMBOS):
            if isinstance(weight, bool):
                raise ValueError('Range weights must be finite and nonnegative')
            weight = float(weight)
            if not math.isfinite(weight) or weight < 0:
                raise ValueError('Range weights must be finite and nonnegative')
            weight = 0.0 if mask & board_mask else weight
            weights.append(weight)
            total += weight
        if not math.isfinite(total) or total <= 0:
            raise ValueError('Range has no positive finite mass after board blockers')
        result.append(tuple(weights))
    return tuple(result)


def cumulative_probabilities(weights):
    """Sequential summation and inclusive CDF boundary match the dependency.

    Original GuideTableDiscreteSampler chooses the first CDF >= u, including
    u=0: with a zero leading weight this can return combo 0. We preserve that
    discrete-RNG endpoint instead of claiming strict positive support there.
    """
    cumulative, total = [], 0.0
    for weight in weights:
        total += weight
        cumulative.append(total)
    if not math.isfinite(total) or total <= 0:
        raise ValueError('Invalid total range weight')
    cumulative = [min(value / total, 1.0) for value in cumulative]
    cumulative[-1] = 1.0
    return tuple(cumulative)


@dataclass(frozen=True)
class Deal:
    combos: tuple[int, ...]
    board_history: tuple[int, int, int, int]
    used_mask: int
    attempts: int
    random_calls: int


class ChanceSampler:
    def __init__(self, ranges, board_history=(0,), *, max_attempts=1_000_000,
                 max_random_calls=10_000_000):
        prefix = tuple(board_history)
        if prefix != (0,):
            prefix = validate_history(prefix)
        if type(max_attempts) is not int or max_attempts <= 0:
            raise ValueError('max_attempts must be a positive integer')
        if type(max_random_calls) is not int or max_random_calls <= 0:
            raise ValueError('max_random_calls must be a positive integer')
        self.prefix = prefix
        self.ranges = validated_ranges(ranges, board_mask=prefix[-1])
        self.cdf = tuple(None if r is None else cumulative_probabilities(r) for r in self.ranges)
        self.max_attempts = max_attempts
        self.max_random_calls = max_random_calls

    def sample(self, rng, cancel_check=None, *, skip_player=-1):
        """rng exposes randrange(bound) and random(); no shared PRNG assumed.

        skip_player reproduces lw's optional uniform target draw only. It does
        NOT implement mn mode-2 traversal's reach weighting or training logic.
        """
        return self.sample_callbacks(rng.randrange, rng.random, cancel_check,
                                     skip_player=skip_player)

    def sample_callbacks(self, next_int, next_double, cancel_check=None, *, skip_player=-1):
        if type(skip_player) is not int or not -1 <= skip_player < len(self.ranges):
            raise ValueError('Invalid skipped player')
        calls = 0

        def check():
            if cancel_check and cancel_check():
                raise ChanceCancelled('Chance sampling cancelled')
            if calls >= self.max_random_calls:
                raise ChanceResourceLimit('Chance random-call budget exhausted')

        def integer(bound):
            nonlocal calls
            check()
            value = next_int(bound)
            calls += 1
            if type(value) is not int or not 0 <= value < bound:
                raise ValueError('Integer random callback returned an invalid value')
            return value

        def real():
            nonlocal calls
            check()
            value = next_double()
            calls += 1
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 1:
                raise ValueError('Real random callback must return a finite value in [0,1)')
            return value

        combos = [-1] * len(self.ranges)
        for attempt in range(1, self.max_attempts + 1):
            check()
            used = self.prefix[-1]
            for player, cdf in enumerate(self.cdf):
                if cdf is None or player == skip_player:
                    continue
                combo = bisect_left(cdf, real())
                mask = COMBOS[combo]
                if mask & used:
                    break
                combos[player] = combo
                used |= mask
            else:
                break
        else:
            raise ChanceResourceLimit('Joint range rejection-attempt budget exhausted')

        for player, cdf in enumerate(self.cdf):
            if cdf is None or player == skip_player:
                while True:
                    combo = integer(1326)
                    mask = COMBOS[combo]
                    if not mask & used:
                        combos[player] = combo
                        used |= mask
                        break
        board = list(self.prefix)
        for street in range(len(board), 4):
            mask = board[-1]
            for _ in range(3 if street == 1 else 1):
                while True:
                    card = 1 << integer(52)
                    if not card & used:
                        used |= card
                        mask |= card
                        break
            board.append(mask)
        return Deal(tuple(combos), tuple(board), used, attempt, calls)
