import numpy as np
import pytest

from preflop_lab.hrc_dynamic import COMBO_ARRAY, DynamicResourceLimit, _runouts
from preflop_lab.hrc_resource_dynamic import ProfileTable, prepare_resource

FLOP = (1 << 40) | (1 << 44) | (1 << 48)
PREFIX = (0, FLOP)


class SyntheticProfile:
    street = 2

    def row(self, board):
        # Independent toy base partitions; no proprietary resource required.
        values = (np.arange(1326) % 17).astype('<i4')
        values[(COMBO_ARRAY & np.uint64(board)) != 0] = -1
        return values


def test_resource_reachability_uses_entire_fixed_flop_domain():
    sparse = np.zeros(1326)
    sparse[[0, 1, 42, 100]] = 1
    table = SyntheticProfile()
    known_turn = (*PREFIX, FLOP | (1 << 50))
    result = prepare_resource(known_turn, 2, [sparse, sparse * .25, None], table)
    assert result.prefix == PREFIX
    assert result.maps[0] is result.maps[1]
    assert result.maps[2] is None
    reachable = set()
    for row, history in _runouts(PREFIX, 2):
        base = table.row(history[-1])
        reachable.update(int(v) for v in base[(sparse > 0) & (base >= 0)])
    dense = {bucket: index for index, bucket in enumerate(sorted(reachable))}
    assert result.effective == [len(dense), len(dense), 0]
    for row, history in _runouts(PREFIX, 2):
        expected = [dense.get(int(value), -1) for value in table.row(history[-1])]
        assert np.array_equal(result.maps[0][row], expected)
    # Like original oo, a zero-weight combo sharing a reachable base bucket
    # maps normally; range probability belongs to the separate chance model.
    assert np.any((result.maps[0][50] >= 0) & (sparse == 0))


def test_resource_zero_support_and_inactive_seat():
    result = prepare_resource(PREFIX, 2, [np.zeros(1326), None], SyntheticProfile())
    assert result.effective == [0, 0]
    assert np.all(result.maps[0] == -1) and result.maps[1] is None


def test_resource_budget_and_cancel():
    with pytest.raises(DynamicResourceLimit, match='memory'):
        prepare_resource(PREFIX, 2, [np.ones(1326)], SyntheticProfile(), max_map_bytes=1)
    with pytest.raises(DynamicResourceLimit, match='cancelled'):
        prepare_resource(PREFIX, 2, [np.ones(1326)], SyntheticProfile(), cancel_check=lambda: True)


def test_resource_input_domains(tmp_path):
    for street in (0, 1, 3, True):
        with pytest.raises(ValueError):
            prepare_resource(PREFIX, street, [np.ones(1326)], SyntheticProfile())
    for invalid in ([1.]*169, [float('nan')]*1326, [-1.]*1326):
        with pytest.raises(ValueError):
            prepare_resource(PREFIX, 2, [invalid], SyntheticProfile())
    (tmp_path/'street2.buckets.u16').write_bytes(b'invalid resource')
    with pytest.raises(ValueError, match='identity'):
        ProfileTable(tmp_path, 2)
