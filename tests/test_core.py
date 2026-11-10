import math
import random

import pytest

from preflop_lab.cards import CLASS_COMBOS, HAND_LABELS, HandRange, hand_class, parse_range, sample_deal
from preflop_lab.core import ResearchSolver, SCALE, default_config, icm_equities, terminal_icm_equities


def solver(stacks=(20, 20, 20), **kwargs):
    return ResearchSolver({"players": [{"name": f"P{i}", "stack": stack, "range": "all"}
                                        for i, stack in enumerate(stacks)],
                           "payouts": [100] + [0] * (len(stacks) - 1),
                           "evaluation_samples": 0, **kwargs})


def walk(game, *actions):
    return game.get_state(actions)


def action_ids(game, state):
    return [a.id for a in game.legal_actions(state)]


def test_preflop_blinds_and_turn_order():
    for n in range(2, 7):
        game = solver([20] * n)
        assert game.root.actor == 0
        assert game.root.street == (0,) * (n - 2) + (SCALE // 2, SCALE)
        state = game.root
        for i in range(n - 1):
            assert state.actor == i
            state = game.step(state, "call")
        assert state.actor == n - 1
        assert "check" in action_ids(game, state)
        assert game.step(state, "check").terminal


def test_stacks_include_blinds_and_antes():
    game = solver((10, 10, 10), ante=0.25)
    assert game.describe_node()["remaining"] == [9.75, 9.25, 8.75]
    assert game.describe_node()["pot"] == 2.25
    assert sum(game.root.contributions) + sum(game.root.remaining) == 30 * SCALE


def test_fold_award_and_uncalled_return():
    game = solver()
    folded = walk(game, "fold", "fold")
    assert game.terminal_stacks(folded, (1, 2, 3)) == [20, 19.5, 20.5]
    game = solver((20, 5))
    showdown = walk(game, "allin", "call")
    assert game.terminal_stacks(showdown, (2, 1)) == [15, 10]
    assert game.terminal_stacks(showdown, (1, 2)) == [25, 0]


def test_side_pots_awarded_independently_and_ties_split():
    game = solver((5, 10, 20))
    state = walk(game, "allin", "allin", "call")
    assert state.terminal
    assert game.terminal_stacks(state, (1, 2, 3)) == [15, 10, 10]
    assert game.terminal_stacks(state, (1, 1, 3)) == [7.5, 17.5, 10]
    assert game.terminal_stacks(state, (3, 2, 1)) == [0, 0, 35]
    folded = walk(game, "allin", "call", "fold")
    assert game.terminal_stacks(folded, (1, 2, 3)) == [11, 5, 19]


def test_underraise_does_not_reopen_prior_raiser():
    game = solver((20, 3, 20))
    short = walk(game, "raise_2500000", "allin")
    assert short.last_full_raise == int(1.5 * SCALE)
    assert game.describe_node(short.path)["minimum_raise_to"] == 4.5
    back = game.step(short, "call")
    assert back.actor == 0
    assert action_ids(game, back) == ["fold", "call"]
    assert game.step(back, "call").terminal


def test_cumulative_short_raises_reopen_action():
    game = solver((20, 3, 4, 20))
    back = walk(game, "raise_2500000", "allin", "allin", "call")
    assert back.actor == 0
    assert back.current_bet == 4 * SCALE
    assert "allin" in action_ids(game, back)
    assert back.last_full_raise == int(1.5 * SCALE)


def test_raise_cap_keeps_allin_and_dry_pot_forbids_extra_bets():
    game = solver((20, 20), max_raises=0)
    assert action_ids(game, game.root) == ["fold", "call", "allin"]
    game = solver((20, 0.25))
    assert game.root.terminal
    assert game.terminal_stacks(game.root, (2, 1)) == [19.75, 0.5]
    game = solver((0.25, 20))
    assert game.root.terminal
    assert game.terminal_stacks(game.root, (1, 2)) == [0.5, 19.75]


def test_icm_known_values_and_simultaneous_eliminations():
    assert icm_equities([1, 1, 1], [50, 30, 20]) == pytest.approx([100 / 3] * 3)
    assert icm_equities([3, 1], [100, 0]) == pytest.approx([75, 25])
    assert icm_equities([0, 0, 10], [50, 30, 20]) == pytest.approx([25, 25, 50])
    assert terminal_icm_equities([0, 0, 35], [50, 30, 20], [5, 10, 20]) == [20, 30, 50]
    assert terminal_icm_equities([0, 0, 35], [50, 30, 20], [5, 5, 25]) == [25, 25, 50]


def test_random_reachable_tree_chip_conservation():
    rng = random.Random(7801)
    for n in range(2, 7):
        game = solver([rng.randrange(2, 31) / 2 for _ in range(n)], ante=0.15)
        total = sum(game.starting) / SCALE
        for _ in range(100):
            state = game.root
            actions = 0
            while not state.terminal:
                assert sum(state.remaining) + sum(state.contributions) == sum(game.starting)
                assert all(x >= 0 for x in state.remaining)
                state = game.step(state, rng.choice(game.legal_actions(state)).id)
                actions += 1
                assert actions < 100
            end = game.terminal_stacks(state, [rng.randrange(1, 5) for _ in range(n)])
            assert sum(end) == pytest.approx(total)
            assert all(x >= 0 for x in end)


def test_range_classes_weights_and_overrides():
    assert len(HAND_LABELS) == len(set(HAND_LABELS)) == 169
    assert sum(map(len, CLASS_COMBOS.values())) == 1326
    assert len(CLASS_COMBOS["AA"]) == 6
    assert len(CLASS_COMBOS["AKs"]) == 4
    assert len(CLASS_COMBOS["AKo"]) == 12
    weights = parse_range("JJ+, AJs+, AQo+, AA:50%")
    assert weights["AA"] == 0.5 and weights["JJ"] == 1 and weights["TT"] == 0
    assert all(weights[x] == 1 for x in ("AKs", "AQs", "AJs", "AKo", "AQo"))
    assert parse_range("99-JJ")["TT"] == 1
    assert parse_range("A2s-A5s")["A4s"] == 1
    assert parse_range("all,72o:0")["72o"] == 0
    with pytest.raises(ValueError):
        parse_range("AKs:2")
    with pytest.raises(ValueError):
        solver((20, 20, 20), players=[{"stack": 20, "range": "AA"}] * 3)


def test_joint_range_sampler_avoids_sequential_conditioning_bias():
    # Legal ordered deals: AA/AA = 6; KK/AA = 36, so P(first AA)=1/7.
    # A sequential seat-by-seat sampler would incorrectly produce 1/2.
    ranges = [HandRange.build("AA,KK"), HandRange.build("AA")]
    rng = random.Random(881)
    count = 0
    for _ in range(7000):
        holes, board = sample_deal(ranges, rng)
        assert len(set(sum(holes, ()) + board)) == 9
        count += hand_class(holes[0]) == "AA"
    assert count / 7000 == pytest.approx(1 / 7, abs=0.015)


def test_multiplayer_average_sampling_correction():
    game = solver((2, 2, 2), max_raises=0)
    first, second, target = game.root, walk(game, "call"), walk(game, "call", "call")
    labels = ("AA", "KK", "QQ")
    # Target player has own reach 1 in both phases. Opponents dramatically
    # change reach to the node, but that must not distort its time average.
    for phase in (0, 1):
        for state, label in ((first, "AA"), (second, "KK")):
            game._info(state, label).regret[:] = ([1, 98, 1] if phase == 0 else [49, 2, 49])
        game._info(target, "QQ").regret[:] = ([9, 1] if phase == 0 else [1, 9])
        for _ in range(12000):
            game._average_pass(labels)
    assert game._info(target, "QQ").mean_strategy() == pytest.approx([0.5, 0.5], abs=0.025)


def test_actual_learning_in_restricted_heads_up_game():
    # AA has 80%+ equity vs KK. At 2bb, jamming AA wins more than checking
    # down a limp; KK faces a 25% call threshold and should predominantly fold.
    game = solver((2, 2), players=[{"name": "SB", "stack": 2, "range": "AA"},
                                 {"name": "BB", "stack": 2, "range": "KK"}], max_raises=0)
    result = game.run(3000)
    assert result["summary"]["status"] == "completed"
    root = result["nodes"]["root"]
    jam_index = next(i for i, a in enumerate(root["actions"]) if a["id"] == "allin")
    assert root["hands"]["AA"]["frequencies"][jam_index] > 0.95
    assert result["nodes"]["allin"]["hands"]["KK"]["frequencies"][0] > 0.95
    assert "QQ" not in root["hands"]


def test_deterministic_seed_progress_cancel_and_resource_limits():
    config = {"evaluation_samples": 0}
    a, b = ResearchSolver(config), ResearchSolver(config)
    progress = []
    result_a = a.run(100, progress_callback=progress.append)
    result_b = b.run(100)
    assert result_a["nodes"] == result_b["nodes"]
    assert [p["iteration"] for p in progress] == [0, 20, 40, 60, 80, 100]
    cancelled = ResearchSolver(config).run(100, cancel_check=lambda: True)
    assert cancelled["summary"]["status"] == "cancelled"
    assert cancelled["summary"]["iterations"] == 0
    limited = ResearchSolver({**config, "max_infosets": 100}).run(100)
    assert limited["summary"]["status"] == "resource_limit"
    assert limited["summary"]["iterations"] < 100


@pytest.mark.parametrize("bad", [{"payouts": None}, {"payouts": 3}, {"seed": float("nan")},
                                 {"iterations": 1}, {"open_sizes": [1]}, {"utility": "mystery"}])
def test_validation_raises_clear_value_errors(bad):
    with pytest.raises(ValueError):
        ResearchSolver(bad)
