"""Compare independent C++ operations to retained original-bytecode evidence."""
import json
from pathlib import Path
import subprocess

import pytest

from preflop_lab.hrc_native import ROOT, build, read_node, run


@pytest.fixture(scope="module")
def probes():
    output = subprocess.check_output([str(build()), "--self-test"], text=True)
    return {r["id"]: r["actual"] for r in map(json.loads, output.splitlines())}


@pytest.fixture(scope="module")
def original():
    report = json.loads((ROOT / "reports/hrc-original-strategy-validation.json").read_text(encoding="utf-8-sig"))
    return {r["id"]: r["actual"] for r in report["records"] if r["kind"] == "numeric_check"}


@pytest.mark.parametrize("case", range(8))
def test_original_regret_matching(probes, original, case):
    assert probes[f"normalization.{case}"] == pytest.approx(original[f"mv.normalization.{case}"], abs=1e-14)


@pytest.mark.parametrize("street,z", [(0, 0), (0, 1), (0, 100), (1, 0), (1, 1)])
@pytest.mark.parametrize("step,label", [(1, "first"), (2, "second")])
def test_original_store_arrays(probes, original, street, z, step, label):
    name = "mE" if street == 0 else "mA"
    assert probes[f"store.{street}.z{z}.{label}"] == pytest.approx(original[f"{name}.z{z}.0.step{step}.raw"], abs=1e-14)


def test_cached_update_clock_and_large_counter(probes):
    assert probes["cached_counter.after5"] == [3, 63, -21, 14, 3.5, 10.5]
    assert probes["cached_counter.after6refresh"] == [6, 90, -30, 20, 5, 15]
    t = 60_000_001
    assert probes["counter_60m_double"] == [t, 4.5*t, -1.5*t, t, .25*t, .75*t]


@pytest.mark.parametrize("v4", [False, True])
@pytest.mark.parametrize("gate", [0, 1])
@pytest.mark.parametrize("scalar", [False, True])
def test_original_traversal_skip_semantics(probes, v4, gate, scalar):
    stem = f"{'scalar' if scalar else 'vector'}.v{4 if v4 else 3}.gate{gate}"
    skip = scalar and v4 and gate == 0
    assert probes[stem+".return_counter_rng"] == [30, 0 if skip else 1, 1 if scalar and v4 else 0]
    assert probes[stem+".raw"] == ([0]*6 if skip else [1, -15.5, 15.5, 1, .5, .5])


def test_independent_integer_tie_settlement(probes):
    assert probes["settlement.merged_tie_tiers"] == [1, 1, 1, -1, -2]
    assert probes["settlement.odd_remainder_to_high_seat"] == [0, 0, 2, -1, -1]


def test_winner_cache_covers_all_subsets_ties_and_deal_changes(probes):
    assert probes['winner_cache.exhaustive_subsets_and_epochs'] == [0, 49_104]


def hu_tree():
    # Three legal terminal chip states; evaluator receives genuine random cards.
    return {"root": 0, "players": 2, "big_blind": 100, "initial_stacks": [1000, 1000],
            "nodes": [{"id": 0, "actor": 0, "street": 0, "buckets": 169, "children": [1, 2], "actions": [0, 3], "terminal_id": -1},
                      {"id": 1, "actor": -1, "street": 0, "buckets": 0, "children": [], "actions": [], "terminal_id": 0},
                      {"id": 2, "actor": 1, "street": 0, "buckets": 169, "children": [3, 4], "actions": [0, 2], "terminal_id": -1},
                      {"id": 3, "actor": -1, "street": 0, "buckets": 0, "children": [], "actions": [], "terminal_id": 1},
                      {"id": 4, "actor": -1, "street": 0, "buckets": 0, "children": [], "actions": [], "terminal_id": 2}],
            "terminals": [{"remaining": [950, 900], "contributions": [50, 100], "folded": [True, False]},
                          {"remaining": [0, 900], "contributions": [1000, 100], "folded": [False, True]},
                          {"remaining": [0, 0], "contributions": [1000, 1000], "folded": [False, False]}]}


def test_fresh_zero_checkpoint_resume_exact(tmp_path):
    tree = hu_tree()
    direct, partial, resumed = (tmp_path / name for name in ["direct", "partial", "resumed"])
    run(tree, tmp_path, 2000, 42, direct)
    run(tree, tmp_path, 750, 42, partial)
    result = run(tree, tmp_path, 2000, 999, resumed, resume_from=partial / "checkpoint.bin")
    assert result["summary"]["iteration"] == 2000
    assert (direct / "checkpoint.bin").read_bytes() == (resumed / "checkpoint.bin").read_bytes()
    node = read_node(direct, 0)
    assert node["updates"] == 2000
    assert sum(r["visits"] for r in node["hands"]) == 2000
    assert all(abs(sum(r["display_strategy"])-1) < 1e-12 for r in node["hands"])


def test_cancel_returns_partial_checkpoint_and_zero_is_untrained(tmp_path):
    tree = hu_tree()
    zero = tmp_path / "zero"
    run(tree, tmp_path, 0, 1, zero)
    assert not any(r["trained"] for r in read_node(zero, 0)["hands"])
    cancelled = tmp_path / "cancelled"
    result = run(tree, tmp_path, 60_000_000, 1, cancelled, cancel_check=lambda: True)
    assert result["summary"]["cancelled"]
    assert result["summary"]["iteration"] < 60_000_000
    assert (cancelled / "checkpoint.bin").exists()
