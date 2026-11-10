"""Generate a four-street research tree from explicit settings, never a saved tree.

Independent Python implementation of the audited lB/lC/mF/ml rule semantics and
the simple preflop/postflop sizing policies. No HRC executable, JS runtime, saved
policy or saved terminal equity is used. Money stays in integer chip units.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import copy
import hashlib
import json
import math
import re
import time
from typing import Callable

from .hrc_tree import HRCAction, HRCNode, ImportedTree, ReplayRules, ReplayState, TreeReplayError
from . import hrc_general_policy as general


class TreeBuildError(TreeReplayError):
    pass


def _require(ok, message):
    if not ok:
        raise TreeBuildError(message)


def default_settings(players=6, stack=200000, big_blind=10000, *,preflop_policy='simple',postflop_policy='simple'):
    """Explicit simple-policy config; stack may also be a per-seat integer list."""
    config={
        "handdata": {"stacks": [stack]*players if isinstance(stack, int) else list(stack),
                     "blinds": [big_blind, big_blind//2, 0], "skipSb": False, "movingBu": False,
                     "anteType": "BB_ANTE_ANTE_FIRST", "straddleType": "OFF"},
        "eqmodel": {"id": "chipev", "raked": False},
        "treeconfig": {"mode": "ui", "preflop": {"id": "preflop.settings.simple", "settings": {
            "PREFLOP_SIZES": ["2.0bb, all-in", "all-in", "all-in", "all-in"],
            "PREFLOP_ALLIN_THRESHOLD": 40.0, "ALLOWED_FLATS_PER_RAISE": [0, 1, 0, 0, 0], "ALLOW_SB_COMPLETE": False}},
            "postflop": {"id": "postflop.settings.simple", "settings": {
                "POSTFLOP_GEO": [[66.0], [66.0]], "POSTFLOP_ADD_ALLIN_SPR": [5.0, 5.0],
                "POSTFLOP_ADD_FLOP_BET_POT": [[], []], "POSTFLOP_ADD_FLOP_CBET_POT": [[], []],
                "POSTFLOP_ADD_FLOP_DONK_POT": [[], []], "POSTFLOP_ADD_FLOP_RAISE_POT": [[], []],
                "POSTFLOP_ALLOW_DONK": [False, False], "POSTFLOP_ALLOW_DONK_PREV_AGGRESSION": [True, True],
                "POSTFLOP_FORCE_CHECKDOWN_AFTER": [3, 3, 2, 1, 0, 0, 0, 0, 0],
                "POSTFLOP_MAX_BETS_PER_STREET": [-1, -1]}}},
        "engine": {"type": "montecarlo", "maxactive": 4, "configuration": {
            "abstractions": [{"street": i, "buckets": b} for i, b in enumerate([169, 1024, 256, 256])]}}}
    for street,policy in (('preflop',preflop_policy),('postflop',postflop_policy)):
        _require(policy in ('simple','general'),'Unknown built-in tree policy')
        if policy=='general':config['treeconfig'][street]={'id':f'{street}.settings.general','settings':general.defaults(street)}
    return config


@dataclass(frozen=True, slots=True)
class GeneratedState(ReplayState):
    dead_money: int = 0
    minimum_raise_to: int = -1
    participant_mask: int = 0

    @property
    def pot(self):
        return sum(self.contributions) + self.dead_money


@dataclass(frozen=True, slots=True)
class GeneratedTree(ImportedTree):
    def describe_node(self, path=None, *, node_id=None):
        result = ImportedTree.describe_node(self, path, node_id=node_id)
        state = self.states[result["hrc_node_id"]]
        result["minimum_raise_to"] = state.minimum_raise_to / self.rules.big_blind if state.minimum_raise_to > 0 else None
        result["topology_source"] = "independently_generated"
        result["state_source"] = "independent_hrc_compatible_rules"
        result["dead_money"] = state.dead_money / self.rules.big_blind
        return result

    def compact_export(self):
        result = ImportedTree.compact_export(self)
        # Runtime timing belongs to UI/report diagnostics, never checkpoint identity.
        result["validation"].pop("seconds", None)
        for terminal in result["terminals"]:
            terminal["dead_money"] = self.states[terminal["node_id"]].dead_money
        return result


@dataclass(frozen=True, slots=True)
class _State:
    remaining: tuple[int, ...]
    street_paid: tuple[int, ...]
    dead_paid: tuple[int, ...]
    dead_money: int = 0
    folded: int = 0
    participants: int = 0
    street: int = 0
    bets: int = 1
    flats: int = 0
    stop: int = -1

    @property
    def current_bet(self):
        return max(self.street_paid)

    @property
    def live_count(self):
        return sum(not self.folded & (1 << i) and x > 0 for i, x in enumerate(self.remaining))

    @property
    def pot(self):
        return sum(self.street_paid) + sum(self.dead_paid) + self.dead_money


@dataclass(frozen=True, slots=True)
class _Context:
    state: _State
    history: tuple[HRCAction, ...]
    compressed: bool = False


class _Builder:
    def __init__(self, settings, budget, cancel, progress, special_fold_mode):
        self.settings = copy.deepcopy(settings)
        _require(isinstance(settings, dict), "Tree settings must be a dictionary")
        _require(type(budget) is int and 1 <= budget <= 2000000, "node_budget must be an integer in 1..2000000")
        self.budget, self.cancel, self.progress = budget, cancel, progress
        hand = self.settings.get("handdata", {})
        stacks = hand.get("stacks")
        _require(isinstance(stacks, list) and 2 <= len(stacks) <= 10, "Expected 2..10 positive integer initial stacks")
        _require(all(type(x) is int and 0 < x <= (1 << 47) for x in stacks), "Initial stacks must be positive bounded integers")
        self.n, self.stacks = len(stacks), tuple(stacks)
        blinds = hand.get("blinds")
        _require(isinstance(blinds, list) and len(blinds) == 3 and all(type(x) is int and 0 <= x <= (1 << 47) for x in blinds), "Expected nonnegative integer [BB,SB,ante]")
        self.bb, self.sb, self.ante = blinds
        _require(self.bb > 0 and self.sb <= self.bb, "Require positive BB and 0<=SB<=BB")
        self.skip_sb = hand.get("skipSb", False)
        self.moving_button=hand.get('movingBu',False)
        _require(type(self.skip_sb) is bool and type(self.moving_button) is bool, "skipSb and movingBu must be boolean")
        self.ante_type = hand.get("anteType", "REGULAR")
        _require(self.ante_type in {"REGULAR", "BB_ANTE_ANTE_FIRST", "BB_ANTE_BLINDS_FIRST", "BB_ANTE_BLIND_FIRST"}, "Unknown ante type")
        self.straddle = hand.get("straddleType", "OFF")
        _require(self.straddle in {"OFF", "SINGLE", "DOUBLE", "BUTTON"}, "Unknown straddle type")
        _require(self.straddle == "OFF" or self.n >= 3, "Straddles require at least three seats")
        self.button = 0 if self.n == 2 else self.n - (2 if self.skip_sb else 3)
        self.base = self.bb * (4 if self.straddle == "DOUBLE" else 2 if self.straddle != "OFF" else 1)
        tree = self.settings.get("treeconfig", {})
        _require(tree.get("mode") == "ui", "Only explicit bundled-policy settings are implemented; arbitrary JavaScript is not executed")
        pre, post = tree.get("preflop", {}), tree.get("postflop", {})
        _require(pre.get('id') in ('preflop.settings.simple','preflop.settings.general') and post.get('id') in ('postflop.settings.simple','postflop.settings.general'), 'Unknown bundled tree policy')
        self.pre_general=pre['id'].endswith('.general');self.post_general=post['id'].endswith('.general')
        defaults = default_settings(self.n,preflop_policy='general' if self.pre_general else 'simple',postflop_policy='general' if self.post_general else 'simple')["treeconfig"]
        self.pre = {**defaults["preflop"]["settings"], **pre.get("settings", {})}
        self.post = {**defaults["postflop"]["settings"], **post.get("settings", {})}
        _require(set(self.pre) == set(defaults["preflop"]["settings"]) and set(self.post) == set(defaults["postflop"]["settings"]), "Unknown bundled-policy setting")
        self._validate_policy()
        engine = self.settings.get("engine", {})
        self.active_limit = engine.get("maxactive", 4)
        _require(type(self.active_limit) is int and 2 <= self.active_limit <= 10, "maxactive must lie in 2..10")
        abstract = engine.get("configuration", {}).get("abstractions")
        _require(isinstance(abstract, list) and len(abstract) == 4, "Four street abstraction specifications are required")
        buckets = tuple(a.get("buckets") for a in abstract)
        _require(all(a.get("street") == i for i, a in enumerate(abstract)) and buckets[0] == 169 and all(type(b) is int and 0 < b <= 16384 for b in buckets), "Invalid abstraction bucket dimensions")
        self.rules = ReplayRules(self.stacks, self.bb, self.sb, buckets)
        if special_fold_mode is None:
            structure = self.settings.get("eqmodel", {}).get("structure", {})
            special_fold_mode = "compressed" if structure.get("bountyType", "NONE") != "NONE" else "checkdown"
        _require(special_fold_mode in {"none", "checkdown", "compressed", "ordinary"}, "Unknown check/fold counterfactual mode")
        self.special = special_fold_mode
        self.nodes, self.states = [], []
        self.started = time.perf_counter()

    def _validate_policy(self):
        def finite(x): return type(x) in (int, float) and math.isfinite(x)
        try:general.validate(self.pre if self.pre_general else None,self.post if self.post_general else None,self._parse_sizes)
        except ValueError as exc:raise TreeBuildError(str(exc)) from exc
        if not self.pre_general:
            _require(isinstance(self.pre["PREFLOP_SIZES"], list) and self.pre["PREFLOP_SIZES"], "At least one preflop size row is required")
            for size in self.pre["PREFLOP_SIZES"]:self._parse_sizes(size)
            _require(finite(self.pre["PREFLOP_ALLIN_THRESHOLD"]) and self.pre["PREFLOP_ALLIN_THRESHOLD"] >= 0, "Invalid preflop all-in threshold")
            _require(type(self.pre["ALLOW_SB_COMPLETE"]) is bool, "ALLOW_SB_COMPLETE must be boolean")
            _require(isinstance(self.pre["ALLOWED_FLATS_PER_RAISE"], list) and all(type(x) is int and x >= 0 for x in self.pre["ALLOWED_FLATS_PER_RAISE"]), "Flat limits must be nonnegative integers")
        for key, value in (() if self.post_general else self.post.items()):
            _require(isinstance(value, list), f"{key} must be an array")
            if key == "POSTFLOP_FORCE_CHECKDOWN_AFTER":
                _require(all(type(x) is int and 0 <= x <= 3 for x in value), "Checkdown streets must lie in 0..3")
            elif key in {"POSTFLOP_ALLOW_DONK", "POSTFLOP_ALLOW_DONK_PREV_AGGRESSION"}:
                _require(len(value) == 2 and all(type(x) is bool for x in value), f"Invalid {key}")
            elif key == "POSTFLOP_MAX_BETS_PER_STREET":
                _require(len(value) == 2 and all(type(x) is int and x >= -1 for x in value), f"Invalid {key}")
            elif key == "POSTFLOP_ADD_ALLIN_SPR":
                _require(len(value) == 2 and all(finite(x) for x in value), f"Invalid {key}")
            else:
                _require(len(value) == 2 and all(isinstance(row, list) and all(finite(x) and x >= 0 for x in row) for row in value), f"Invalid {key}")
                if key == "POSTFLOP_GEO":
                    _require(all(x > 0 for row in value for x in row), "Geometric hints must be positive")

    @staticmethod
    def _parse_sizes(text):
        _require(isinstance(text, str), "Preflop sizing rows must be strings")
        text = text.lower()
        if not text:
            return [[("allin", 0.0)]]
        _require(text not in {"none", "-"}, "The original simple preflop parser does not support '-' or 'none'")
        allin=bool(re.search(r'all-in|allin|ai',text));text=re.sub(r'all-in|allin|ai','',text)
        _require(re.fullmatch(r'[0-9.,+x% b]*',text) is not None,'Unsupported preflop sizing syntax')
        text=re.sub(r'\+ +','+',text.replace('+',' +'))
        output=[];row=[]
        for token in re.split(r'[, ]+',text):
            if not token:continue
            if not token.startswith('+') and row:output.append(row);row=[]
            match=re.fullmatch(r'\+?(\d+(?:\.\d*)?|\.\d+)(bb|x|%)?',token)
            _require(match is not None,f'Unsupported preflop sizing syntax: {token}')
            number,unit=float(match[1]),match[2] or 'bb'
            _require(math.isfinite(number),'Sizing must be finite')
            _require(unit!='%' or not row,'Pot percentage is only permitted as a base preflop sizing')
            row.append((unit,number))
        if row:output.append(row)
        if allin:output.append([('allin',0.)])
        return output

    def initial(self):
        remaining, paid, dead = list(self.stacks), [0]*self.n, [0]*self.n
        dead_money = 0
        def post(seat, amount, active):
            _require(amount >= 0, "A straddle would subtract chips already posted")
            amount = min(amount, remaining[seat]); remaining[seat] -= amount
            (paid if active else dead)[seat] += amount
        if self.ante_type == "REGULAR":
            for i in range(self.n): post(i, self.ante, False)
        elif self.ante_type == "BB_ANTE_ANTE_FIRST":
            dead_money = min(remaining[-1], self.ante); remaining[-1] -= dead_money
        if not self.skip_sb: post(self.n-2, self.sb, True)
        post(self.n-1, self.bb, True)
        if self.ante_type in {"BB_ANTE_BLIND_FIRST", "BB_ANTE_BLINDS_FIRST"}:
            dead_money = min(remaining[-1], self.ante); remaining[-1] -= dead_money
        if self.straddle in {"SINGLE", "DOUBLE"}: post(0, 2*self.bb-paid[0], True)
        if self.straddle == "DOUBLE": post(1, 4*self.bb-paid[1], True)
        if self.straddle == "BUTTON": post(self.button, 2*self.bb-paid[self.button], True)
        return _Context(_State(tuple(remaining), tuple(paid), tuple(dead), dead_money), ())

    def actor(self, context):
        state = context.state
        current = [a for a in context.history if a.street == state.street]
        last_raise = next((a for a in reversed(current) if a.kind == 3), None)
        if current:
            start = current[-1].actor + 1
        elif state.street == 0:
            start = {"OFF": 0, "SINGLE": 1, "DOUBLE": 2, "BUTTON": self.button+1}[self.straddle]
        else:
            start = 1 if self.n == 2 else self.n - (1 if self.skip_sb else 2)
        acted = {a.actor for a in current}
        for offset in range(self.n):
            seat = (start+offset) % self.n
            if last_raise is not None and seat == last_raise.actor: return None
            if state.folded & (1 << seat): continue
            if not state.participants & (1 << seat): return seat
            if state.remaining[seat] > 0:
                if state.current_bet > state.street_paid[seat]: return seat
                if seat not in acted and state.live_count > 1: return seat
        return None

    def limits(self, context, actor):
        if actor is None: return -1, -1
        s = context.state
        maximum = max((s.remaining[i]+s.street_paid[i] for i in range(self.n) if i != actor and not s.folded & (1 << i)), default=0)
        effective_maximum = min(maximum, s.remaining[actor]+s.street_paid[actor])
        if s.remaining[actor]+s.street_paid[actor] <= s.current_bet or s.current_bet == maximum or s.live_count == 1:
            return -1, effective_maximum
        minimum, previous = (2*self.base, self.base) if s.street == 0 else (self.base, 0)
        current = [a for a in context.history if a.street == s.street]
        raises = [i for i, a in enumerate(current) if a.kind == 3]
        if raises:
            accepted = 0
            for i in raises:
                if current[i].amount >= minimum:
                    minimum, previous, accepted = 2*current[i].amount-previous, current[i].amount, i
            if any(a.actor == actor for a in current[accepted:]): return -1, effective_maximum
        return minimum, effective_maximum

    @staticmethod
    def can_check(state, actor):
        return state.bets == 0 if state.street > 0 else state.street_paid[actor] >= state.current_bet

    def apply(self, context, kind, amount=0):
        s, actor = context.state, self.actor(context)
        _require(actor is not None and actor != s.stop, "Illegal generated actor")
        remaining, paid, dead = list(s.remaining), list(s.street_paid), list(s.dead_paid)
        allin, participants, folded, stop, bets, flats = False, s.participants, s.folded, s.stop, s.bets, s.flats
        if kind == 0:
            dead[actor] += paid[actor]; paid[actor] = 0; folded |= 1 << actor
        elif kind == 1:
            _require(self.can_check(s, actor), "Illegal generated check")
            participants |= 1 << actor
            if stop < 0: stop = actor
        elif kind == 2:
            due = 0 if self.can_check(s, actor) else max(s.current_bet, self.bb if s.street == 0 else 0)-paid[actor]
            amount = min(remaining[actor], due)
            allin = amount >= remaining[actor]
            remaining[actor] -= amount; paid[actor] += amount; participants |= 1 << actor; flats += 1
            if stop < 0: stop = actor
        else:
            minimum, maximum = self.limits(context, actor)
            _require(minimum > 0 and min(minimum, maximum) <= amount <= maximum, "Illegal generated raise")
            # mF clamps a requested candidate first, but lB applies its minimum
            # again and checks the actor's own stack BEFORE the opponent cap.
            # For short effective stacks this can intentionally leave an
            # uncalled excess; reproduce the observed bytes, not ideal rules.
            amount = max(amount, minimum)
            own = remaining[actor]+paid[actor]
            opponent = max((s.remaining[i]+s.street_paid[i] for i in range(self.n) if i != actor and not s.folded & (1 << i)), default=0)
            if amount >= own:
                amount, allin = own, True
            else:
                allin = amount >= opponent
                amount = min(amount, opponent)
            remaining[actor] -= amount-paid[actor]; paid[actor] = amount
            participants |= 1 << actor; stop = actor; bets += 1; flats = 0
        _require(min(remaining) >= 0, "Generated negative remaining stack")
        action = HRCAction(kind, actor, s.street, amount, allin)
        state = _State(tuple(remaining), tuple(paid), tuple(dead), s.dead_money, folded, participants, s.street, bets, flats, stop)
        return _Context(state, context.history+(action,), context.compressed)

    def advance(self, context):
        s = context.state
        _require(self.actor(context) is None and s.street < 3, "Cannot advance unfinished/river round")
        _require(s.participants | s.folded == (1 << self.n)-1, "Not all players have acted")
        return replace(context, state=replace(s, street_paid=(0,)*self.n, dead_paid=tuple(a+b for a,b in zip(s.street_paid,s.dead_paid)), street=s.street+1, bets=0, flats=0, stop=-1))

    def next_street(self, context):
        s = context.state
        index = s.live_count-2
        last = self.post["POSTFLOP_FORCE_CHECKDOWN_AFTER"]
        return s.street < 3 and 0 <= index < len(last) and s.street < last[index]

    def normalize(self, context):
        while True:
            actor = self.actor(context)
            if actor is None and self.next_street(context): context = self.advance(context)
            elif actor is not None and context.state.remaining[actor] == 0: context = self.apply(context, 2)
            else: return context

    def _pot_geometry(self, context, actor):
        s = context.state
        current = s.current_bet
        opponent = max((s.remaining[i]+s.street_paid[i] for i in range(self.n) if i != actor and not s.folded & (1 << i)), default=0)
        call = current-s.street_paid[actor]
        pot = s.pot+call
        effective = min(s.remaining[actor]-call, opponent-current)
        _require(pot > 0, "Invalid geometric sizing context")
        return current, pot, effective

    def geometric(self, context, actor, hint):
        minimum,maximum=self.limits(context,actor)
        if maximum<=minimum:return maximum
        current, pot, effective = self._pot_geometry(context, actor)
        ratio = (pot+2*effective)/pot
        count = math.log(ratio)/math.log(1+2*hint)
        higher, lower = math.ceil(count), max(1, math.floor(count))
        small = (math.pow(ratio, 1/higher)-1)/2 if higher else 0
        big = (math.pow(ratio, 1/lower)-1)/2
        value = big if abs(small-hint) > abs(big-hint) else small
        minimum, maximum = self.limits(context, actor)
        return min(max(current+math.ceil(pot*value), minimum), maximum)

    def pot_size(self, context, actor, fraction):
        current, pot, _ = self._pot_geometry(context, actor)
        minimum, maximum = self.limits(context, actor)
        return min(max(current+math.floor(fraction*pot+.5), minimum), maximum)

    def is_donk(self, context, actor):
        s = context.state
        if s.bets: return False
        seen = set()
        for action in reversed(context.history):
            if action.street < s.street-1: return False
            if action.kind == 3:
                return action.actor != actor and s.remaining[action.actor] > 0 and action.actor not in seen
            seen.add(action.actor)
        return False

    def sizings(self, context, actor):
        s = context.state
        minimum, maximum = self.limits(context, actor)
        if minimum <= 0: return []
        if s.street == 0:
            if self.pre_general and s.bets>=5:return [maximum]
            rows = self.pre.get("PREFLOP_SIZES",[])
            text=general.pre_text(self,context,actor) if self.pre_general else rows[s.bets-1] if s.bets-1<len(rows) else 'all-in'
            specs = self._parse_sizes(text)
            def value(term):
                unit, number = term
                if unit == "allin": return maximum
                if unit == "%": return self.pot_size(context, actor, number*.01)
                if unit == "x":
                    last = next((a.amount for a in reversed(context.history) if a.kind == 3), self.base)
                    return math.floor(number * (self.base if s.bets <= 1 else last) + .5)
                return math.floor(number*self.bb+.5)
            sizes = []
            for spec in specs:
                size = value(spec[0])
                if len(spec) > 1:
                    size += sum(value(spec[min(i, len(spec)-1)]) for i in range(1, s.flats+1))
                size = min(max(size, minimum), maximum)
                sizes.append(maximum if size >= maximum*self.pre["PREFLOP_ALLIN_THRESHOLD"]/100 else size)
            if self.pre_general and (self.pre['PREFLOP_ADD_ALLIN_SPR']<0 or general.spr(self,context,actor)<=self.pre['PREFLOP_ADD_ALLIN_SPR']):sizes.append(maximum)
        else:
            idx = 0 if s.live_count == 2 else 1
            donk = self.is_donk(context, actor)
            if donk and not self.post["POSTFLOP_ALLOW_DONK"][idx]:
                if not self.post["POSTFLOP_ALLOW_DONK_PREV_AGGRESSION"][idx] or not any(a.kind == 3 and a.actor == actor for a in context.history): return []
            cap = self.post["POSTFLOP_MAX_BETS_PER_STREET"][idx]
            if cap >= 0 and s.bets >= cap: return [maximum]
            pots = []
            if s.street == 1 and not self.post_general:
                if s.bets == 0:
                    last = next((a for a in reversed(context.history) if a.kind == 3), None)
                    key = "CBET" if last is not None and last.actor == actor else "DONK" if donk else None
                    if key: pots = self.post[f"POSTFLOP_ADD_FLOP_{key}_POT"][idx]
                    if not pots: pots = self.post["POSTFLOP_ADD_FLOP_BET_POT"][idx]
                else: pots = self.post["POSTFLOP_ADD_FLOP_RAISE_POT"][idx]
            sizes = general.post_sizes(self,context,actor,general.post_text(self,context,actor)) if self.post_general else [self.pot_size(context, actor, x/100) for x in pots] if pots else [self.geometric(context, actor, x/100) for x in self.post["POSTFLOP_GEO"][idx]]
            _, pot, effective = self._pot_geometry(context, actor)
            threshold = self.post["POSTFLOP_ADD_ALLIN_SPR"][idx]
            if threshold < 0 or general.spr(self,context,actor) <= threshold: sizes.append(maximum)
            if context.compressed:
                geo = self.geometric(context, actor, .75)
                sizes = [maximum if abs(maximum-x) <= abs(geo-x) else geo for x in sizes]
        return sorted({min(max(x, minimum), maximum) for x in sizes})

    def children(self, context):
        actor, s = self.actor(context), context.state
        if actor is None: return []
        count = sum(s.remaining[i] == 0 or bool(s.participants & (1 << i)) for i in range(self.n))
        if not s.participants & (1 << actor) and count >= self.active_limit:
            return [self.normalize(self.apply(context, 0))]
        sizes = self.sizings(context, actor)
        children = []
        if self.can_check(s, actor):
            special = self.special if s.street == 0 and not context.compressed else "none"
            if sizes and special != "none":
                folded = self.apply(context, 0)
                if special == "checkdown":
                    while True:
                        seat = self.actor(folded)
                        if seat is not None: folded = self.apply(folded, 1 if self.can_check(folded.state, seat) else 0)
                        elif folded.state.street < 3: folded = self.advance(folded)
                        else: break
                elif special == "compressed": folded = replace(folded, compressed=True)
                children.append(self.normalize(folded))
            children.append(self.normalize(self.apply(context, 1)))
        else:
            children.append(self.normalize(self.apply(context, 0)))
            maximum_other = max((s.remaining[i]+s.street_paid[i] for i in range(self.n) if i != actor and not s.folded & (1 << i)), default=0)
            ordinary = s.current_bet < min(s.remaining[actor]+s.street_paid[actor], maximum_other) and bool(sizes)
            allow = True
            if ordinary:
                if not s.participants & (1 << actor) and s.bets <= 1:
                    counted = sum(s.remaining[i] == 0 or bool(s.participants & (1 << i)) or s.street_paid[i] == s.current_bet for i in range(self.n))
                    allow = counted < self.active_limit
                if s.street == 0:
                    flats = self.pre["ALLOWED_FLATS_PER_RAISE"]
                    allow &= general.can_flat(self,context,actor) if self.pre_general else (s.bets == 1 and self.pre["ALLOW_SB_COMPLETE"] and s.street_paid[actor] > 0) or (s.bets-1 < len(flats) and s.flats < flats[s.bets-1])
            if allow: children.append(self.normalize(self.apply(context, 2)))
        children.extend(self.normalize(self.apply(context, 3, size)) for size in sizes)
        return children

    def public_state(self, context, terminal):
        s, actor = context.state, self.actor(context)
        minimum, _ = self.limits(context, actor)
        street = context.history[-1].street if terminal and context.history else s.street
        current = [a for a in context.history if a.street == s.street]
        acted = {a.actor for a in current}
        last_raise = next((a for a in reversed(current) if a.kind == 3), None)
        pending = [False]*self.n
        if actor is not None:
            for offset in range(self.n):
                i = (actor+offset) % self.n
                if last_raise is not None and i == last_raise.actor: break
                pending[i] = not s.folded & (1 << i) and (not s.participants & (1 << i) or
                    (s.remaining[i] > 0 and (s.current_bet > s.street_paid[i] or (i not in acted and s.live_count > 1))))
        next_full, accepted = (2*self.base, self.base) if s.street == 0 else (self.base, 0)
        for action in current:
            if action.kind == 3 and action.amount >= next_full:
                next_full, accepted = 2*action.amount-accepted, action.amount
        reopen = tuple(s.current_bet if self.limits(context, i)[0] > 0 else next_full for i in range(self.n))
        return GeneratedState(s.remaining, tuple(a+b for a,b in zip(s.street_paid,s.dead_paid)), s.street_paid,
            tuple(bool(s.folded & (1 << i)) for i in range(self.n)), street, s.current_bet,
            max(0, minimum-s.current_bet) if minimum > 0 else self.base, tuple(pending), reopen,
            actor, s.dead_money, minimum, s.participants)

    def visit(self, context, parent, prior_length):
        if self.cancel and self.cancel(): raise TreeBuildError("Tree construction cancelled")
        while True:
            _require(len(context.history) <= 256, "Tree exceeds the 256-action depth limit; reduce raise branches or stack depth")
            children = self.children(context)
            if len(children) != 1: break
            context = children[0]
        _require(len(children) <= 16, "A native decision supports at most 16 actions; reduce sizing choices")
        _require(len(self.nodes) < self.budget, f"Tree exceeds node_budget={self.budget}; reduce branch sizes or participants")
        index = len(self.nodes)
        self.nodes.append(None)
        self.states.append(self.public_state(context, not children))
        if self.progress and index % 1000 == 0: self.progress({"nodes": index+1, "node_budget": self.budget})
        ids = tuple(self.visit(child, index, len(context.history)) for child in children)
        self.nodes[index] = HRCNode(index, parent, self.actor(context) if children else None,
                                   context.state.street if children else None, ids, context.history[prior_length:])
        return index

    def build(self):
        self.visit(self.normalize(self.initial()), -1, 0)
        for state in self.states:
            _require(sum(state.remaining)+sum(state.contributions)+state.dead_money == sum(self.stacks), "Generated state violates chip conservation")
        settings_sha = hashlib.sha256(json.dumps(self.settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return GeneratedTree(self.settings, self.rules, tuple(self.nodes), tuple(self.states), 0,
            {"kind": "independently_generated", "settings_sha256": settings_sha, "builder": "python-general-policy-v1" if self.pre_general or self.post_general else "python-simple-policy-v1", "saved_tree_read": False, "special_fold_mode": self.special},
            {"nodes": len(self.nodes), "decisions": sum(not n.terminal for n in self.nodes), "terminals": sum(n.terminal for n in self.nodes),
             "chip_conservation": True, "seconds": time.perf_counter()-self.started, "node_budget": self.budget})


def build_tree(settings, *, node_budget=250000, cancel_check: Callable[[], bool] | None = None,
               progress_callback: Callable[[dict], None] | None = None, special_fold_mode=None):
    """Build from explicit HRC-shaped settings without opening any archive/file."""
    try:
        return _Builder(settings, node_budget, cancel_check, progress_callback, special_fold_mode).build()
    except TreeBuildError:
        raise
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise TreeBuildError(f"Invalid explicit tree settings: {exc}") from exc
