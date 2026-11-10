"""Independent invariants and edge-case validation of the research engine.

Expected values are derived from pot accounting/probability, not HRC output.
"""
from collections import Counter
from fractions import Fraction
from itertools import permutations
import random
from types import SimpleNamespace

import pytest

from preflop_lab.cards import (
    CLASS_COMBOS, HandRange, hand_class, sample_deal, validate_joint_ranges,
)
from preflop_lab.core import ResearchSolver, SCALE, icm_equities, terminal_icm_equities


def game(stacks, **kwargs):
    return ResearchSolver({
        "players": [{"name": f"P{i}", "stack": value, "range": "all"}
                    for i, value in enumerate(stacks)],
        "open_sizes": [2.5], "reraise_multipliers": [2], "max_raises": 4,
        "evaluation_samples": 0,
        **kwargs,
    })


def walk(solver, *actions):
    node = solver.root
    for action in actions:
        node = solver.step(node, action)
    return node


def test_joint_range_sampling_conditions_all_seats_together():
    # P0: 6 AA combos each at weight .5, 6 KK at 1; P1: 6 AA at 1.
    # Compatible total masses: AA/AA = 6*.5*1 = 3; KK/AA = 6*6 = 36.
    # Thus P(P0=AA | compatible) = 1/13, not its independent prior 1/3.
    ranges = [HandRange.build("AA:50%,KK"), HandRange.build("AA")]
    rng = random.Random(749331)
    seen = Counter()
    for _ in range(12000):
        holes, board = sample_deal(ranges, rng)
        assert len(set((*holes[0], *holes[1], *board))) == 9
        seen[hand_class(holes[0])] += 1
    assert abs(seen["AA"] / 12000 - 1 / 13) < .012


def test_range_combo_multiplicities_and_impossible_joint_range():
    assert sum(map(len, CLASS_COMBOS.values())) == 1326
    assert len(CLASS_COMBOS["AA"]) == 6
    assert len(CLASS_COMBOS["AKs"]) == 4
    assert len(CLASS_COMBOS["AKo"]) == 12
    with pytest.raises(ValueError, match="duplicate cards"):
        validate_joint_ranges([HandRange.build("AA")] * 3)


def test_sidepots_and_uncalled_excess_are_separate_tiers():
    solver = game([100, 70, 30])
    node = walk(solver, "allin", "call", "call")
    assert node.terminal
    # Short player wins 90 main; middle wins 80 side; large gets 30 uncalled.
    assert solver.terminal_stacks(node, [30, 20, 10]) == pytest.approx([30, 80, 90])
    # All tie: every player recovers its own stake from each eligible tier.
    assert solver.terminal_stacks(node, [10, 10, 10]) == pytest.approx([100, 70, 30])


def test_folded_chips_remain_in_main_and_sidepots():
    solver = game([30, 20, 10])
    # P0 open 2.5; P1 raise 5; P2 shove 10; P0 folds; P1 calls.
    node = walk(solver, "raise_2500000", "raise_5000000", "allin", "fold", "call")
    assert node.terminal
    assert solver.terminal_stacks(node, [1, 30, 20]) == pytest.approx([27.5, 10, 22.5])


def test_single_short_allin_does_not_reopen_original_raiser():
    solver = game([20, 3, 20])
    node = walk(solver, "raise_2500000", "allin", "call")
    assert node.actor == 0
    assert {action.kind for action in solver.legal_actions(node)} == {"fold", "call"}


def test_cumulative_short_allins_reopen_only_players_facing_full_increment():
    solver = game([20, 3, 20, 4, 20])
    node = walk(solver, "raise_2500000", "allin", "call", "allin", "call")
    assert node.actor == 0
    # 2.5->4 is a complete 1.5 raise to P0, but P2 called at 3.
    assert any(action.kind in ("raise", "allin") for action in solver.legal_actions(node))
    assert node.last_full_raise == int(1.5 * SCALE)
    node = solver.step(node, "call")
    assert node.actor == 2
    assert {action.kind for action in solver.legal_actions(node)} == {"fold", "call"}


def test_big_blind_keeps_option_after_small_blind_complete():
    solver = game([20, 20])
    node = walk(solver, "call")
    assert node.actor == 1
    assert "check" in {a.id for a in solver.legal_actions(node)}
    node = solver.step(node, "check")
    assert node.terminal


def test_heads_up_short_blind_does_not_force_artificial_call_or_dry_bet():
    solver = game([20, .3])
    assert solver.root.terminal
    assert solver.legal_actions(solver.root) == ()
    assert solver.terminal_stacks(solver.root, [20, 10]) == pytest.approx([19.7, .6])


def test_sole_active_player_faces_only_largest_actual_allin():
    solver = game([20, .4, .3])
    actions = solver.legal_actions(solver.root)
    assert {a.id for a in actions} == {"fold", "call"}
    assert next(a.cost for a in actions if a.id == "call") == int(.4 * SCALE)
    node = walk(solver, "call")
    assert solver.terminal_stacks(node, [30, 20, 10]) == pytest.approx([19.6, .2, .9])


def permutation_icm(stacks, payouts):
    """Separate reference using exhaustive finishing-order permutations."""
    n = len(stacks)
    result = [Fraction(0)] * n
    prizes = list(map(Fraction, payouts)) + [Fraction(0)] * (n - len(payouts))
    for order in permutations(range(n)):
        probability = Fraction(1)
        remaining = sum(stacks)
        for player in order:
            probability *= Fraction(stacks[player], remaining)
            remaining -= stacks[player]
        for place, player in enumerate(order):
            result[player] += probability * prizes[place]
    return list(map(float, result))


def test_icm_matches_exhaustive_finish_orders_and_conserves_prizes():
    stacks, prizes = [37, 23, 17, 11, 7, 5], [100, 55, 30, 15]
    answer = icm_equities(stacks, prizes)
    assert answer == pytest.approx(permutation_icm(stacks, prizes), abs=1e-10)
    assert sum(answer) == pytest.approx(sum(prizes))


def test_simultaneous_eliminations_rank_by_starting_stack_and_split_ties():
    assert terminal_icm_equities([60, 0, 0], [50, 30, 20], [30, 20, 10]) == [50, 30, 20]
    assert terminal_icm_equities([60, 0, 0], [50, 30, 20], [20, 20, 20]) == [50, 25, 25]


def test_every_reachable_small_tree_conserves_chips_and_never_goes_negative():
    solver = game([3, 5, 4], ante=.1, max_raises=2)
    pending = [solver.root]
    checked = 0
    terminal_count = 0
    while pending:
        state = pending.pop()
        checked += 1
        assert sum(state.contributions) + sum(state.remaining) == sum(solver.starting)
        assert all(x >= 0 for x in (*state.contributions, *state.street, *state.remaining))
        if state.terminal:
            terminal_count += 1
            for ranks in ([10, 20, 30], [30, 20, 10], [10, 10, 10]):
                end = solver.terminal_stacks(state, ranks)
                assert min(end) >= 0
                assert sum(end) == pytest.approx(12)
            continue
        assert not state.folded[state.actor]
        assert state.remaining[state.actor] > 0
        actions = solver.legal_actions(state)
        assert len({action.id for action in actions}) == len(actions)
        for action in actions:
            assert 0 <= action.cost <= state.remaining[state.actor]
            child = solver.step(state, action.id)
            assert len(child.path) == len(state.path) + 1
            pending.append(child)
    assert checked > 20
    assert terminal_count > 10


@pytest.mark.parametrize("bad", [None, 1, True, "50,30,20"])
def test_invalid_payout_container_has_clean_validation_error(bad):
    with pytest.raises(ValueError):
        game([10, 10], payouts=bad)


class KuhnAdapter(ResearchSolver):
    """Exercise production regret/average updates on a solved small game.

    Only game rules/payoffs are replaced. Betting and private information have
    two decisions per player and three card ranks, permitting exact best response.
    """
    def __init__(self):
        self.n = 2
        self.config = {"max_infosets": 100}
        self._infos = {}
        self._nodes = {}
        self._rng = random.Random(901114)
        self._cancel = lambda: False
        self._touches = 0
        self.root = self._node(())

    def _node(self, path):
        actors = {(): 0, ("check",): 1, ("bet",): 1, ("check", "bet"): 0}
        actor = actors.get(path)
        return SimpleNamespace(path=path, actor=actor, terminal=actor is None)

    def legal_actions(self, state):
        if state.terminal:
            return ()
        names = ("fold", "call") if state.path and state.path[-1] == "bet" else ("check", "bet")
        return tuple(SimpleNamespace(id=name) for name in names)

    def step(self, state, action_id):
        return self._node(state.path + (action_id,))

    def _utility(self, state, ranks, traverser):
        if state.path[-1] == "fold":
            winner = 0 if state.path == ("bet", "fold") else 1
            amount = 1
        else:
            winner = 0 if ranks[0] < ranks[1] else 1
            amount = 1 if state.path == ("check", "check") else 2
        return amount if traverser == winner else -amount


def test_actual_mccfr_updates_solve_kuhn_against_exact_best_responses():
    solver = KuhnAdapter()
    deals = list(permutations(range(3), 2))
    # Each inner step calls the production methods, including importance-
    # weighted averaging. Independent chance samples serve each traversal.
    for _ in range(12000):
        for traverser in range(2):
            labels = solver._rng.choice(deals)
            solver._traverse(solver.root, labels, tuple(2 - x for x in labels), traverser)
        for _ in range(2):
            solver._average_pass(solver._rng.choice(deals))

    policy = {key: info.mean_strategy() for key, info in solver._infos.items()}

    def value_for_deal(state, deal, override):
        if state.terminal:
            return solver._utility(state, tuple(2 - x for x in deal), 0)
        key = (state.path, deal[state.actor])
        choices = override.get(key, policy[key])
        return sum(p * value_for_deal(solver.step(state, action.id), deal, override)
                   for p, action in zip(choices, solver.legal_actions(state)))

    def exact_value(override):
        return sum(value_for_deal(solver.root, deal, override) for deal in deals) / len(deals)

    best = []
    for player in range(2):
        paths = [(), ("check", "bet")] if player == 0 else [("check",), ("bet",)]
        keys = [(path, card) for path in paths for card in range(3)]
        responses = []
        for bits in range(1 << len(keys)):
            override = {key: ([0., 1.] if bits & (1 << index) else [1., 0.])
                        for index, key in enumerate(keys)}
            payoff = exact_value(override)
            responses.append(payoff if player == 0 else -payoff)
        best.append(max(responses))
    assert abs(exact_value({}) - (-1 / 18)) < .03
    assert sum(best) < .06  # Exact NashConv of the averaged two-player profile.

