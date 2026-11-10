"""Independent reach-range extraction from an explicitly supplied parent policy.

No archive/checkpoint is opened implicitly. The caller chooses a policy source,
and supplies display/average action probabilities and postflop bucket mappings.
Ranges are individual reach factors, not card-removal-adjusted marginals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import math
import struct

from .hrc_dynamic import COMBOS, DECK_MASK, validate_history
from .hrc_abstraction import preflop_class

CARD_NAMES = tuple(rank+suit for rank in '23456789TJQKA' for suit in 'cdhs')
PREFLOP_CLASSES = tuple(preflop_class((m & -m).bit_length()-1, m.bit_length()-1) for m in COMBOS)


def _weights(values, lengths, name):
    if not isinstance(values, (tuple, list)) and not hasattr(values, 'shape'):
        raise ValueError(f'{name} must be a numeric vector')
    if len(values) not in lengths:
        raise ValueError(f'{name} has an unsupported length')
    out = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError(f'{name} requires finite nonnegative values')
        try:
            value = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f'{name} requires finite nonnegative values') from error
        if not math.isfinite(value) or value < 0:
            raise ValueError(f'{name} requires finite nonnegative values')
        out.append(value)
    return out


def expand_preflop(weights, board_mask=0):
    values = _weights(weights, (169,), 'Preflop range')
    if type(board_mask) is not int or not 0 <= board_mask <= DECK_MASK:
        raise ValueError('Invalid board mask')
    return [0. if hole & board_mask else values[cls] for hole, cls in zip(COMBOS, PREFLOP_CLASSES)]


def apply_blockers(weights, board_mask):
    values = _weights(weights, (1326,), 'Combo range')
    if type(board_mask) is not int or not 0 <= board_mask <= DECK_MASK:
        raise ValueError('Invalid board mask')
    return [0. if hole & board_mask else value for hole, value in zip(COMBOS, values)]


def multiply_action(weights, probabilities, buckets, board_mask=0):
    """lq's pure multiplication semantics; no per-seat renormalization."""
    values = _weights(weights, (1326,), 'Combo range')
    action = _weights(probabilities, (len(probabilities),), 'Action probabilities')
    if not action or any(p > 1 for p in action):
        raise ValueError('Action probabilities must be in [0,1]')
    if len(buckets) != 1326:
        raise ValueError('Expected1326 bucket IDs')
    if type(board_mask) is not int or not 0 <= board_mask <= DECK_MASK:
        raise ValueError('Invalid board mask')
    output = []
    for weight, bucket, hole in zip(values, buckets, COMBOS):
        if isinstance(bucket, bool) or int(bucket) != bucket or not -1 <= bucket < len(action):
            raise ValueError('Invalid parent bucket ID')
        value = 0. if hole & board_mask or bucket < 0 else weight * action[int(bucket)]
        if not math.isfinite(value):
            raise ValueError('Reach product overflowed')
        output.append(value)
    return output


def board_text(history):
    history = validate_history(history)
    return ''.join(CARD_NAMES[c] for old, new in zip(history, history[1:])
                   for c in range(51, -1, -1) if (new & ~old) & (1 << c))


def range_text(weights, precision=None):
    """Original lO-style decimal export when precision given; otherwise lossless.

    Returning both text and parsed weights makes display quantization explicit.
    Lossless output uses fixed decimal notation because original lQ excludes e.
    """
    values = _weights(weights, (1326,), 'Combo range')
    if precision is not None and (type(precision) is not int or not 0 <= precision <= 15):
        raise ValueError('Range precision must be0..15 orNone')
    threshold = 0. if precision is None else .5 * 10.**(-precision)
    tokens, parsed = [], [0.] * 1326
    for combo, value in enumerate(values):
        if value <= 0 or value < threshold:
            continue
        label = ''.join(CARD_NAMES[c] for c in range(51,-1,-1) if COMBOS[combo] & (1 << c))
        if value == 1 or (precision is not None and value >= 1-threshold):
            tokens.append(label)
            parsed[combo] = 1.
        else:
            decimal = Decimal(str(value))
            text = format(decimal, 'f') if precision is None else format(decimal.quantize(Decimal(1).scaleb(-precision),rounding=ROUND_HALF_UP),f'.{precision}f')
            tokens.append(label+':'+text)
            parsed[combo] = float(text)
    return ', '.join(tokens), parsed


@dataclass(frozen=True)
class ReachExtraction:
    node_id: int
    path: tuple[str, ...]
    board_history: tuple[int, ...]
    ranges: tuple[tuple[float, ...], ...]
    active: tuple[bool, ...]
    initial_state: dict
    sequence: tuple[dict, ...]
    subtree_config: dict
    serialized_ranges: tuple[tuple[float, ...], ...]
    zero_mass_seats: tuple[int, ...]
    serialized_zero_mass_seats: tuple[int, ...]
    trace: tuple[dict, ...]
    provenance: dict


def extract_reach(tree, path, board_history, action_probabilities, bucket_map,
                  *, initial_ranges=None, range_precision=None, policy_source='explicit_callback'):
    """Extract any nonterminal postflop node from ImportedTree/GeneratedTree.

    action_probabilities(node_id,edge) -> one probability per parent bucket.
    bucket_map(street,history,actor) ->1326 IDs; preflop never calls it.
    The caller owns policy choice and tree cropping; this function is immutable.
    """
    history = validate_history(board_history)
    node = tree.get_node(path)
    if node.terminal or node.street not in (1,2,3):
        raise ValueError('Subtree selection must be a nonterminal postflop node')
    if len(history) <= node.street:
        raise ValueError('Board history does not reach the selected street')
    players = tree.rules.players
    if initial_ranges is None:
        initial_ranges = [None]*players
    if not isinstance(initial_ranges,(list,tuple)) or len(initial_ranges)!=players:
        raise ValueError('Initial ranges must cover every actual seat')
    ranges = []
    for row in initial_ranges:
        if row is None:
            ranges.append([1.]*1326)
        else:
            values = _weights(row,(169,1326),'Initial range')
            ranges.append(expand_preflop(values) if len(values)==169 else values)
    path = tuple(tree.node_path(node.id))
    cursor = tree.nodes[tree.root]
    actions = list(cursor.incoming_actions)
    trace = []
    for token in path:
        edge = int(token)
        if cursor.terminal or cursor.actor is None or cursor.street is None:
            raise ValueError('Path traverses a terminal node')
        actor, street = cursor.actor, cursor.street
        probabilities = list(action_probabilities(cursor.id,edge))
        if street == 0:
            if len(probabilities)!=169:
                raise ValueError('Preflop policy requires169 bucket probabilities')
            buckets = PREFLOP_CLASSES
            mask = 0
        else:
            if len(history)<=street:
                raise ValueError('Parent strategy requires unavailable public cards')
            buckets = tuple(bucket_map(street,history,actor))
            mask = history[street]
        before = sum(ranges[actor])
        ranges[actor] = multiply_action(ranges[actor],probabilities,buckets,mask)
        trace.append(dict(node_id=cursor.id,edge=edge,actor=actor,street=street,
                          before_weight_sum=before,after_weight_sum=sum(ranges[actor]),
                          action_sha256=hashlib.sha256(struct.pack(f'<{len(probabilities)}d',*probabilities)).hexdigest(),
                          bucket_sha256=hashlib.sha256(struct.pack('<1326i',*map(int,buckets))).hexdigest()))
        child = tree.nodes[cursor.children[edge]]
        actions.extend(child.incoming_actions)
        cursor = child
    # Original lq's branch-local blockers can omit a newly dealt card for the
    # just-acting player. The actual lw factory applies the full fixed board;
    # we make that final conditioning step explicit for every actual seat.
    ranges = [apply_blockers(row,history[-1]) for row in ranges]
    state = tree.states[node.id]
    active = tuple(not state.folded[p] and state.remaining[p]>0 for p in range(players))
    sequence = tuple(dict(player=a.actor,type='FXCR'[a.kind],amount=a.amount,street=a.street) for a in actions)
    wizard_sequence = [a for a in sequence if a['street']<node.street]
    compatible = len(wizard_sequence)==len(sequence)
    serialized = [range_text(row,range_precision) for row in ranges]
    config = dict(street=node.street,board=board_text(history),sequence=list(sequence),
                  players={str(p):dict(active=active[p],range=serialized[p][0]) for p in range(players)})
    initial = asdict(state)
    initial['initial_stacks'] = list(tree.rules.initial_stacks)
    initial['big_blind'] = tree.rules.big_blind
    initial['pot'] = state.pot
    return ReachExtraction(node.id,path,history,tuple(tuple(r) for r in ranges),active,initial,sequence,config,
                           tuple(tuple(pair[1]) for pair in serialized),
                           tuple(p for p,row in enumerate(ranges) if not any(v>0 for v in row)),
                           tuple(p for p,pair in enumerate(serialized) if not any(v>0 for v in pair[1])),tuple(trace),
                           dict(policy_source=policy_source,policy_read_by_module=False,original_strategy_auto_loaded=False,
                                factor_semantics='individual path reach; no marginal card-removal normalization',
                                final_board_blockers_applied=True,range_precision=range_precision,
                                original_wizard_compatible=compatible,original_wizard_sequence=wizard_sequence,
                                selection_semantics='street_start' if compatible else 'independent_midstreet_extension'))
