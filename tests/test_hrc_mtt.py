"""Independent MTT numerical invariants and original-bytecode regressions.

The ordinary suite does not require Java or an HRC installation. The separate
validate-hrc-mtt.py command performs the bounded original/native comparison.
"""
import math

import pytest

from preflop_lab.mtt_equity import Calculator, mtt_icm_equities, _qng


def finish_order(stacks, prizes):
    result = [0.0] * len(stacks)
    def visit(remaining, rank, reach):
        if rank >= min(len(prizes), len(stacks)):
            return
        total = math.fsum(stacks[i] for i in remaining)
        for i in remaining:
            next_reach = reach * stacks[i] / total
            result[i] += prizes[rank] * next_reach
            visit([j for j in remaining if j != i], rank + 1, next_reach)
    visit(list(range(len(stacks))), 0, 1.0)
    return result


@pytest.mark.parametrize("outside", [0, 1, 8, 99, 100, 1000])
def test_first_two_places_are_exact_at_any_field_size(outside):
    table = [20.0, 35.0, 90.0]
    other = [10.0 + i % 31 for i in range(outside)]
    field = table + other
    total = sum(field)
    # Independently sum all first/second finisher events, with no numerical integral.
    expected = [0.0] * len(table)
    for first in range(len(field)):
        probability = field[first] / total
        if first < len(table):
            expected[first] += 1000 * probability
        for second in range(len(table)):
            if second != first:
                expected[second] += 500 * probability * field[second] / sum(field[i] for i in range(len(field)) if i != first)
    assert mtt_icm_equities(table, [1000, 500], other) == pytest.approx(expected, abs=1e-10)


def test_finite_quadrature_tracks_finish_order_on_regular_stacks():
    table, outside, prizes = [20, 30, 50], [10, 15], [100, 50, 20]
    actual = mtt_icm_equities(table, prizes, outside)
    # QNG stops at 87 points even when its requested 1e-10 tolerance is unmet.
    assert actual == pytest.approx(finish_order(table + outside, prizes)[:3], abs=1e-6)


def test_one_survivor_keeps_full_prize_schedule():
    assert mtt_icm_equities([10], [100, 50, 20]) == [100]


def test_old_prize_schedule_does_not_change_exact_rank_range():
    assert mtt_icm_equities([2, 4, 9], [100] * 7) == mtt_icm_equities([2, 4, 9], [100] * 3)


def test_threshold_depends_on_outside_count_not_total_field():
    exact = Calculator([1000, 500, 200], [30] * 99)
    approximate = Calculator([1000, 500, 200], [30] * 100)
    assert not exact.approximate and approximate.approximate
    assert exact([30, 30]) == pytest.approx([1700 / 101] * 2, abs=1e-10)
    assert approximate([30]) == pytest.approx([16.83170414167392], abs=1e-10)


def test_large_field_original_approximation_not_renormalized():
    other = [10 + ((i * 47) % 89) for i in range(100)]
    assert mtt_icm_equities([20, 35, 90], [100] * 103, other) == pytest.approx(
        [99.85060005517461, 99.9826818098798, 100.0011198849433], abs=1e-10)


def test_original_large_field_full_old_prize_schedule():
    other = [10 + i % 79 for i in range(100)]
    assert mtt_icm_equities([20, 35], [100] * 120, other) == pytest.approx(
        [99.99995452348288, 100.00017326116732], abs=1e-10)


@pytest.mark.parametrize("scale", [1e-100, 7, 1e100])
def test_chip_units_do_not_change_equity(scale):
    table, outside = [20, 30, 50], [10, 15]
    expected = mtt_icm_equities(table, [100, 50, 20], outside)
    assert mtt_icm_equities([s * scale for s in table], [100, 50, 20], [s * scale for s in outside]) == pytest.approx(expected, abs=1e-10)


def test_player_order_and_prepared_reuse():
    prizes, outside, table = [1000, 500, 200], [20] * 100, [10, 30, 50]
    before = (prizes[:], outside[:], table[:])
    calculator = Calculator(prizes, outside)
    expected = calculator(table)
    result = calculator(list(reversed(table)))
    assert result == pytest.approx(list(reversed(expected)), abs=1e-9)
    assert calculator(table) == expected
    assert (prizes, outside, table) == before


def test_zero_prize_field():
    assert mtt_icm_equities([1, 2, 3], [0, 0, 0], [10] * 100) == [0, 0, 0]


@pytest.mark.parametrize("table,prizes,other", [
    ([], [100], []), ([0, 10], [100], []), ([-1, 10], [100], []),
    ([math.nan, 10], [100], []), ([math.inf, 10], [100], []),
    ([True, 10], [100], []), (["1", 10], [100], []),
    ([1, 10], [], []), ([1, 10], [100, -1], []),
    ([1, 10], [50, 100], []), ([1, 10], [math.nan], []),
    ([1, 10], [100], [0]), ([1, 10], [100], [math.inf]),
    ([1, 1e18], [100, 50], []), ([1e308, 1e308], [100, 50], []),
])
def test_invalid_or_unresolvable_float_domain_rejected(table, prizes, other):
    with pytest.raises(ValueError):
        mtt_icm_equities(table, prizes, other)


def test_quadrature_polynomial_and_empty_interval():
    assert _qng(lambda x: x ** 12, 0, 1) == pytest.approx(1 / 13, abs=1e-15)
    assert _qng(lambda x: 1, 2, 2) == 0
