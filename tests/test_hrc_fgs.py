"""Independent FGS rules, real recursion, resource limits, and numerical regressions."""
from dataclasses import replace
import itertools
from pathlib import Path

import pytest

from preflop_lab.hrc_fgs import (Calculator, ChanceTables, Config, Context,
    FgsResourceLimit, Outcome, _RESULTS, allin_outcome, forced_state,
    next_context, ordinary_terminal)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def tables():
    path = ROOT / "analysis/hrc-deep/fgs/chance-cache.bin"
    if path.exists():
        return ChanceTables.read(path)
    plugins = Path("D:/Program Files/HRC/plugins")
    if not (plugins / "net.holdemresources.preflopdata.holdem_1.4.1.jar").exists():
        pytest.skip("Optional original chance-table research fixture is unavailable")
    return ChanceTables.from_installation(plugins)


@pytest.mark.parametrize("moving,stacks,expected,skip", [
    (False, (10, 20, 30, 40), (20, 30, 40, 10), False),
    (False, (10, 20, 30, 0), (20, 30, 10), True),
    (True, (10, 20, 30, 0), (30, 10, 20), False),
    (True, (10, 20, 0, 40), (40, 10, 20), False),
    (True, (10, 20, 0, 0), (10, 20), False),
    (False, (10, 0, 0, 40), (40, 10), False),
])
def test_seat_rotation_and_eliminated_blinds(moving, stacks, expected, skip):
    initial = Context((10, 20, 30, 40), depth=2)
    config = Config((100, 50), 10, 5, moving_button=moving)
    child, mapping = next_context(initial, Outcome(stacks, (0,) * 4, 3, False), config)
    assert child.stacks == expected and child.skip_sb == skip and child.depth == 3
    assert tuple(stacks[i] for i in mapping) == expected


@pytest.mark.parametrize("ante_type,remaining,posted,pool", [
    ("REGULAR", [150, 0, 0], [0, 20, 0], 0),
    ("BB_ANTE_FIRST", [250, 70, 0], [0, 50, 0], 70),
    ("BB_BLIND_FIRST", [250, 70, 0], [0, 50, 70], 0),
])
def test_short_stack_forced_bet_priority(ante_type, remaining, posted, pool):
    state = forced_state(Context((250, 120, 70)), Config((100, 50), 100, 50, 100, ante_type=ante_type))
    assert state[0] == remaining and state[1] == posted and state[3] == pool
    assert sum(state[0]) + sum(state[1]) + sum(state[2]) + state[3] == 440


def test_bb_ante_zero_live_contribution_can_win_global_pool():
    context = Context((250, 120, 70))
    config = Config((100, 50), 100, 50, 100, ante_type="BB_ANTE_FIRST")
    outcome = allin_outcome(context, config, (0, 2), (2, 1))
    assert outcome.stacks[2] == 70
    assert sum(outcome.stacks) == 440


def test_equal_rank_odd_chip_uses_largest_seat_at_equal_cap():
    context = Context((100, 100, 100))
    outcome = allin_outcome(context, Config((100, 50), 2, 1), (0, 2), (1, 1))
    assert outcome.stacks == (100, 99, 101)
    assert outcome.tied_award


@pytest.mark.parametrize("ante_type", ["REGULAR", "BB_ANTE_FIRST", "BB_BLIND_FIRST"])
def test_all_root_participant_outcomes_conserve_chips(ante_type):
    context = Context((15, 40, 105, 160))
    config = Config((100, 60, 20), 50, 25, 20, ante_type=ante_type)
    for count in (1, 2, 3):
        for participants in itertools.combinations(range(4), count):
            for ranks in _RESULTS[count]:
                outcome = allin_outcome(context, config, participants, ranks)
                assert sum(outcome.stacks) == sum(context.stacks)
                assert min(outcome.stacks) >= 0
                assert all(not mask if outcome.stacks[i] else True for i, mask in enumerate(outcome.winner_masks))


def test_pkos_pay_now_roll_heads_and_preserve_full_prize_mass():
    context = Context((100, 100, 100), (20, 40, 60))
    config = Config((100, 60, 20), 10, 5, bounty_mode="PROGRESSIVE", immediate_fraction=0.25)
    outcome = allin_outcome(context, config, (0, 1, 2), (1, 2, 3))
    values, immediate, heads = ordinary_terminal(context, config, outcome)
    assert heads == (95, 0, 0)
    assert immediate == [25, 40, 40]
    assert sum(values) == pytest.approx(300)


def test_next_blind_level_is_depth_sensitive():
    config = Config((100, 50), 100, 50, next_level_at=2, next_level=(200, 100, 10))
    before = forced_state(Context((1000, 1000), depth=1), config)
    after = forced_state(Context((1000, 1000), depth=2), config)
    assert before[1] == [50, 100] and after[1] == [100, 200] and after[2] == [10, 10]


def test_full_hu_recursive_regression_and_cache(tables):
    calculator = Calculator(Config((100, 50), 100, 50, depth=1), tables)
    context = Context((1000, 1000))
    actual = calculator.equities(context)
    assert actual == pytest.approx([74.95299024077718, 75.04700975922282], abs=1e-11)
    assert calculator.stats["states"] == 3 and calculator.stats["sweeps"] == 600
    assert calculator.equities(context) == actual
    assert calculator.stats["cache_hits"] >= 1
    assert actual != pytest.approx([75, 75], abs=1e-4)


def test_tie_and_three_way_recursion_cutoffs(tables):
    context = Context((1000, 800, 1200))
    config = Config((100, 60, 20), 100, 50, depth=1, depth3way=0)
    calculator = Calculator(config, tables)
    for ranks in [(1, 1, 1), (1, 2, 3)]:
        outcome = allin_outcome(context, config, (0, 1, 2), ranks)
        assert calculator.terminal(context, outcome) == ordinary_terminal(context, config, outcome)[0]
    assert calculator.stats["states"] == 0


def test_failed_work_is_not_published_as_completed_result(tables):
    calculator = Calculator(Config((100, 50), 100, 50, max_states=1), tables)
    context = Context((1000, 1000))
    with pytest.raises(FgsResourceLimit):
        calculator.equities(context)
    assert context not in calculator.caches[0]


def test_idle_training_time_does_not_consume_fgs_work_budget(tables, monkeypatch):
    calculator = Calculator(Config((100, 50), 100, 50, depth=0, max_seconds=1), tables)
    context = Context((1000, 1000))
    outcome = allin_outcome(context, calculator.config, (0,), (1,))
    expected = calculator.terminal(context, outcome)
    spent = calculator.work_seconds
    monkeypatch.setattr("preflop_lab.hrc_fgs.time.monotonic", lambda: 1e9)
    assert calculator.terminal(context, outcome) == expected
    assert calculator.work_seconds == spent
    fresh = allin_outcome(context, calculator.config, (1,), (1,))
    assert calculator.terminal(context, fresh) == ordinary_terminal(context, calculator.config, fresh)[0]


def test_completed_terminal_cache_remains_usable_after_budget_exhaustion(tables):
    calculator = Calculator(Config((100, 50), 100, 50, depth=0), tables)
    context = Context((1000, 1000))
    outcome = allin_outcome(context, calculator.config, (0,), (1,))
    expected = calculator.terminal(context, outcome)
    calculator.stats["states"] = calculator.config.max_states + 1
    assert calculator.terminal(context, outcome) == expected
    with pytest.raises(FgsResourceLimit):
        calculator.terminal(context, allin_outcome(context, calculator.config, (1,), (1,)))


def test_bad_outcome_rejected(tables):
    calculator = Calculator(Config((100, 50), 100, 50), tables)
    with pytest.raises(ValueError):
        calculator.terminal(Context((1000, 1000)), Outcome((1001, 1000), (0, 0), 1, False))
