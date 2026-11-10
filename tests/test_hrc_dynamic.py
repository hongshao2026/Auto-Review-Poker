import struct

import numpy as np
import pytest

from preflop_lab.hrc_dynamic import (
    COMBOS, DynamicResourceLimit, abstraction_key, key_rows, prepare, validate_history,
)

FLOP = (1 << 0) | (1 << 16) | (1 << 33)
PREFIX = (0, FLOP)


@pytest.mark.parametrize('mode', ['strict', 'balanced', 'relaxed'])
def test_scalar_vector_keys_agree_on_complete_river(mode):
    history = (*PREFIX, FLOP | (1 << 45), FLOP | (1 << 45) | (1 << 50))
    keys = key_rows(PREFIX, history, mode)
    for combo, hole in enumerate(COMBOS):
        if not hole & history[-1]:
            assert tuple(keys[combo]) == tuple(abstraction_key(PREFIX, history, hole, mode))


def test_per_player_supports_share_maps_and_remain_separate():
    full = np.ones(1326)
    sparse = np.zeros(1326)
    sparse[[10, 50, 100, 900]] = .25
    result = prepare(PREFIX, 1, 'strict', [full, full * .3, sparse, None, np.zeros(1326)])
    assert result.maps[0] is result.maps[1]
    assert result.maps[2] is not result.maps[0]
    assert result.maps[3] is None and result.effective[3:] == [0, 0]
    assert np.all(result.maps[4] == -1)
    for combo, hole in enumerate(COMBOS):
        if hole & FLOP or sparse[combo] == 0:
            assert result.maps[2][0, combo] == -1
    reachable = np.unique(result.maps[2][result.maps[2] >= 0])
    assert np.array_equal(reachable, np.arange(result.effective[2]))


def test_perfect_equivalent_excluded_combo_is_not_a_range_filter():
    # A monotone board leaves three suits interchangeable. A zero-weight
    # physical combo may still have a reachable perfect abstraction key.
    prefix = (0, (1 << 0) | (1 << 16) | (1 << 32))
    sparse = np.zeros(1326)
    sparse[6 * 5 // 2 + 5] = 1  # cards 6 and 5
    result = prepare(prefix, 1, 'perfect', [sparse])
    assert np.count_nonzero(result.maps[0] >= 0) > 1
    assert result.effective == [1]


def test_future_board_rows_and_blockers():
    result = prepare(PREFIX, 2, 'balanced', [np.ones(1326)])
    assert result.maps[0].shape == (52, 1326)
    assert np.all(result.maps[0][0] == -1)  # card already in flop
    turn = FLOP | (1 << 45)
    combo = next(i for i, h in enumerate(COMBOS) if not h & turn)
    assert result.map((*PREFIX, turn), [combo]) == [int(result.maps[0][45, combo])]
    colliding = next(i for i, h in enumerate(COMBOS) if h & turn)
    assert result.map((*PREFIX, turn), [colliding]) == [-1]


def test_binary_metadata_and_none_mode(tmp_path):
    result = prepare(PREFIX, 1, 'none', [np.ones(1326), None])
    path = tmp_path / 'unused.hrdyn'
    result.write(path)
    payload = path.read_bytes()
    assert payload[:8] == b'HRDYN001'
    assert struct.unpack_from('<5I', payload, 8) == (1, 2, 2, 1, 0)
    assert result.effective == [0, 0]
    assert result.map(PREFIX, [10, -1]) == [-1, -1]


@pytest.mark.parametrize('history', [(0, 3), (0, FLOP, FLOP), (1, FLOP), (0, FLOP, (1 << 4) - 1)])
def test_invalid_history(history):
    with pytest.raises(ValueError):
        validate_history(history)


def test_domain_and_resource_controls():
    with pytest.raises(ValueError, match='flop-to-river'):
        prepare(PREFIX, 3, 'perfect', [np.ones(1326)])
    with pytest.raises(DynamicResourceLimit, match='memory'):
        prepare(PREFIX, 3, 'strict', [np.ones(1326)], max_map_bytes=10)
    with pytest.raises(DynamicResourceLimit, match='cancelled'):
        prepare(PREFIX, 1, 'strict', [np.ones(1326)], cancel_check=lambda: True)
    result = prepare(PREFIX, 1, 'none', [None])
    for invalid in (True, -2, 1326, 1.5):
        with pytest.raises(ValueError, match='Combo IDs'):
            result.map(PREFIX, [invalid])
