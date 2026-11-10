"""Independent no-limit preflop tree, check-down leaves, and MCCFR.

Regrets: external sampling (Lanctot et al., NIPS 2009), one traversal per
player. Chance and opponents are sampled from their actual distributions;
the traverser's actions are enumerated, so no own-reach multiplier is applied
to counterfactual regret updates.

Averages: a SEPARATE full-support public-trajectory sampler. At information
set I, add pi_i(I) / q_public(I) * sigma_i(I). Taking expectation cancels the
public sampling probability. Private-card sampling contributes a stationary
hand-class marginal, which cancels on normalization. This also works for more
than two players, unlike the usual uncorrected opponent-node averaging trick.

All future streets check down on one uniformly sampled shared board. This is
an explicit smaller game, not a postflop solver or an HRC-equivalent valuation.
"""

from dataclasses import dataclass, field
from functools import lru_cache
import math
import random
import time

from .cards import HandRange, hand_class, sample_deal, evaluate_hands, validate_joint_ranges

SCALE = 1_000_000


def default_config():
    return {
        "players": [{"name": "BTN", "stack": 20.0, "range": "all"},
                    {"name": "SB", "stack": 20.0, "range": "all"},
                    {"name": "BB", "stack": 20.0, "range": "all"}],
        "small_blind": 0.5, "big_blind": 1.0, "ante": 0.0,
        "open_sizes": [2.5], "reraise_multipliers": [3.0], "max_raises": 2,
        "utility": "chips", "payouts": [50.0, 30.0, 20.0],
        "iterations": 1000, "seed": 42,
        "max_nodes": 50000, "max_infosets": 100000, "evaluation_samples": 500,
    }


def _number(value, name, minimum=0, maximum=1_000_000):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a number.") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return result


def _integer(value, name, minimum, maximum):
    number = _number(value, name, minimum, maximum)
    if int(number) != number:
        raise ValueError(f"{name} must be an integer.")
    return int(number)


def _chips(value):
    return round(value * SCALE)


def _bb(value):
    return value / SCALE


def _payouts(values, n):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= n:
        raise ValueError(f"Payouts must contain 1 to {n} amounts.")
    result = [_number(x, "payout", 0, 1e12) for x in values]
    if any(result[i] < result[i + 1] for i in range(len(result) - 1)):
        raise ValueError("Payouts must be ordered from first place downward.")
    if sum(result) <= 0:
        raise ValueError("At least one payout must be positive.")
    return result + [0.0] * (n - len(result))


def icm_equities(stacks, payouts):
    """Exact independent-chip-model prize equity, up to six players.

    A positive stack wins first place in proportion to its chip share;
    recurse among the remaining stacks. Zero-stack ties split remaining
    prizes equally. Hand-ending eliminations use starting-stack rank in
    terminal_icm_equities instead of this generic zero-stack tie convention.
    """
    if not isinstance(stacks, (list, tuple)) or not 1 <= len(stacks) <= 6:
        raise ValueError("ICM supports 1 to 6 stacks.")
    stacks = tuple(_number(x, "ICM stack", 0, 1e15) for x in stacks)
    prizes = _payouts(payouts, len(stacks))
    n = len(stacks)

    @lru_cache(maxsize=None)
    def solve(mask):
        players = [i for i in range(n) if mask & (1 << i)]
        result = [0.0] * n
        if not players:
            return tuple(result)
        place = n - len(players)
        total = sum(stacks[i] for i in players)
        if total == 0:
            share = sum(prizes[place:]) / len(players)
            for i in players:
                result[i] = share
            return tuple(result)
        for winner in players:
            if stacks[winner] == 0:
                continue
            probability = stacks[winner] / total
            child = solve(mask ^ (1 << winner))
            for i in players:
                result[i] += probability * (prizes[place] if i == winner else child[i])
        return tuple(result)

    return list(solve((1 << n) - 1))


def terminal_icm_equities(stacks, payouts, starting_stacks):
    """ICM for survivors; same-hand busts rank by pre-hand stack (ties split)."""
    n = len(stacks)
    prizes = _payouts(payouts, n)
    alive = [i for i, value in enumerate(stacks) if value > 1e-9]
    eliminated = sorted((i for i in range(n) if i not in alive),
                        key=lambda i: starting_stacks[i], reverse=True)
    result = [0.0] * n
    if alive:
        for i, value in zip(alive, icm_equities([stacks[j] for j in alive], prizes[:len(alive)])):
            result[i] = value
    position = 0
    while position < len(eliminated):
        end = position + 1
        while end < len(eliminated) and starting_stacks[eliminated[end]] == starting_stacks[eliminated[position]]:
            end += 1
        share = sum(prizes[len(alive) + position:len(alive) + end]) / (end - position)
        for i in eliminated[position:end]:
            result[i] = share
        position = end
    return result


@dataclass(frozen=True, slots=True)
class State:
    path: tuple
    contributions: tuple
    street: tuple
    remaining: tuple
    folded: tuple
    pending: tuple
    reopen_at: tuple
    current_bet: int
    last_full_raise: int
    raises: int
    actor: int | None

    @property
    def terminal(self):
        return self.actor is None


@dataclass(frozen=True, slots=True)
class Action:
    id: str
    kind: str
    amount: int
    cost: int
    label: str

    def as_dict(self):
        return {"id": self.id, "kind": self.kind, "amount": _bb(self.amount),
                "cost": _bb(self.cost), "label": self.label}


@dataclass(slots=True)
class InfoSet:
    regret: list
    average: list
    visits: int = 0
    average_samples: int = 0
    average_weight: float = 0.0

    def strategy(self):
        positive = [max(0.0, r) for r in self.regret]
        total = sum(positive)
        return [x / total for x in positive] if total > 0 else [1 / len(positive)] * len(positive)

    def mean_strategy(self):
        total = sum(self.average)
        return [x / total for x in self.average] if total > 0 else None


class ResourceLimit(RuntimeError):
    pass


class _Cancelled(Exception):
    pass


class ResearchSolver:
    def __init__(self, config=None):
        raw = default_config()
        if config is not None:
            if not isinstance(config, dict):
                raise ValueError("Config must be an object.")
            raw.update(config)
        players = raw["players"]
        if not isinstance(players, list) or not 2 <= len(players) <= 6:
            raise ValueError("Use 2 to 6 players in preflop order: UTG ... BTN, SB, BB; heads-up: SB/BTN, BB.")
        self.n = len(players)
        canonical_players = []
        self.ranges = []
        for i, player in enumerate(players):
            if not isinstance(player, dict):
                raise ValueError("Each player must be an object.")
            stack = _number(player.get("stack", 20), f"Player {i + 1} stack", 0.000001, 10000)
            name = str(player.get("name", f"P{i + 1}"))[:40]
            hand_range = HandRange.build(player.get("range", "all"))
            self.ranges.append(hand_range)
            canonical_players.append({"name": name, "stack": _bb(_chips(stack)),
                                      "range": player.get("range", "all")})
        validate_joint_ranges(self.ranges)
        sb = _number(raw["small_blind"], "Small blind", 0.000001, 1000)
        bb = _number(raw["big_blind"], "Big blind", sb, 1000)
        ante = _number(raw["ante"], "Ante", 0, 1000)
        if not isinstance(raw["open_sizes"], list) or not 1 <= len(raw["open_sizes"]) <= 4:
            raise ValueError("Specify 1 to 4 opening raise-to sizes.")
        opens = sorted(set(_number(x, "Opening size", 2 * bb, 20000) for x in raw["open_sizes"]))
        if not isinstance(raw["reraise_multipliers"], list) or not 1 <= len(raw["reraise_multipliers"]) <= 3:
            raise ValueError("Specify 1 to 3 re-raise multipliers.")
        multipliers = sorted(set(_number(x, "Re-raise multiplier", 1.01, 10) for x in raw["reraise_multipliers"]))
        utility = raw["utility"]
        if utility not in ("chips", "icm"):
            raise ValueError("Utility must be 'chips' or 'icm'.")
        # Adapt only the untouched default payouts to a smaller table.
        prize_input = raw["payouts"]
        if isinstance(prize_input, (list, tuple)) and self.n < len(prize_input) and (config is None or "payouts" not in config):
            prize_input = prize_input[:self.n]
        prizes = _payouts(prize_input, self.n)
        self.config = {"players": canonical_players, "small_blind": sb, "big_blind": bb,
                       "ante": ante, "open_sizes": opens, "reraise_multipliers": multipliers,
                       "max_raises": _integer(raw["max_raises"], "Maximum normal raises", 0, 4),
                       "utility": utility, "payouts": prizes,
                       "iterations": _integer(raw["iterations"], "Iterations", 100, 20000),
                       "seed": _integer(raw["seed"], "Seed", 0, 2**32 - 1),
                       "max_nodes": _integer(raw["max_nodes"], "Node budget", 100, 100000),
                       "max_infosets": _integer(raw["max_infosets"], "Information-set budget", 100, 200000),
                       "evaluation_samples": _integer(raw["evaluation_samples"], "Evaluation samples", 0, 10000)}
        self.starting = tuple(_chips(p["stack"]) for p in canonical_players)
        self.baseline = (icm_equities(self.starting, prizes) if utility == "icm"
                         else [_bb(x) for x in self.starting])
        self._nodes = {}
        self._actions = {}
        self._infos = {}
        self._rng = random.Random(self.config["seed"])
        self._cancel = lambda: False
        self._touches = 0
        self.iterations_completed = 0
        self.root = self._initial_state()
        self._nodes[()] = self.root

    def _initial_state(self):
        ante = _chips(self.config["ante"])
        contributions = [min(stack, ante) for stack in self.starting]
        remaining = [stack - paid for stack, paid in zip(self.starting, contributions)]
        street = [0] * self.n
        for i, blind in ((self.n - 2, self.config["small_blind"]),
                         (self.n - 1, self.config["big_blind"])):
            paid = min(remaining[i], _chips(blind))
            street[i] += paid
            remaining[i] -= paid
            contributions[i] += paid
        pending = tuple(x > 0 for x in remaining)
        state = State((), tuple(contributions), tuple(street), tuple(remaining),
                      (False,) * self.n, pending, (-1,) * self.n,
                      _chips(self.config["big_blind"]), _chips(self.config["big_blind"]), 0, None)
        return self._with_next_actor(state, self.n - 1)

    def _with_next_actor(self, state, previous):
        live = [i for i in range(self.n) if not state.folded[i]]
        able = [i for i in live if state.remaining[i] > 0]
        actor = None
        if len(live) > 1 and able:
            # No dry-side-pot betting, and no action against a short blind that
            # is already covered by the sole player still holding chips.
            settled = (len(able) == 1 and
                       state.street[able[0]] >= max(state.street[i] for i in live if i != able[0]))
            if not settled:
                for offset in range(1, self.n + 1):
                    i = (previous + offset) % self.n
                    if state.pending[i] and not state.folded[i] and state.remaining[i] > 0:
                        actor = i
                        break
        return State(state.path, state.contributions, state.street, state.remaining,
                     state.folded, state.pending, state.reopen_at, state.current_bet,
                     state.last_full_raise, state.raises, actor)

    def legal_actions(self, state):
        if state.terminal:
            return ()
        if state.path in self._actions:
            return self._actions[state.path]
        i = state.actor
        current = state.current_bet
        able_opponents = [j for j in range(self.n) if j != i and not state.folded[j] and state.remaining[j] > 0]
        if not able_opponents:
            current = max(state.street[j] for j in range(self.n) if j != i and not state.folded[j])
        owed = max(0, current - state.street[i])
        cost = min(state.remaining[i], owed)
        actions = []
        if owed:
            actions.append(Action("fold", "fold", state.street[i], 0, "Fold"))
            actions.append(Action("call", "call", state.street[i] + cost, cost,
                                  f"Call {_bb(cost):g}" + (" (all-in)" if cost == state.remaining[i] else "")))
        else:
            actions.append(Action("check", "check", state.street[i], 0, "Check"))
        max_to = state.street[i] + state.remaining[i]
        can_raise = (max_to > state.current_bet and state.current_bet >= state.reopen_at[i]
                     and any(state.street[j] + state.remaining[j] > state.current_bet for j in able_opponents))
        if can_raise:
            minimum = state.current_bet + state.last_full_raise
            if state.raises < self.config["max_raises"]:
                sizes = ([_chips(x) for x in self.config["open_sizes"]] if state.raises == 0
                         else [round(state.current_bet * x) for x in self.config["reraise_multipliers"]])
                for target in sorted(set(max(minimum, x) for x in sizes)):
                    if target < max_to:
                        actions.append(Action(f"raise_{target}", "raise", target, target - state.street[i],
                                              f"Raise to {_bb(target):g}"))
            actions.append(Action("allin", "allin", max_to, state.remaining[i], f"All-in to {_bb(max_to):g}"))
        result = tuple(actions)
        self._actions[state.path] = result
        return result

    def step(self, state, action_id):
        if state.terminal:
            raise ValueError("A terminal node has no actions.")
        path = state.path + (action_id,)
        if path in self._nodes:
            return self._nodes[path]
        action = next((a for a in self.legal_actions(state) if a.id == action_id), None)
        if action is None:
            raise ValueError(f"Illegal action {action_id!r} at this node.")
        if len(self._nodes) >= self.config["max_nodes"]:
            raise ResourceLimit("Public-node budget reached; reduce players, raise sizes or depth, or increase the explicit budget.")
        i = state.actor
        contributions, street = list(state.contributions), list(state.street)
        remaining, folded = list(state.remaining), list(state.folded)
        pending, reopen = list(state.pending), list(state.reopen_at)
        current, minimum, raises = state.current_bet, state.last_full_raise, state.raises
        pending[i] = False
        if action.kind == "fold":
            folded[i] = True
        else:
            contributions[i] += action.cost
            remaining[i] -= action.cost
            street[i] += action.cost
            if action.amount > current:
                increment = action.amount - current
                if increment >= minimum:
                    minimum = increment
                current = action.amount
                raises += 1
                pending = [j != i and not folded[j] and remaining[j] > 0 for j in range(self.n)]
            reopen[i] = current + minimum
        result = State(path, tuple(contributions), tuple(street), tuple(remaining), tuple(folded),
                       tuple(pending), tuple(reopen), current, minimum, raises, None)
        result = self._with_next_actor(result, i)
        self._nodes[path] = result
        return result

    def get_state(self, path=None):
        if path is None:
            path = []
        if not isinstance(path, (list, tuple)) or len(path) > 128 or any(not isinstance(a, str) for a in path):
            raise ValueError("Node path must be a list of at most 128 action IDs.")
        state = self.root
        for action_id in path:
            state = self.step(state, action_id)
        return state

    @staticmethod
    def node_id(path):
        return "/".join(path) if path else "root"

    def describe_node(self, path=None):
        state = self.get_state(path)
        i = state.actor
        return {"id": self.node_id(state.path), "path": list(state.path), "actor": i,
                "actor_name": self.config["players"][i]["name"] if i is not None else None,
                "pot": _bb(sum(state.contributions)), "current_bet": _bb(state.current_bet),
                "minimum_raise_to": _bb(state.current_bet + state.last_full_raise),
                "contributions": [_bb(x) for x in state.contributions],
                "street_contributions": [_bb(x) for x in state.street],
                "remaining": [_bb(x) for x in state.remaining], "folded": list(state.folded),
                "all_in": [not state.folded[j] and state.remaining[j] == 0 for j in range(self.n)],
                "terminal": state.terminal,
                "terminal_kind": ("fold_award" if sum(not x for x in state.folded) == 1 else "checkdown_showdown") if state.terminal else None,
                "actions": [a.as_dict() for a in self.legal_actions(state)]}

    def terminal_stacks(self, state, ranks):
        """Settle each contribution tier separately (lower rank is stronger).

        Uncalled top tiers return to their sole contributor. Folded money stays
        in the pot, ties split exactly; no chip denomination rounding is used.
        Output is in bb and conserves the sum of original stacks.
        """
        if not state.terminal:
            raise ValueError("Settlement requires a terminal state.")
        result = [float(x) for x in state.remaining]
        live = [i for i in range(self.n) if not state.folded[i]]
        if len(live) == 1:
            result[live[0]] += sum(state.contributions)
            return [_bb(x) for x in result]
        previous = 0
        for level in sorted(set(state.contributions) - {0}):
            contributors = [i for i in range(self.n) if state.contributions[i] >= level]
            amount = (level - previous) * len(contributors)
            previous = level
            if len(contributors) == 1:
                result[contributors[0]] += amount
                continue
            eligible = [i for i in contributors if not state.folded[i]]
            if not eligible:
                raise RuntimeError("Invalid reachable pot: no live eligible player in a contested tier.")
            best = min(ranks[i] for i in eligible)
            winners = [i for i in eligible if ranks[i] == best]
            for winner in winners:
                result[winner] += amount / len(winners)
        return [_bb(x) for x in result]

    def _utility(self, state, ranks, traverser):
        stacks = self.terminal_stacks(state, ranks)
        if self.config["utility"] == "icm":
            value = terminal_icm_equities(stacks, self.config["payouts"], self.starting)[traverser]
        else:
            value = stacks[traverser]
        return value - self.baseline[traverser]

    def _info(self, state, label):
        key = (state.path, label)
        info = self._infos.get(key)
        if info is None:
            if len(self._infos) >= self.config["max_infosets"]:
                raise ResourceLimit("Information-set budget reached; reduce players or raise sizes, or increase the explicit budget.")
            count = len(self.legal_actions(state))
            info = InfoSet([0.0] * count, [0.0] * count)
            self._infos[key] = info
        return info

    def _checkpoint(self):
        self._touches += 1
        if self._touches % 512 == 0 and self._cancel():
            raise _Cancelled

    def _pick(self, probabilities):
        draw = self._rng.random()
        cumulative = 0.0
        for index, probability in enumerate(probabilities):
            cumulative += probability
            if draw < cumulative:
                return index
        return len(probabilities) - 1

    def _traverse(self, state, labels, ranks, traverser):
        self._checkpoint()
        if state.terminal:
            return self._utility(state, ranks, traverser)
        actions = self.legal_actions(state)
        info = self._info(state, labels[state.actor])
        strategy = info.strategy()
        if state.actor != traverser:
            return self._traverse(self.step(state, actions[self._pick(strategy)].id), labels, ranks, traverser)
        values = [self._traverse(self.step(state, action.id), labels, ranks, traverser) for action in actions]
        expected = sum(probability * value for probability, value in zip(strategy, values))
        for index, value in enumerate(values):
            info.regret[index] += value - expected
        info.visits += 1
        return expected

    def _average_pass(self, labels):
        state = self.root
        reach = [1.0] * self.n
        sampling_reach = 1.0
        while not state.terminal:
            self._checkpoint()
            actor = state.actor
            actions = self.legal_actions(state)
            info = self._info(state, labels[actor])
            strategy = info.strategy()
            weight = reach[actor] / sampling_reach
            for index, probability in enumerate(strategy):
                info.average[index] += weight * probability
            info.average_weight += weight
            info.average_samples += 1
            # Uniform component guarantees positive support even when current
            # strategy puts zero mass on a public branch.
            sampling = [0.5 * p + 0.5 / len(actions) for p in strategy]
            index = self._pick(sampling)
            reach[actor] *= strategy[index]
            sampling_reach *= sampling[index]
            state = self.step(state, actions[index].id)

    def _evaluation(self, samples):
        rng = random.Random(self.config["seed"] ^ 0x5A17F00D)
        means, m2 = [0.0] * self.n, [0.0] * self.n
        fallbacks = decisions = 0
        for count in range(1, samples + 1):
            if self._cancel():
                raise _Cancelled
            holes, board = sample_deal(self.ranges, rng)
            labels, ranks = tuple(map(hand_class, holes)), evaluate_hands(holes, board)
            state = self.root
            while not state.terminal:
                actions = self.legal_actions(state)
                info = self._infos.get((state.path, labels[state.actor]))
                policy = info.mean_strategy() if info is not None and info.visits > 0 else None
                if policy is None:
                    policy = [1 / len(actions)] * len(actions)
                    fallbacks += 1
                decisions += 1
                index = rng.choices(range(len(actions)), weights=policy, k=1)[0]
                state = self.step(state, actions[index].id)
            stacks = self.terminal_stacks(state, ranks)
            values = (terminal_icm_equities(stacks, self.config["payouts"], self.starting)
                      if self.config["utility"] == "icm" else stacks)
            for i in range(self.n):
                value = values[i] - self.baseline[i]
                delta = value - means[i]
                means[i] += delta / count
                m2[i] += delta * (value - means[i])
        return {"samples": samples, "mean_utility": means,
                "standard_error": [math.sqrt(x / (samples - 1) / samples) if samples > 1 else None for x in m2],
                "untrained_fallback_decisions": fallbacks, "decisions": decisions,
                "fallback_policy": "uniform on legal actions when no trained average exists",
                "interpretation": "Self-play Monte Carlo utility estimate with sampling SE; not exploitability or a Nash certificate."}

    def run(self, iterations=None, progress_callback=None, cancel_check=None):
        target = _integer(self.config["iterations"] if iterations is None else iterations, "Iterations", 100, 20000)
        self._cancel = cancel_check or (lambda: False)
        started = time.perf_counter()
        status, message, evaluation = "completed", None, None
        completed = 0

        def progress():
            if progress_callback:
                progress_callback({"iteration": completed, "total": target,
                                   "elapsed_seconds": round(time.perf_counter() - started, 3),
                                   "nodes": len(self._nodes), "infosets": len(self._infos), "status": "running"})

        try:
            progress()
            for iteration in range(target):
                if self._cancel():
                    raise _Cancelled
                for traverser in range(self.n):
                    holes, board = sample_deal(self.ranges, self._rng)
                    self._traverse(self.root, tuple(map(hand_class, holes)), evaluate_hands(holes, board), traverser)
                # Independent chance samples for the average estimator.
                for _ in range(self.n):
                    holes, _board = sample_deal(self.ranges, self._rng)
                    self._average_pass(tuple(map(hand_class, holes)))
                completed = iteration + 1
                self.iterations_completed += 1
                if completed % 20 == 0 or completed == target:
                    progress()
            if self.config["evaluation_samples"]:
                evaluation = self._evaluation(self.config["evaluation_samples"])
        except _Cancelled:
            status, message = "cancelled", "Stopped on request; available partial strategies are retained."
        except ResourceLimit as exc:
            status, message = "resource_limit", str(exc)
        nodes = {}
        published = 0
        for (path, label), info in self._infos.items():
            frequencies = info.mean_strategy()
            if not info.visits or frequencies is None:
                continue
            state = self._nodes[path]
            node_id = self.node_id(path)
            if node_id not in nodes:
                nodes[node_id] = {"path": list(path), "actor": state.actor,
                                  "actions": [a.as_dict() for a in self.legal_actions(state)],
                                  "visits": 0, "hands": {}}
            nodes[node_id]["hands"][label] = {"frequencies": frequencies, "visits": info.visits,
                                             "average_samples": info.average_samples,
                                             "average_weight": info.average_weight, "trained": True}
            nodes[node_id]["visits"] += info.visits
            published += 1
        warnings = ["Continuation after preflop is a random-board check-down; there is no postflop betting.",
                    "Finite samples and action/hand abstractions can leave large strategy uncertainty. Unvisited hands are untrained.",
                    "No exploitability bound or convergence certificate is computed."]
        if self.n > 2 or self.config["utility"] == "icm":
            warnings.append("Multiplayer and ICM results have no general Nash-equilibrium convergence guarantee here.")
        return {"config": self.config, "summary": {"status": status, "message": message,
                "iterations": completed, "iterations_completed": completed, "iterations_requested": target,
                "total_iterations": self.iterations_completed,
                "elapsed_seconds": round(time.perf_counter() - started, 3), "public_nodes": len(self._nodes),
                "infosets": len(self._infos), "regret_infosets": sum(i.visits > 0 for i in self._infos.values()),
                "published_hands": published, "trained_nodes": len(nodes),
                "algorithm": "external-sampling MCCFR; separate importance-weighted average-policy sampling",
                "averaging": "own_reach / full-support public sampling reach; weighted 169-class private-card samples",
                "utility_unit": "bb" if self.config["utility"] == "chips" else "payout units",
                "continuation": "checkdown", "evaluation": evaluation, "warnings": warnings}, "nodes": nodes}
