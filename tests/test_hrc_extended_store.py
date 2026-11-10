"""Independent invariants for the storage migration and stale-cache boundary."""
import struct

import pytest

from preflop_lab.hrc_extended_store import ExtendedStore


def test_bucket_average_does_not_inherit_regret_or_shared_marker_weight():
    store = ExtendedStore(31, 1, 2)
    store.update(0, 2, .5, 0, [.25, .75], [-4, 8])
    assert store.rows[0] == [-18, 6, 2, .25, .75]
    assert store.shared == [.125, .375]
    assert store.header == [1, 0, 0]


def test_cached_counter_and_average_reset_have_observable_stale_semantics():
    store = ExtendedStore(31, 1, 2)
    store.header = [100.25, 2, 3]
    store._load_adders()
    store.update(0, 1, 1, 1, [.25, .75], [-4, 8])
    store.update(0, 1, 1, 1, [.25, .75], [-4, 8])
    assert store.counter == 102 and store.header[0] == 100.25
    assert store.shared == [52.625, 154.875]
    store.reset(False, True)
    assert store.counter == 100  # Reset restores the cached count, not the true adder.
    assert store.shared == pytest.approx([2e-20, 3e-20], rel=1e-15, abs=0)
    assert store.rows[0][2] == 202.5


@pytest.mark.parametrize("format", [27, 31])
def test_nonpositive_weight_cannot_add_shared_strategy(format):
    store = ExtendedStore(format, 1, 2)
    before = store.snapshot([0])
    store.update(0, 0, 100, 0, [.2, .8], [2, 9])
    store.update(0, -1, 100, 0, [.2, .8], [2, 9])
    assert store.snapshot([0]) == before


def test_25_to_27_preserves_raw_regret_and_seeds_bucket_average_with_policy():
    store = ExtendedStore(25, 2, 3)
    store.header = [9.25, 2, 3, 4]
    store.rows = [[-2, -1, 0], [1, 3, 6]]
    converted = store.converted_to_27()
    assert converted.header == store.header
    assert converted.rows == [[-2, -1, 0, 1/3, 1/3, 1/3], [1, 3, 6, .1, .3, .6]]
    assert store.rows == [[-2, -1, 0], [1, 3, 6]]


def test_serialized_31_rows_are_contiguous_across_internal_chunk_boundary():
    store = ExtendedStore(31, 3278, 2)
    store.rows[3276] = [1, 2, 3, 4, 5]
    serialized = store.serialize()
    offset = 4 * (3 + 3276 * 5)
    assert struct.unpack_from('<5f', serialized, offset) == (1, 2, 3, 4, 5)
    assert store.snapshot([3276])['chunks'] == [3, 16380, 10]
