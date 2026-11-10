"""Cards, suit-symmetric weighted ranges, and unbiased joint dealing.

Integer card IDs use PHEvaluator's rank*4+suit representation. A range weight
is the inclusion weight of EACH concrete combo in that class, not the total
probability of the class. Independent weighted hands are jointly conditioned
on no card collision by rejecting the ENTIRE deal; sequential renormalization
would bias earlier seats. No proprietary range/equity tables are used.
"""

from bisect import bisect_right
from dataclasses import dataclass
from itertools import combinations
import math
import random
import re

RANKS = "AKQJT98765432"
ASCENDING_RANKS = RANKS[::-1]
SUITS = "cdhs"
HAND_LABELS = [a + b if a == b else a + b + "s" if i < j else b + a + "o"
               for i, a in enumerate(RANKS) for j, b in enumerate(RANKS)]


def hand_labels():
    """169 labels, row-major 13x13: pairs diagonal, suited above diagonal."""
    return list(HAND_LABELS)


def card_id(value):
    if isinstance(value, int) and 0 <= value < 52:
        return value
    if isinstance(value, str) and len(value) == 2:
        rank, suit = value[0].upper(), value[1].lower()
        if rank in ASCENDING_RANKS and suit in SUITS:
            return ASCENDING_RANKS.index(rank) * 4 + SUITS.index(suit)
    raise ValueError(f"Invalid card: {value!r}")


def card_name(card):
    return ASCENDING_RANKS[card // 4] + SUITS[card % 4]


def hand_class(cards):
    a, b = cards
    r1, r2 = sorted((a // 4, b // 4), reverse=True)
    return (ASCENDING_RANKS[r1] + ASCENDING_RANKS[r2]
            + ("" if r1 == r2 else "s" if a % 4 == b % 4 else "o"))


CLASS_COMBOS = {label: [] for label in HAND_LABELS}
for _combo in combinations(range(52), 2):
    CLASS_COMBOS[hand_class(_combo)].append(_combo)


def _single(token):
    match = re.fullmatch(r"([AKQJT2-9])([AKQJT2-9])([so]?)", token, re.I)
    if not match:
        raise ValueError(f"Invalid hand notation: {token!r}")
    a, b, suffix = match.group(1).upper(), match.group(2).upper(), match.group(3).lower()
    if RANKS.index(a) > RANKS.index(b):
        a, b = b, a
    if a == b:
        if suffix:
            raise ValueError(f"A pair cannot have a suited/offsuit suffix: {token}")
        return [a + b]
    return [a + b + suffix] if suffix else [a + b + "s", a + b + "o"]


def _expand(token):
    if token.lower() in ("all", "random", "*", "100%"):
        return HAND_LABELS
    if token.endswith("+"):
        base = _single(token[:-1])
        out = []
        for label in base:
            a, b = label[:2]
            if a == b:
                out.extend(r + r for r in RANKS[:RANKS.index(a) + 1])
            else:
                out.extend(a + r + label[2] for r in RANKS[RANKS.index(a) + 1:RANKS.index(b) + 1])
        return out
    if "-" in token:
        pieces = token.split("-")
        if len(pieces) != 2:
            raise ValueError(f"Invalid range interval: {token}")
        left, right = _single(pieces[0]), _single(pieces[1])
        out = []
        if len(left) != len(right):
            raise ValueError(f"Interval endpoints must have matching suffixes: {token}")
        for a, b in zip(left, right):
            if len(a) == len(b) == 2:
                lo, hi = sorted((RANKS.index(a[0]), RANKS.index(b[0])))
                out.extend(r + r for r in RANKS[lo:hi + 1])
            elif len(a) == len(b) == 3 and a[0] == b[0] and a[2] == b[2]:
                lo, hi = sorted((RANKS.index(a[1]), RANKS.index(b[1])))
                out.extend(a[0] + r + a[2] for r in RANKS[lo:hi + 1])
            else:
                raise ValueError(f"Use pair intervals or fixed-high-card intervals: {token}")
        return out
    return _single(token)


def _weight(value):
    try:
        result = float(value[:-1]) / 100 if isinstance(value, str) and value.endswith("%") else float(value)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid range weight: {value!r}") from None
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("Range weights must be between 0 and 1 (or 0% and 100%).")
    return result


def parse_range(spec="all"):
    """Return 169 class weights. Later tokens override earlier overlaps.

    Examples: 'JJ+, AJs+, AQo+', 'AA:0.5,AKs:50%', {'AA':1,'AKs':0.25}.
    An unsuffixed non-pair (AK) includes both suited and offsuit combinations.
    """
    weights = dict.fromkeys(HAND_LABELS, 0.0)
    if spec is None:
        spec = "all"
    if isinstance(spec, str):
        tokens = [x for x in re.split(r"[,;\s]+", spec.strip()) if x]
        entries = []
        for token in tokens:
            if ":" in token:
                name, value = token.split(":", 1)
                entries.append((name, _weight(value)))
            else:
                entries.append((token, 1.0))
    elif isinstance(spec, dict):
        entries = [(str(k), _weight(v)) for k, v in spec.items()]
    else:
        raise ValueError("A starting range must be a notation string or a class-weight object.")
    for token, value in entries:
        for label in _expand(token):
            weights[label] = value
    if not any(weights.values()):
        raise ValueError("A starting range must contain at least one positive-weight hand.")
    return weights


@dataclass(slots=True)
class HandRange:
    weights: dict
    combos: list
    cumulative: list
    masks: list
    total: float
    uniform_all: bool

    @classmethod
    def build(cls, spec):
        weights = parse_range(spec)
        combos, cumulative, masks = [], [], []
        total = 0.0
        for label in HAND_LABELS:
            weight = weights[label]
            if weight <= 0:
                continue
            for combo in CLASS_COMBOS[label]:
                combos.append(combo)
                masks.append((1 << combo[0]) | (1 << combo[1]))
                total += weight
                cumulative.append(total)
        return cls(weights, combos, cumulative, masks, total,
                   len(combos) == 1326 and len(set(weights.values())) == 1)

    def sample(self, rng):
        return self.combos[bisect_right(self.cumulative, rng.random() * self.total)]


def validate_joint_ranges(ranges, budget=100000):
    """Catch impossible narrow ranges before training; bound broad searches."""
    ordered = sorted(ranges, key=lambda r: len(r.combos))
    visited = 0

    def search(index, used):
        nonlocal visited
        if index == len(ordered):
            return True
        for mask in ordered[index].masks:
            visited += 1
            if visited > budget:
                return None
            if not used & mask:
                found = search(index + 1, used | mask)
                if found is not False:
                    return found
        return False

    if search(0, 0) is False:
        raise ValueError("The starting ranges cannot be dealt together without duplicate cards.")


def sample_deal(ranges, rng, max_attempts=100000):
    """Deal weighted private combos and one shared five-card runout."""
    if all(r.uniform_all for r in ranges):
        cards = rng.sample(range(52), 2 * len(ranges) + 5)
        return tuple(tuple(cards[2*i:2*i+2]) for i in range(len(ranges))), tuple(cards[-5:])
    for _ in range(max_attempts):
        holes = tuple(r.sample(rng) for r in ranges)
        used = {c for pair in holes for c in pair}
        if len(used) == 2 * len(ranges):
            board = tuple(rng.sample([c for c in range(52) if c not in used], 5))
            return holes, board
    raise ValueError("Ranges have too few compatible deals for rejection sampling; broaden them. No biased fallback was used.")


def evaluate_hands(holes, board):
    try:
        from phevaluator.evaluator import evaluate_cards
    except ImportError as exc:
        raise RuntimeError("Install the declared phevaluator dependency before solving.") from exc
    return tuple(evaluate_cards(*pair, *board) for pair in holes)
