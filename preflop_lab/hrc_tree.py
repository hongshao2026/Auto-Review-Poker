"""Import HRC topology and independently replay chip state, without saved strategy.

Only settings.json and gametree.dat are read. The topology remains an imported
research input: validating it is not an independent recreation of HRC's tree
builder. Amounts stay exact integers in the archive's internal chip units.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
import zipfile


ACTION_NAMES = ("fold", "check", "call", "raise")


class TreeReplayError(ValueError):
    """Invalid archive structure, unsupported setup, or illegal action replay."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TreeReplayError(message)


@dataclass(frozen=True, slots=True)
class HRCAction:
    kind: int
    actor: int
    street: int
    amount: int
    allin: bool = False

    @property
    def name(self) -> str:
        return ACTION_NAMES[self.kind]

    @classmethod
    def decode(cls, word: int) -> "HRCAction":
        _require(word & 15 < 4 and word & 240 == 0, f"Unsupported action word: {word:016x}")
        return cls(word & 15, (word >> 8) & 15, (word >> 13) & 7,
                   word >> 16, bool(word & 4096))


@dataclass(frozen=True, slots=True)
class ReplayRules:
    initial_stacks: tuple[int, ...]
    big_blind: int
    small_blind: int
    buckets: tuple[int, int, int, int]

    @property
    def players(self) -> int:
        return len(self.initial_stacks)


@dataclass(frozen=True, slots=True)
class ReplayState:
    remaining: tuple[int, ...]
    contributions: tuple[int, ...]
    street_contributions: tuple[int, ...]
    folded: tuple[bool, ...]
    street: int
    current_bet: int
    last_full_raise: int
    pending: tuple[bool, ...]
    reopen_at: tuple[int, ...]
    next_actor: int | None

    @property
    def pot(self) -> int:
        return sum(self.contributions)

    @property
    def live(self) -> tuple[int, ...]:
        return tuple(i for i, folded in enumerate(self.folded) if not folded)


@dataclass(frozen=True, slots=True)
class HRCNode:
    id: int
    parent_id: int
    actor: int | None
    street: int | None
    children: tuple[int, ...]
    incoming_actions: tuple[HRCAction, ...]

    @property
    def terminal(self) -> bool:
        return self.actor is None


@dataclass(frozen=True, slots=True)
class ImportedTree:
    settings: dict[str, Any]
    rules: ReplayRules
    nodes: tuple[HRCNode, ...]
    states: tuple[ReplayState, ...]
    root: int
    provenance: dict[str, Any]
    validation: dict[str, Any]

    def node_path(self, node_id: int) -> list[str]:
        """Return original edge slots from root; never action-amount guesses."""
        _require(type(node_id) is int and 0 <= node_id < len(self.nodes), "Node ID outside tree")
        result = []
        while node_id != self.root:
            node = self.nodes[node_id]
            result.append(str(self.nodes[node.parent_id].children.index(node_id)))
            node_id = node.parent_id
        return result[::-1]

    def get_node(self, path: list[str] | tuple[str, ...] | None = None) -> HRCNode:
        path = [] if path is None else path
        _require(isinstance(path, (list, tuple)) and len(path) <= 128,
                 "Node path must contain at most 128 edge-index strings")
        node = self.nodes[self.root]
        for token in path:
            _require(isinstance(token, str) and token.isascii() and token.isdigit() and len(token) <= 6,
                     "Node path entries must be edge-index strings")
            edge = int(token)
            _require(0 <= edge < len(node.children), "Node path selects a missing child")
            node = self.nodes[node.children[edge]]
        return node

    def describe_node(self, path: list[str] | tuple[str, ...] | None = None, *, node_id: int | None = None) -> dict[str, Any]:
        """Immutable GUI preview in BB; never consumes training RNG or budget."""
        if node_id is not None:
            _require(path is None, "Provide a path or node_id, not both")
            path = self.node_path(node_id)
        node = self.get_node(path)
        state = self.states[node.id]
        scale = self.rules.big_blind
        n = self.rules.players
        positions = (["BTN/SB", "BB"] if n == 2 else
                     [f"P{i+1}" for i in range(n-3)] + ["BTN", "SB", "BB"])
        actions = []
        for edge, child in enumerate(node.children):
            first = self.nodes[child].incoming_actions[0]
            cost = (first.amount - state.street_contributions[first.actor] if first.kind == 3 else
                    first.amount if first.kind == 2 else 0)
            amount_bb, cost_bb = first.amount / scale, cost / scale
            if first.kind == 0:
                label = "弃牌"
            elif first.kind == 1:
                label = "过牌"
            elif first.kind == 2:
                label = f"跟注 {cost_bb:g} BB" + (" · 全下" if first.allin else "")
            else:
                label = ("全下至" if first.allin else "加注至") + f" {amount_bb:g} BB"
            actions.append({"id": str(edge), "kind": first.name, "amount": amount_bb,
                            "cost": cost_bb, "label": label, "all_in": first.allin,
                            "child_id": child, "forced_suffix_count": len(self.nodes[child].incoming_actions)-1})
        return {"id": str(node.id), "hrc_node_id": node.id, "path": self.node_path(node.id),
                "actor": node.actor, "actor_name": positions[node.actor] if node.actor is not None else None,
                "street": state.street, "street_name": ("preflop", "flop", "turn", "river")[state.street],
                "pot": state.pot / scale, "current_bet": state.current_bet / scale,
                "minimum_raise_to": (state.current_bet + state.last_full_raise) / scale,
                "contributions": [x / scale for x in state.contributions],
                "street_contributions": [x / scale for x in state.street_contributions],
                "remaining": [x / scale for x in state.remaining], "folded": list(state.folded),
                "all_in": [not state.folded[i] and state.remaining[i] == 0 for i in range(n)],
                "terminal": node.terminal,
                "terminal_kind": ("fold_award" if len(state.live) == 1 else "showdown") if node.terminal else None,
                "actions": actions, "topology_source": "imported_hrc", "state_source": "independent_action_replay"}

    def compact_export(self) -> dict[str, Any]:
        """JSON-compatible native input; no saved regret, averages, or leaf EV.

        children/actions retain archive edge order. Each action is the FIRST
        action of that edge; its forced suffix has already been replayed into
        the child's state. Terminal contributions include folded dead money
        and uncalled excess: the settlement layer must return excess properly.
        """
        compact, terminals = [], []
        for node, state in zip(self.nodes, self.states):
            terminal_id = -1
            if node.terminal:
                terminal_id = len(terminals)
                terminals.append({
                    "id": terminal_id, "node_id": node.id,
                    "remaining": list(state.remaining),
                    "contributions": list(state.contributions),
                    "folded": list(state.folded), "live": list(state.live),
                    "live_mask": sum(1 << i for i in state.live),
                })
            actions = [self.nodes[c].incoming_actions[0].kind for c in node.children]
            special = (1 if self.nodes[node.children[1]].terminal else 2) if len(actions) > 1 and actions[1] == 1 else 0
            compact.append({
                "id": node.id, "actor": -1 if node.terminal else node.actor,
                "street": state.street, "buckets": 0 if node.terminal else self.rules.buckets[state.street],
                "children": list(node.children), "actions": actions,
                "terminal_id": terminal_id, "special": special,
            })
        return {"version": "hrc-topology-replay-v1", "root": self.root,
                "players": self.rules.players, "big_blind": self.rules.big_blind,
                "initial_stacks": list(self.rules.initial_stacks),
                "nodes": compact, "terminals": terminals,
                "provenance": dict(self.provenance), "validation": dict(self.validation)}


def _positive_int(value: Any, name: str) -> int:
    _require(type(value) is int and 0 < value <= (1 << 47), f"{name} must be a positive bounded integer")
    return value


def rules_from_settings(settings: dict[str, Any]) -> ReplayRules:
    """Fail closed for setup variants not yet independently verified."""
    _require(isinstance(settings, dict), "settings must be an object")
    _require("subtree" not in settings, "Fixed-board subtree imports have not been verified")
    hand = settings.get("handdata", {})
    _require(isinstance(hand, dict), "handdata must be an object")
    stacks = hand.get("stacks")
    _require(isinstance(stacks, list) and 2 <= len(stacks) <= 10, "Expected 2 to 10 stacks")
    stacks = tuple(_positive_int(x, "stack") for x in stacks)
    blinds = hand.get("blinds")
    _require(isinstance(blinds, list) and len(blinds) == 3, "Expected blinds [big, small, ante]")
    big, small = _positive_int(blinds[0], "big blind"), _positive_int(blinds[1], "small blind")
    _require(small <= big and type(blinds[2]) is int and blinds[2] == 0,
             "Replay currently supports positive SB<=BB and zero ante only")
    _require(hand.get("skipSb", False) is False and hand.get("movingBu", False) is False,
             "skipSb/movingBu setups have not been verified")
    _require(hand.get("straddleType", "OFF") == "OFF", "Straddles have not been verified")
    _require(min(stacks) > big, "Starting stacks at/below a blind have not been verified")
    model = settings.get("eqmodel", {})
    _require(isinstance(model, dict) and model.get("id") == "chipev" and model.get("raked", False) is False,
             "Native replay export currently supports unraked chipEV only")
    try:
        abstract = settings["engine"]["configuration"]["abstractions"]
        _require(isinstance(abstract, list) and len(abstract) == 4, "Expected four street abstraction entries")
        buckets = tuple(_positive_int(x["buckets"], "buckets") for x in abstract)
        _require(all(x["street"] == i for i, x in enumerate(abstract)), "Abstractions must be in street order")
        _require(buckets[0] == 169, "Only 169-class preflop abstraction is supported")
    except (KeyError, TypeError) as exc:
        raise TreeReplayError("Malformed abstraction configuration") from exc
    return ReplayRules(stacks, big, small, buckets)


def initial_state(rules: ReplayRules) -> ReplayState:
    n = rules.players
    street = [0] * n
    street[n - 2] = rules.small_blind
    street[n - 1] = rules.big_blind
    remaining = tuple(s - paid for s, paid in zip(rules.initial_stacks, street))
    return ReplayState(remaining, tuple(street), tuple(street), (False,) * n, 0,
                       rules.big_blind, rules.big_blind, (True,) * n,
                       (-1,) * n, 0)


def _assert_conservation(state: ReplayState, rules: ReplayRules) -> None:
    _require(all(r >= 0 and c >= 0 and 0 <= sc <= c and r + c == initial
                 for r, c, sc, initial in zip(state.remaining, state.contributions,
                                              state.street_contributions, rules.initial_stacks)),
             "Per-player chip conservation or nonnegative-state invariant failed")
    _require(sum(state.remaining) + state.pot == sum(rules.initial_stacks), "Total chip conservation failed")


def _advance_street(state: ReplayState, street: int, rules: ReplayRules) -> ReplayState:
    _require(street == state.street + 1 and 1 <= street <= 3, "Nonconsecutive street transition")
    _require(state.next_actor is None and not any(state.pending), "Street advanced before betting round closed")
    live = [i for i in range(rules.players) if not state.folded[i] and state.remaining[i] > 0]
    _require(len(state.live) > 1 and len(live) > 1, "New betting street with fewer than two players able to act")
    order = ([1, 0] if rules.players == 2 else list(range(rules.players - 2, rules.players)) + list(range(rules.players - 2)))
    pending = tuple(i in live for i in range(rules.players))
    first = next(i for i in order if pending[i])
    return replace(state, street=street, street_contributions=(0,) * rules.players,
                   current_bet=0, last_full_raise=rules.big_blind,
                   pending=pending, reopen_at=(-1,) * rules.players, next_actor=first)


def apply_action(state: ReplayState, action: HRCAction, rules: ReplayRules) -> ReplayState:
    """Replay a concrete action, including forced suffixes and round changes."""
    _require(action.kind in range(4) and 0 <= action.actor < rules.players and 0 <= action.street <= 3,
             "Action kind/actor/street outside domain")
    _require(type(action.amount) is int and action.amount >= 0, "Action amount must be a nonnegative integer")
    if action.street != state.street:
        state = _advance_street(state, action.street, rules)
    actor = action.actor
    _require(not state.folded[actor], "Folded player acted again")
    # HRC materializes a final forced check by the sole survivor (e.g. BB walks).
    sole_survivor_check = len(state.live) == 1 and action.kind == 1 and state.live[0] == actor
    _require(sole_survivor_check or state.next_actor == actor,
             f"Wrong actor: expected {state.next_actor}, got {actor}")
    _require(state.remaining[actor] > 0 or sole_survivor_check, "All-in player acted again")
    remaining, total, street_paid = list(state.remaining), list(state.contributions), list(state.street_contributions)
    folded, pending, reopen_at = list(state.folded), list(state.pending), list(state.reopen_at)
    owed = max(state.current_bet - street_paid[actor], 0)
    current_bet, last_full = state.current_bet, state.last_full_raise
    if action.kind == 0:
        _require(action.amount == 0 and not action.allin, "Fold carries amount/all-in flag")
        folded[actor] = True
    elif action.kind == 1:
        _require(action.amount == 0 and not action.allin and (owed == 0 or sole_survivor_check),
                 "Check faces a bet or carries amount/all-in flag")
    else:
        if action.kind == 2:
            cost = min(owed, remaining[actor])
            _require(cost > 0 and action.amount == cost, "Call amount is not the exact legal increment")
        else:
            _require(action.amount > current_bet, "Raise does not exceed current bet")
            _require(reopen_at[actor] < 0 or current_bet >= reopen_at[actor], "Action has not reopened for a raise")
            cost = action.amount - street_paid[actor]
            _require(0 < cost <= remaining[actor], "Raise exceeds stack or does not invest chips")
            increment = action.amount - current_bet
            _require(increment >= last_full or cost == remaining[actor], "Non-all-in raise below minimum")
            _require(sum(not folded[i] and remaining[i] > 0 for i in range(rules.players) if i != actor) > 0,
                     "Raise has no opponent with chips to respond")
            if increment >= last_full:
                last_full = increment
            current_bet = action.amount
            pending = [not folded[i] and remaining[i] > 0 for i in range(rules.players)]
        remaining[actor] -= cost
        total[actor] += cost
        street_paid[actor] += cost
        _require(action.allin == (remaining[actor] == 0), "All-in flag disagrees with remaining stack")
    pending[actor] = False
    reopen_at[actor] = current_bet + last_full
    live = [i for i in range(rules.players) if not folded[i]]
    if len(live) <= 1:
        pending = [False] * rules.players
    else:
        pending = [p and not folded[i] and remaining[i] > 0 for i, p in enumerate(pending)]
    next_actor = next((i for step in range(1, rules.players + 1)
                       if pending[i := (actor + step) % rules.players]), None)
    result = ReplayState(tuple(remaining), tuple(total), tuple(street_paid), tuple(folded), state.street,
                         current_bet, last_full, tuple(pending), tuple(reopen_at), next_actor)
    _assert_conservation(result, rules)
    return result


def parse_gametree(data: bytes) -> tuple[tuple[HRCNode, ...], int]:
    """Bounded binary parser for the observed HRC 4.1 tree record format."""
    position = 0
    def read(fmt: str):
        nonlocal position
        size = struct.calcsize(fmt)
        _require(position + size <= len(data), f"Truncated tree record at byte {position}")
        result = struct.unpack_from(fmt, data, position)
        position += size
        return result
    count, = read("<i")
    _require(1 <= count <= 1_000_000, "Tree node count outside supported bounds")
    nodes: list[HRCNode | None] = [None] * count
    for _ in range(count):
        node_id, parent, kind, length, child_count = read("<iiBbh")
        _require(0 <= node_id < count and nodes[node_id] is None, "Invalid or duplicate node ID")
        _require(kind in (1, 2) and length >= 0 and child_count >= 0, "Invalid node record header")
        if kind == 1:
            street, actor = read("<bb")
            _require(0 <= street <= 3 and 0 <= actor <= 9 and child_count > 0, "Invalid decision header")
        else:
            actor = street = None
            _require(child_count == 0, "Terminal node declares children")
        incoming = tuple(HRCAction.decode(w) for w in read("<" + "Q" * length))
        children = tuple(read("<" + "i" * child_count))
        _require(all(0 <= c < count for c in children), "Missing/negative child slots are not supported")
        nodes[node_id] = HRCNode(node_id, parent, actor, street, children, incoming)
    _require(position == len(data), "Trailing bytes after gametree")
    roots = [n.id for n in nodes if n.parent_id == -1]
    _require(len(roots) == 1, "Expected exactly one root")
    queue, seen = deque([roots[0]]), set()
    while queue:
        node_id = queue.popleft()
        _require(node_id not in seen, "Tree cycle or reused child")
        seen.add(node_id)
        for child in nodes[node_id].children:
            _require(nodes[child].parent_id == node_id, "Parent/child mismatch")
            queue.append(child)
    _require(len(seen) == count, "Unreachable tree nodes")
    return tuple(nodes), roots[0]


def replay_tree(nodes: tuple[HRCNode, ...], root: int, rules: ReplayRules) -> tuple[tuple[ReplayState, ...], dict[str, Any]]:
    states: list[ReplayState | None] = [None] * len(nodes)
    queue = deque([(root, initial_state(rules))])
    actions = forced = transitions = 0
    while queue:
        node_id, state = queue.popleft()
        node = nodes[node_id]
        try:
            if node_id != root:
                _require(bool(node.incoming_actions), "Child has no incoming decision action")
                parent = nodes[node.parent_id]
                first = node.incoming_actions[0]
                _require(first.actor == parent.actor and first.street == parent.street,
                         "Edge's first action does not belong to parent decision")
            for action in node.incoming_actions:
                transitions += action.street != state.street
                state = apply_action(state, action, rules)
                actions += 1
            forced += max(0, len(node.incoming_actions) - (node_id != root))
            if not node.terminal:
                if node.street != state.street:
                    state = _advance_street(state, node.street, rules)
                    transitions += 1
                _require(node.actor == state.next_actor, f"Node actor mismatch: {node.actor} != {state.next_actor}")
                _require(len(state.live) > 1, "Decision after only one survivor remains")
            else:
                _require(state.next_actor is None, "Leaf reached before pending actions completed")
                _require(state.street == 3 or len(state.live) <= 1 or
                         sum(not state.folded[i] and state.remaining[i] > 0 for i in range(rules.players)) <= 1,
                         "Leaf ends before future betting streets without all-in/fold closure")
                for level in set(state.contributions) - {0}:
                    _require(any(not state.folded[i] and paid >= level for i, paid in enumerate(state.contributions)),
                             "Positive pot layer has no eligible player")
            _assert_conservation(state, rules)
        except TreeReplayError as exc:
            raise TreeReplayError(f"node {node_id}: {exc}") from exc
        states[node_id] = state
        for child in node.children:
            queue.append((child, state))
    counts = Counter(n.street for n in nodes if not n.terminal)
    return tuple(states), {"nodes": len(nodes), "edges": len(nodes) - 1, "decision_nodes": sum(not n.terminal for n in nodes),
                           "terminal_nodes": sum(n.terminal for n in nodes), "decision_nodes_by_street": [counts[i] for i in range(4)],
                           "replayed_actions": actions, "forced_suffix_actions": forced, "street_transitions": transitions,
                           "all_nodes_conserve_chips": True, "all_actions_rule_checked": True,
                           "all_terminal_pot_layers_have_eligible_players": True,
                           "topology_source": "imported from HRC archive; not independently generated"}


def load_hrc_tree(path: str | Path) -> ImportedTree:
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for name, limit in (("settings.json", 1_000_000), ("gametree.dat", 200_000_000)):
            _require(names.count(name) == 1, f"Missing/duplicate {name}")
            _require(archive.getinfo(name).file_size <= limit, f"Oversized {name}")
        # Explicitly never open nodedata.dat, state.json, or idx.dat.
        settings_bytes, tree_bytes = archive.read("settings.json"), archive.read("gametree.dat")
    try:
        settings = json.loads(settings_bytes)
    except (ValueError, UnicodeError) as exc:
        raise TreeReplayError("Invalid settings JSON") from exc
    rules = rules_from_settings(settings)
    nodes, root = parse_gametree(tree_bytes)
    states, validation = replay_tree(nodes, root, rules)
    provenance = {"source_path": str(path.resolve()),
                  "settings_sha256": hashlib.sha256(settings_bytes).hexdigest(),
                  "gametree_sha256": hashlib.sha256(tree_bytes).hexdigest(),
                  "read_members": ["settings.json", "gametree.dat"],
                  "saved_strategy_loaded": False, "saved_terminal_utilities_loaded": False}
    return ImportedTree(settings, rules, nodes, states, root, provenance, validation)
