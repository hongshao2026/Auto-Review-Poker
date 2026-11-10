"""Product integration boundaries for the independently validated FGS model."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from preflop_lab.hrc_fgs_config import fgs_spec, prepare_chances, validated_fgs


def scene(bb=20000):
    return SimpleNamespace(rules=SimpleNamespace(initial_stacks=(150000, 150000, 150000),
        big_blind=bb, small_blind=bb // 2), settings={"handdata": {"blinds": [bb, bb // 2, 1000],
        "anteType": "BB_ANTE_BLINDS_FIRST", "straddleType": "SINGLE", "skipSb": True, "movingBu": False}})


def test_disabled_fgs_does_not_require_equity_or_resources():
    assert fgs_spec(None, None, scene()) is None
    assert not validated_fgs()["enabled"]


@pytest.mark.parametrize("equity", [None, {"mode": "chipev"}, {"mode": "mtt_icm"},
    {"mode": "icm", "other_stacks": [100]}])
def test_unsupported_monetary_combinations_fail(equity):
    with pytest.raises(ValueError, match="FGS 需要"):
        validated_fgs({"enabled": True}, equity, 3)


@pytest.mark.parametrize("field,value", [("enabled", 1), ("depth", True), ("depth", 11),
    ("depth3way", -1), ("max_states", 0), ("max_seconds", float("nan")),
    ("terminal_cache_capacity", -1), ("max_sweeps", 1.5), ("unrecognized", 1)])
def test_invalid_or_unknown_fields_rejected(field, value):
    with pytest.raises(ValueError):
        validated_fgs({field: value})


def test_custom_and_fixed_blind_level_units_are_explicit():
    raw = {"enabled": True, "next_level_at": 2,
        "next_level": {"big_blind": 3, "small_blind": 1.5, "ante": .3}}
    original = deepcopy(raw)
    custom = fgs_spec(raw, {"mode": "icm"}, scene(), chip_scale=10000)
    fixed = fgs_spec(raw, {"utility": "icm"}, scene())
    assert custom["next_level"] == [30000, 15000, 3000]
    assert fixed["next_level"] == [60000, 30000, 6000]
    assert raw == original
    assert custom["ante_type"] == "BBBlindFirst" and custom["straddle"] == "Single"
    assert custom["skip_sb"] is True and custom["big_blind"] == 20000


def test_noninteger_internal_future_bets_fail_instead_of_rounding():
    with pytest.raises(ValueError, match="整数筹码"):
        fgs_spec({"enabled": True, "next_level_at": 1,
            "next_level": {"big_blind": 1.00001, "small_blind": .5, "ante": 0}},
            {"mode": "icm"}, scene(), chip_scale=10000)


@pytest.mark.parametrize("raw", [{"next_level_at": 1}, {"next_level": {}},
    {"next_level_at": 0, "next_level": {"big_blind": 1, "small_blind": .5, "ante": 0}},
    {"next_level_at": 1, "next_level": {"big_blind": 1, "small_blind": 2, "ante": 0}}])
def test_incomplete_or_inconsistent_future_level_rejected(raw):
    with pytest.raises(ValueError):
        validated_fgs(raw)


def test_tree_handdata_cannot_disagree_with_actual_rules():
    tree = scene()
    tree.settings["handdata"]["blinds"][0] = 10000
    with pytest.raises(ValueError, match="不一致"):
        fgs_spec({"enabled": True}, {"mode": "icm"}, tree)


def test_corrupt_cache_rejected_and_not_overwritten(tmp_path):
    target = tmp_path / "fgs-chance-v1.bin"
    target.write_bytes(b"FGSCHN01bad data")
    with pytest.raises(ValueError, match="缓存损坏"):
        prepare_chances(tmp_path / "missing-installation", tmp_path)
    assert target.read_bytes() == b"FGSCHN01bad data"
