"""Independent, history-aware postflop abstraction for fixed-board research.

This module computes keys and player-specific dense bucket IDs from cards and
range supports. It reads no proprietary bucket resource or saved policy.
The original pure key/mapping classes are used only by validation scripts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json
import math
from pathlib import Path
import struct
import time

import numpy as np

SUIT_MASK = 0x1111111111111
DECK_MASK = (1 << 52) - 1
COMBOS = tuple((1 << high) | (1 << low) for high in range(1, 52) for low in range(high))
COMBO_ARRAY = np.asarray(COMBOS, dtype=np.uint64)
MODES = ("strict", "balanced", "relaxed", "perfect", "none")


class DynamicResourceLimit(RuntimeError):
    pass


def validate_history(history):
    history = tuple(history)
    if not 2 <= len(history) <= 4 or history[0] != 0:
        raise ValueError("Board history must be [0, flop, optional turn, optional river]")
    for i, board in enumerate(history[1:], 1):
        if type(board) is not int or board < 0 or board > DECK_MASK or board.bit_count() != i + 2 or history[i-1] & board != history[i-1]:
            raise ValueError("Invalid cumulative board masks/history")
    return history


def refine_groups(board, groups=(0, 0, 0, 0)):
    """Stable equivalence groups; previous history breaks final-board ties."""
    keys = [(((board >> suit) & SUIT_MASK) << 2) + groups[suit] for suit in range(4)]
    order = sorted(range(4), key=keys.__getitem__)
    result = [0] * 4
    group = 0
    for rank, suit in enumerate(order):
        if rank and keys[suit] != keys[order[rank-1]]:
            group = rank
        result[suit] = group
    return tuple(result)


def history_groups(history):
    groups = (0, 0, 0, 0)
    for board in history:
        groups = refine_groups(board, groups)
    return groups


def canonical_with_groups(groups, mask):
    vectors = sorted((groups[suit], (mask >> suit) & SUIT_MASK) for suit in range(4))
    return sum(vector << suit for suit, (_, vector) in enumerate(vectors))


def _canonical_many(groups, masks):
    vectors = np.asarray([((masks >> np.uint64(suit)) & np.uint64(SUIT_MASK)) + np.uint64(groups[suit] << 52)
                          for suit in range(4)])
    vectors.sort(axis=0)
    result = np.zeros(masks.shape, dtype=np.uint64)
    for suit in range(4):
        result |= (vectors[suit] & np.uint64(SUIT_MASK)) << np.uint64(suit)
    return result


def _key_context(prefix, history, relaxed_river):
    groups = history_groups(prefix)
    code, previous = 0, prefix[-1]
    stop = len(history) - int(relaxed_river)
    for board in history[len(prefix):stop]:
        card = board ^ previous
        code = code * 52 + canonical_with_groups(groups, card).bit_length() - 1
        groups = refine_groups(board, groups)
        previous = board
    if relaxed_river:
        card = history[3] ^ history[2]
        index = card.bit_length() - 1
        suit = index % 4
        realized = ((history[2] >> suit) & SUIT_MASK).bit_count() >= 2
        code = code * 52 + index - suit + ((1 << (suit + 32)) if realized else 0)
    return code, groups, tuple(canonical_with_groups(groups, b) for b in history)


def abstraction_key(prefix, history, hole, mode):
    """Scalar independent key, including original residual-hole suit tests."""
    prefix, history = validate_history(prefix), validate_history(history)
    if history[:len(prefix)] != prefix or mode not in ("strict", "balanced", "relaxed"):
        raise ValueError("Invalid abstraction prefix or key mode")
    if type(hole) is not int or hole < 0 or hole > DECK_MASK or hole.bit_count() != 2 or hole & history[-1]:
        raise ValueError("Invalid/colliding hole cards")
    street = len(history) - 1
    code, groups, board = _key_context(prefix, history, mode == "relaxed" and street == 3)
    mask = canonical_with_groups(groups, hole)
    if mode == "strict":
        return code, mask
    features = [0, 0, 0] if (mode, street) in (("relaxed", 1), ("balanced", 2)) else [0, 0]
    while mask:
        bit = mask & -mask
        index = bit.bit_length() - 1
        suit = index % 4
        count = lambda b: ((b >> suit) & SUIT_MASK).bit_count()
        remaining_suited = count(mask)
        if street == 1:
            if count(board[1]) > 1 or (mode == "balanced" and count(board[1]) == 1 and remaining_suited == 2):
                features[0] |= bit
            else:
                slot = 1 if len(features) == 2 or (count(board[1]) == 1 and remaining_suited == 2) else 2
                features[slot] += 1 << (index - suit)
        elif street == 2:
            if count(board[2]) > 1:
                features[0] |= bit
            else:
                slot = 1 if len(features) == 2 or count(board[1]) == 1 else 2
                features[slot] += 1 << (index - suit)
        else:
            keep = count(board[2]) > 1 if mode == "balanced" else count(board[3]) > 2 or (count(board[2]) == 2 and remaining_suited == 2)
            if keep:
                features[0] |= bit
            else:
                features[1] += 1 << (index - suit)
        mask ^= bit
    return (code, *features)


def key_rows(prefix, history, mode):
    """Compute all 1326 scalar-equivalent keys as little-endian signed int64."""
    street = len(history) - 1
    code, groups, board = _key_context(prefix, history, mode == "relaxed" and street == 3)
    masks = _canonical_many(groups, COMBO_ARRAY)
    if mode == "strict":
        return np.column_stack((np.full(1326, code, dtype=np.uint64), masks)).astype('<i8')
    low = masks & (~masks + np.uint64(1))
    high = masks ^ low
    indices = [np.frexp(bits.astype(np.float64))[1] - 1 for bits in (low, high)]
    columns = 3 if (mode, street) in (("relaxed", 1), ("balanced", 2)) else 2
    features = np.zeros((1326, columns), dtype=np.uint64)
    for position, (bits, index) in enumerate(zip((low, high), indices)):
        suits = index % 4
        counts = lambda b: np.array([((b >> s) & SUIT_MASK).bit_count() for s in range(4)])[suits]
        both = (indices[0] % 4 == indices[1] % 4) if position == 0 else np.zeros(1326, dtype=bool)
        rank = np.left_shift(np.uint64(1), (index - suits).astype(np.uint64))
        if street == 1:
            keep = counts(board[1]) > 1
            if mode == "balanced":keep |= (counts(board[1]) == 1) & both
            secondary = (counts(board[1]) == 1) & both
        elif street == 2:
            keep = counts(board[2]) > 1
            secondary = counts(board[1]) == 1
        else:
            keep = counts(board[2]) > 1 if mode == "balanced" else (counts(board[3]) > 2) | ((counts(board[2]) == 2) & both)
            secondary = np.ones(1326, dtype=bool)
        features[keep, 0] |= bits[keep]
        if columns == 2:
            features[~keep, 1] += rank[~keep]
        else:
            features[~keep & secondary, 1] += rank[~keep & secondary]
            features[~keep & ~secondary, 2] += rank[~keep & ~secondary]
    return np.column_stack((np.full(1326, code, dtype=np.uint64), features)).astype('<i8')


def _runouts(prefix, street):
    count = street + 1 - len(prefix)
    if count == 0:
        yield 0, prefix
        return
    available = [card for card in range(52) if not prefix[-1] & (1 << card)]
    for cards in itertools.permutations(available, count):
        history, index = list(prefix), 0
        for card in cards:
            index = index * 52 + card
            history.append(history[-1] | (1 << card))
        yield index, tuple(history)


@dataclass
class DynamicAbstraction:
    prefix: tuple[int, ...]
    street: int
    mode: str
    effective: list[int]
    maps: list[np.ndarray | None]

    def map(self, history, combos):
        history = validate_history(history)
        if len(history) <= self.street or history[:len(self.prefix)] != self.prefix or len(combos) != len(self.maps):
            raise ValueError("History or player count differs from prepared abstraction")
        if any(type(combo) is not int or not -1 <= combo < 1326 for combo in combos):
            raise ValueError("Combo IDs must be integers in -1..1325")
        row = 0
        previous = self.prefix[-1]
        for board in history[len(self.prefix):self.street + 1]:
            row = row * 52 + (board ^ previous).bit_length() - 1
            previous = board
        return [-1 if mapping is None or combo < 0 else int(mapping[row, combo])
                for mapping, combo in zip(self.maps, combos)]

    def write(self, path):
        """Compact dense maps; duplicate player range-support maps share payload."""
        unique, indices = [], []
        for mapping in self.maps:
            if mapping is None:indices.append(-1);continue
            index = next((i for i, item in enumerate(unique) if item is mapping), None)
            if index is None:index=len(unique);unique.append(mapping)
            indices.append(index)
        rows = 52 ** (self.street + 1 - len(self.prefix))
        with Path(path).open('wb') as stream:
            stream.write(b'HRDYN001')
            stream.write(struct.pack('<5I', self.street, len(self.prefix), len(self.maps), rows, len(unique)))
            stream.write(struct.pack(f'<{len(self.prefix)}Q', *self.prefix))
            stream.write(struct.pack(f'<{len(indices)}i', *indices))
            stream.write(struct.pack(f'<{len(self.effective)}I', *self.effective))
            for mapping in unique:stream.write(mapping.astype('<i4', copy=False).tobytes())


def prepare(prefix, street, mode, ranges, *, max_seconds=120, max_map_bytes=1 << 30, cancel_check=None):
    """Build player-specific maps. None ranges mark inactive seats only.

    Positive range weights determine reachability; probabilities are dealt by
    the separate weighted chance sampler, never inferred from these IDs.
    """
    prefix = validate_history(prefix)
    if type(street) is not int or not len(prefix)-1 <= street <= 3 or mode not in MODES:
        raise ValueError("Invalid target street or abstraction mode")
    if mode == 'perfect' and street > len(prefix):
        raise ValueError("Original perfect abstraction does not support flop-to-river")
    if not isinstance(ranges, (tuple, list)) or not 1 <= len(ranges) <= 10:
        raise ValueError("Expected 1..10 player range arrays")
    if not math.isfinite(max_seconds) or max_seconds <= 0 or type(max_map_bytes) is not int or max_map_bytes <= 0:
        raise ValueError("Invalid dynamic abstraction resource budget")
    supports=[]
    for values in ranges:
        if values is None:supports.append(None);continue
        values=np.asarray(values,dtype=float)
        if values.shape!=(1326,) or not np.isfinite(values).all() or np.any(values<0):raise ValueError("Ranges require1326 finite nonnegative weights")
        supports.append(values>0)
    if mode == 'none':
        return DynamicAbstraction(prefix, street, mode, [0]*len(ranges), [None]*len(ranges))
    rows=52**(street+1-len(prefix));unique_supports={s.tobytes():s for s in supports if s is not None}
    if rows*1326*4*len(unique_supports)>max_map_bytes:raise DynamicResourceLimit("Dynamic map memory budget exceeded before construction")
    started=time.monotonic()
    def check():
        if cancel_check and cancel_check():raise DynamicResourceLimit("Dynamic abstraction cancelled")
        if time.monotonic()-started>max_seconds:raise DynamicResourceLimit("Dynamic abstraction time budget exhausted")
    all_runouts=list(_runouts(prefix,street));keys=[];valid=[]
    groups=history_groups(prefix)
    for _,history in all_runouts:
        check();legal=(COMBO_ARRAY & np.uint64(history[-1]))==0;valid.append(legal)
        if mode=='none':key=np.zeros((1326,1),dtype='<i8')
        elif mode=='perfect':
            if street==len(prefix)-1:
                key=_canonical_many(refine_groups(prefix[-1]),COMBO_ARRAY).astype('<i8')[:,None]
            else:
                card=history[-1]^prefix[-1]
                label=canonical_with_groups(groups,card).bit_length()-1
                key=(_canonical_many(groups,COMBO_ARRAY|np.uint64(card)) | np.uint64(label<<52)).astype('<i8')[:,None]
        else:key=key_rows(prefix,history,mode)
        keys.append(key)
    keys=np.stack(keys);valid=np.stack(valid)
    built={}
    for identity,support in unique_supports.items():
        check();selected=valid & support[None,:]
        selected_keys=keys[selected]
        unique=np.unique(selected_keys,axis=0)
        if len(unique)>2**31-1:raise DynamicResourceLimit("Too many dynamic buckets")
        # Structured numeric columns preserve lexicographic signed-long order.
        dtype=np.dtype([(str(i),'<i8') for i in range(keys.shape[2])])
        sorted_keys=np.ascontiguousarray(unique).view(dtype).reshape(-1)
        mapping=np.full((rows,1326),-1,dtype='<i4')
        for i,(row,_) in enumerate(all_runouts):
            check();eligible=valid[i] if mode=='perfect' else selected[i]
            if not len(unique):continue
            candidates=np.ascontiguousarray(keys[i,eligible]).view(dtype).reshape(-1)
            matches=np.searchsorted(sorted_keys,candidates)
            inside=matches<len(unique)
            inside[inside]&=sorted_keys[matches[inside]]==candidates[inside]
            columns=np.flatnonzero(eligible)
            mapping[row,columns[inside]]=matches[inside]
        built[identity]=(len(unique),mapping)
    effective=[0 if s is None else built[s.tobytes()][0] for s in supports]
    maps=[None if s is None else built[s.tobytes()][1] for s in supports]
    return DynamicAbstraction(prefix,street,mode,effective,maps)
