from collections import Counter
import math
import random

import pytest

from preflop_lab.hrc_chance import (
    ChanceCancelled, ChanceResourceLimit, ChanceSampler,
    cumulative_probabilities, validated_ranges,
)
from preflop_lab.hrc_dynamic import COMBOS

FLOP = (1 << 40) | (1 << 44) | (1 << 48)
BOARD = (0, FLOP, FLOP | (1 << 50), FLOP | (1 << 50) | (1 << 51))


def weights(**items):
    result = [0.] * 1326
    for combo, value in items.items():
        result[int(combo)] = value
    return result


def test_enumerated_joint_law_is_product_conditioned_on_no_overlap():
    # Player0 A=(0,1),B=(2,3); player1 C=(0,4),D=(4,5).
    # Only (A,C) overlaps. Accepted product masses are4,6,12, not the
    # sequential-conditioner's .25,.25,.50 marginal allocation.
    sampler = ChanceSampler([weights(**{'0':1,'5':3}), weights(**{'6':2,'14':4})],
                            BOARD, max_attempts=1)
    counts, rejected = Counter(), 0
    for i in range(4):
        for j in range(6):
            values = iter(((i+.5)/4, (j+.5)/6))
            try:
                deal = sampler.sample_callbacks(lambda bound: pytest.fail('No uniform draw expected'), lambda: next(values))
                counts[deal.combos] += 1
            except ChanceResourceLimit:
                rejected += 1
    assert rejected == 2
    assert counts == {(0,14):4, (5,6):6, (5,14):12}


def test_collision_redraws_earlier_weighted_seat():
    values = iter((.1, .1, .9, .9))
    sampler = ChanceSampler([weights(**{'0':1,'5':1}), weights(**{'1':1,'14':1})], BOARD)
    result = sampler.sample_callbacks(lambda bound: 0, lambda: next(values))
    assert result.combos == (5,14)
    assert result.attempts == 2 and result.random_calls == 4


def test_folded_seat_remains_a_dead_card_seat():
    # Seat0 has folded before this subtree, but remains an actual dealt seat.
    integers = iter((0, 5))
    sampler = ChanceSampler([weights(**{'0':1}), None], BOARD)
    deal = sampler.sample_callbacks(lambda bound: next(integers), lambda: .5)
    assert deal.combos == (0,5)
    assert deal.random_calls == 3  # uniform seat rejected the folded hole cards
    assert deal.used_mask.bit_count() == 9


@pytest.mark.parametrize('prefix_length', [1,2,3,4])
def test_complete_board_preserves_history_and_all_card_disjointness(prefix_length):
    sampler = ChanceSampler([None, [1.]*1326, None, [1.]*1326], BOARD[:prefix_length])
    for seed in range(20):
        deal = sampler.sample(random.Random(seed))
        assert deal.board_history[:prefix_length] == BOARD[:prefix_length]
        assert [mask.bit_count() for mask in deal.board_history] == [0,3,4,5]
        used = deal.board_history[-1]
        for combo in deal.combos:
            assert not used & COMBOS[combo]
            used |= COMBOS[combo]
        assert used == deal.used_mask and used.bit_count() == 13


def test_cdf_inclusive_boundary_and_zero_endpoint_preserved():
    sampler = ChanceSampler([weights(**{'100':1})], BOARD)
    assert sampler.sample_callbacks(lambda bound: 0, lambda: 0.).combos == (0,)
    assert sampler.sample_callbacks(lambda bound: 0, lambda: math.nextafter(0,1)).combos == (100,)
    sampler = ChanceSampler([weights(**{'0':1,'5':1})], BOARD)
    assert sampler.sample_callbacks(lambda bound: 0, lambda: .5).combos == (0,)
    assert sampler.sample_callbacks(lambda bound: 0, lambda: math.nextafter(.5,1)).combos == (5,)


def test_joint_impossibility_and_cancellation_are_explicit():
    sampler = ChanceSampler([weights(**{'0':1})]*2, BOARD, max_attempts=4)
    with pytest.raises(ChanceResourceLimit, match='rejection-attempt'):
        sampler.sample_callbacks(lambda bound: 0, lambda: .5)
    with pytest.raises(ChanceCancelled):
        sampler.sample(random.Random(4), lambda: True)
    sampler = ChanceSampler([None], BOARD, max_random_calls=2)
    blocked = next(i for i, mask in enumerate(COMBOS) if mask & BOARD[-1])
    with pytest.raises(ChanceResourceLimit, match='random-call'):
        sampler.sample_callbacks(lambda bound: blocked, lambda: .5)


def test_board_blocking_scale_and_range_validation():
    blocked = next(i for i, mask in enumerate(COMBOS) if mask & FLOP)
    row = weights(**{'0':2, str(blocked):100})
    validated = validated_ranges([row, None], 2, FLOP)
    assert validated[0][0] == 2 and validated[0][blocked] == 0 and validated[1] is None
    for invalid in ([0.]*1326, [1.]*169, [-1.]*1326, [math.nan]*1326, [math.inf]*1326, [True]*1326, [1e308]*1326):
        with pytest.raises(ValueError):
            ChanceSampler([invalid], BOARD)
    with pytest.raises(ValueError, match='blockers'):
        ChanceSampler([weights(**{str(blocked):1})], BOARD)
    with pytest.raises(ValueError):
        validated_ranges([None], 2)
    assert cumulative_probabilities([1,3]) == (.25,1.)


def test_invalid_random_callbacks_and_uniform_target_primitive():
    sampler = ChanceSampler([weights(**{'0':1})], BOARD)
    for value in (-.1,1.,math.nan,True):
        with pytest.raises(ValueError):
            sampler.sample_callbacks(lambda bound: 5, lambda: value)
    deal = sampler.sample_callbacks(lambda bound: 5, lambda: pytest.fail('Target must be uniform'), skip_player=0)
    assert deal.combos == (5,)
    with pytest.raises(ValueError):
        sampler.sample_callbacks(lambda bound: -1, lambda: .5, skip_player=0)
