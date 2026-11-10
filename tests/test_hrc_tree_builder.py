"""Generated trees versus original complete structures and independent rules."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from preflop_lab.hrc_tree import parse_gametree, replay_tree
from preflop_lab.hrc_tree_builder import _Builder, build_tree, default_settings, TreeBuildError

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,n,stack,pushfold,pko", [
    ("hu10bb-pushfold-10m", 2, 100000, True, False),
    ("eight15bb-raise-call-postflop-60m", 8, 150000, False, False),
    ("nine10bb-raise-call-postflop-initial", 9, 100000, False, False),
    ("nine20bb-raise-call-postflop-60m", 9, 200000, False, False),
    ("eight15bb-pko-50-30-20-initial", 8, 150000, False, True),
])
def test_generate_complete_original_tree_from_explicit_parameters(name, n, stack, pushfold, pko):
    path = ROOT / "analysis/hrc-desktop" / f"{name}.hrcz"
    if not path.exists(): pytest.skip("Local original research fixture absent")
    config = default_settings(n, stack)
    if pushfold:
        config["treeconfig"]["preflop"]["settings"]["PREFLOP_SIZES"][0] = "all-in"
        config["treeconfig"]["preflop"]["settings"]["ALLOWED_FLATS_PER_RAISE"][1] = 0
    if pko:
        config["eqmodel"] = {"id": "icm", "structure": {"bountyType": "PKO"}}
    generated = build_tree(config)  # Before any archive is opened, including settings.
    with ZipFile(path) as archive: nodes, root = parse_gametree(archive.read("gametree.dat"))
    assert generated.nodes == nodes
    assert generated.root == root
    states, _ = replay_tree(nodes, root, generated.rules)
    for actual, reference in zip(generated.states, states):
        for field in ("remaining", "contributions", "folded", "street", "current_bet", "next_actor"):
            assert getattr(actual, field) == getattr(reference, field)
    assert generated.provenance["saved_tree_read"] is False
    assert generated.compact_export()["nodes"][0]["actor"] == 0


def test_generated_btn_preview_and_no_input_mutation(monkeypatch):
    config = default_settings(8, 150000)
    before = copy.deepcopy(config)
    monkeypatch.setattr(ZipFile, "__init__", lambda *a, **k: pytest.fail("Builder must not read any archive"))
    tree = build_tree(config)
    assert config == before
    view = tree.describe_node(["0"]*5)
    assert view["actor"] == 5
    assert [a["kind"] for a in view["actions"]] == ["fold", "raise", "raise"]
    assert [a["amount"] for a in view["actions"]] == [0, 2, 15]
    assert tree.describe_node(node_id=5) == view
    assert view["topology_source"] == "independently_generated"
    assert tree.states[5].pending[5:8] == (True, True, True)


def test_rebuilding_identical_config_has_identical_checkpoint_input():
    config = default_settings(3, 1000, 100)
    first, second = build_tree(config), build_tree(config)
    assert "seconds" in first.validation
    assert "seconds" not in first.compact_export()["validation"]
    assert json.dumps(first.compact_export(), sort_keys=True) == json.dumps(second.compact_export(), sort_keys=True)


@pytest.mark.parametrize("n", range(2, 11))
@pytest.mark.parametrize("ante_type", ["REGULAR", "BB_ANTE_ANTE_FIRST", "BB_ANTE_BLIND_FIRST"])
def test_two_to_ten_seats_ante_short_stack_conservation(n, ante_type):
    config = default_settings(n, [1000 + i*100 for i in range(n)], 100)
    config["handdata"]["anteType"] = ante_type
    config["handdata"]["blinds"][2] = 40
    config["handdata"]["stacks"][-1] = 50
    config["engine"]["maxactive"] = 2
    pre = config["treeconfig"]["preflop"]["settings"]
    pre["PREFLOP_SIZES"] = ["all-in"]
    pre["ALLOWED_FLATS_PER_RAISE"] = [0, 0]
    tree = build_tree(config)
    for state in tree.states:
        assert min(state.remaining) >= 0
        assert sum(state.remaining) + sum(state.contributions) + state.dead_money == sum(tree.rules.initial_stacks)
    root = tree.states[0]
    if ante_type == "REGULAR": assert root.dead_money == 0
    elif ante_type == "BB_ANTE_ANTE_FIRST": assert root.dead_money == 40
    else: assert root.dead_money == 0  # BB's entire short stack posts the blind first.


@pytest.mark.parametrize("straddle,actor,posted", [("OFF", 0, [0,0,0,50,100]),
    ("SINGLE", 1, [200,0,0,50,100]), ("DOUBLE", 2, [200,400,0,50,100]), ("BUTTON", 3, [0,0,200,50,100])])
def test_straddle_actor_and_initial_posting(straddle, actor, posted):
    config = default_settings(5, 2000, 100)
    config["handdata"]["straddleType"] = straddle
    builder = _Builder(config, 10000, None, None, None)
    context = builder.initial()
    assert builder.actor(context) == actor
    assert list(context.state.street_paid) == posted
    assert sum(context.state.remaining) + sum(posted) == 10000


def test_bb_ante_allin_zero_contribution_retains_live_eligibility():
    config = default_settings(2, [1000, 50], 100)
    config["handdata"]["blinds"][2] = 100
    tree = build_tree(config)
    leaf = tree.compact_export()["terminals"][0]
    assert len(tree.nodes) == 1
    assert leaf["dead_money"] == 50
    assert leaf["remaining"] == [950, 0]
    assert leaf["contributions"] == [50, 0]
    assert leaf["live_mask"] == 3  # The BB can win the separate ante pool.


def test_original_short_raise_reopen_and_effective_allin_rules():
    config = default_settings(3, [2000, 400, 2000], 100)
    builder = _Builder(config, 10000, None, None, None)
    context = builder.initial()
    context = builder.apply(context, 3, 300)
    assert builder.limits(context, 1) == (500, 400)
    context = builder.apply(context, 3, 400)
    assert builder.limits(context, 2) == (500, 2000)  # Original HRC, not conventional 600.
    called = builder.apply(context, 2)
    assert builder.limits(called, 0)[0] == -1
    raised = builder.apply(context, 3, 500)
    assert builder.limits(raised, 0)[0] == 700
    config = default_settings(3, [2000, 400, 1000], 100)
    builder = _Builder(config, 10000, None, None, None)
    context = builder.apply(builder.initial(), 3, 1000)
    assert context.history[-1].allin
    assert context.state.remaining[0] == 1000


def test_partial_original_snapshot_regression_report_is_all_passing():
    path = ROOT / "reports/hrc-original-tree-builder-validation.json"
    if not path.exists(): pytest.skip("Original rule audit has not run")
    report = json.loads(path.read_text())
    assert report["passed"]
    assert report["case_count"] >= 900
    assert all(case["actual"] == {**case["actual"], **case["independent"]} for case in report["cases"])


def test_preflop_reraise_sizing_and_flat_completion():
    config = default_settings(3, 10000, 100)
    pre = config["treeconfig"]["preflop"]["settings"]
    pre["PREFLOP_SIZES"] = ["2bb + 1bb, 3bb, all-in", "3x,all-in"]
    pre["PREFLOP_ALLIN_THRESHOLD"] = 100
    pre["ALLOWED_FLATS_PER_RAISE"] = [2, 2, 0]
    builder = _Builder(config, 10000, None, None, None)
    context = builder.initial()
    assert builder.sizings(context, 0) == [200, 300, 10000]
    context = builder.apply(context, 2)
    assert builder.sizings(context, 1) == [300, 10000]  # Add one BB per preceding flat.
    context = builder.apply(context, 3, 300)
    assert builder.sizings(context, 2) == [900, 10000]


def test_special_check_fold_counterfactual_modes_have_distinct_subtrees():
    config = default_settings(3, 1000, 100)
    config["treeconfig"]["preflop"]["settings"]["ALLOWED_FLATS_PER_RAISE"] = [2, 1, 0]
    ordinary = build_tree(config, special_fold_mode="checkdown")
    bounty = build_tree(config, special_fold_mode="compressed")
    assert ordinary.nodes != bounty.nodes
    specials = [n for n in bounty.compact_export()["nodes"] if n["special"]]
    assert specials
    assert any(n["special"] == 2 for n in specials)
    assert all(n["actions"][:2] == [0, 1] for n in specials)


def test_node_budget_cancellation_and_progress():
    config = default_settings(8, 150000)
    with pytest.raises(TreeBuildError, match="node_budget"):
        build_tree(config, node_budget=30)
    with pytest.raises(TreeBuildError, match="cancelled"):
        build_tree(config, cancel_check=lambda: True)
    seen = []
    tree = build_tree(config, progress_callback=seen.append)
    assert seen[0]["nodes"] == 1
    assert seen[-1]["nodes"] > 3000
    assert len(tree.nodes) == 4786


@pytest.mark.parametrize("location,value", [
    (("handdata", "stacks"), [100]), (("handdata", "stacks"), [100, 0]),
    (("handdata", "blinds"), [0, 0, 0]), (("handdata", "blinds"), [100, 50, -1]),
    (("handdata", "straddleType"), "UNKNOWN"), (("handdata", "anteType"), "UNKNOWN"),
    (("handdata", "movingBu"), "true"), (("engine", "maxactive"), 1),
    (("treeconfig", "mode"), "script"),
    (("treeconfig", "preflop", "id"), "preflop.settings.general"),
    (("treeconfig", "preflop", "settings", "PREFLOP_SIZES"), ["garbage"]),
    (("treeconfig", "preflop", "settings", "ALLOWED_FLATS_PER_RAISE"), [-1]),
    (("treeconfig", "postflop", "settings", "POSTFLOP_GEO"), [[0], [66]]),
])
def test_reject_unsupported_or_invalid_config(location, value):
    config = default_settings()
    owner = config
    for key in location[:-1]: owner = owner[key]
    owner[location[-1]] = value
    with pytest.raises(TreeBuildError): build_tree(config)
