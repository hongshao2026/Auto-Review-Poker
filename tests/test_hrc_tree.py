"""Independent replay invariants; archive tests skip when local fixtures are absent."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import zipfile

import pytest

from preflop_lab.hrc_tree import (HRCAction, TreeReplayError, apply_action,
                                initial_state, load_hrc_tree, parse_gametree,
                                rules_from_settings)

ROOT = Path(__file__).resolve().parents[1]


def settings(stacks=(1000, 1000)):
    return {"handdata": {"stacks": list(stacks), "blinds": [100, 50, 0],
                         "skipSb": False, "movingBu": False, "straddleType": "OFF"},
            "eqmodel": {"id": "chipev", "raked": False},
            "engine": {"configuration": {"abstractions": [
                {"street": i, "buckets": b} for i, b in enumerate((169, 1024, 256, 256))]}}}


def word(kind, actor, amount=0, street=0, allin=False):
    return kind | actor << 8 | int(allin) << 12 | street << 13 | amount << 16


def tree_bytes(records):
    chunks = [struct.pack("<i", len(records))]
    for node_id, parent, actor, street, incoming, children in records:
        kind = 2 if actor is None else 1
        chunks.append(struct.pack("<iiBbh", node_id, parent, kind, len(incoming), len(children)))
        if actor is not None:
            chunks.append(struct.pack("<bb", street, actor))
        chunks.append(struct.pack("<" + "Q" * len(incoming), *incoming))
        chunks.append(struct.pack("<" + "i" * len(children), *children))
    return b"".join(chunks)


def hu_records():
    return [(0, -1, 0, 0, [], [1, 2]),
            (1, 0, None, None, [word(0, 0), word(1, 1)], []),
            (2, 0, 1, 0, [word(3, 0, 1000, allin=True)], [3, 4]),
            (3, 2, None, None, [word(0, 1)], []),
            (4, 2, None, None, [word(2, 1, 900, allin=True)], [])]


def archive(path, records=None, config=None, saved=b"unread strategy payload"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("settings.json", json.dumps(config or settings()))
        z.writestr("gametree.dat", tree_bytes(records or hu_records()))
        z.writestr("nodedata.dat", saved)
        z.writestr("state.json", b"deliberately not valid JSON")
        z.writestr("idx.dat", b"deliberately not a valid index")
    return path


def test_archive_reader_never_reads_saved_strategy_or_leaf_values(tmp_path, monkeypatch):
    path = archive(tmp_path / "hu.hrcz")
    opened = []
    real_read = zipfile.ZipFile.read
    def logged_read(self, name, *args, **kwargs):
        opened.append(name)
        return real_read(self, name, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "read", logged_read)
    result = load_hrc_tree(path)
    assert opened == ["settings.json", "gametree.dat"]
    assert result.provenance["saved_strategy_loaded"] is False
    assert result.provenance["saved_terminal_utilities_loaded"] is False


def test_saved_payload_changes_cannot_seed_import(tmp_path):
    first = load_hrc_tree(archive(tmp_path / "a.hrcz", saved=b"strategy A"))
    second = load_hrc_tree(archive(tmp_path / "b.hrcz", saved=b"different strategies and leaf EV"))
    assert first.nodes == second.nodes and first.states == second.states
    assert first.compact_export()["nodes"] == second.compact_export()["nodes"]
    assert first.compact_export()["terminals"] == second.compact_export()["terminals"]


def test_hu_forced_winner_check_and_uncalled_excess_remain_distinct(tmp_path):
    tree = load_hrc_tree(archive(tmp_path / "hu.hrcz"))
    walk, won_without_call, called = tree.states[1], tree.states[3], tree.states[4]
    assert walk.folded == (True, False) and walk.contributions == (50, 100)
    assert won_without_call.remaining == (0, 900)
    assert won_without_call.contributions == (1000, 100)
    assert won_without_call.folded == (False, True)
    # Native settlement must return the unmatched 900 then award the matched 200.
    assert won_without_call.remaining[0] + 900 + 200 == 1100
    assert called.remaining == (0, 0) and called.contributions == (1000, 1000)
    assert tree.validation["forced_suffix_actions"] == 1


def test_compact_export_has_native_edge_order_and_terminal_state(tmp_path):
    compact = load_hrc_tree(archive(tmp_path / "hu.hrcz")).compact_export()
    assert compact["nodes"][0]["children"] == [1, 2]
    assert compact["nodes"][0]["actions"] == [0, 3]
    assert compact["nodes"][2]["actions"] == [0, 2]
    assert compact["nodes"][0]["buckets"] == 169
    assert compact["terminals"][2]["live_mask"] == 3
    assert compact["big_blind"] == 100
    json.dumps(compact, allow_nan=False)


def test_describe_node_is_immutable_path_and_id_preview(tmp_path):
    tree = load_hrc_tree(archive(tmp_path / "hu.hrcz"))
    original_states = tree.states
    root = tree.describe_node()
    assert root["pot"] == 1.5 and root["remaining"] == [9.5, 9.0]
    assert [a["id"] for a in root["actions"]] == ["0", "1"]
    raised = tree.describe_node(["1"])
    assert raised == tree.describe_node(node_id=2)
    assert raised["actor"] == 1 and raised["actions"][1]["cost"] == 9.0
    assert tree.node_path(4) == ["1", "1"]
    assert tree.get_node(["1", "1"]).id == 4
    raised["remaining"][0] = -999
    assert tree.describe_node(["1"])["remaining"][0] == 0
    assert tree.states is original_states
    with pytest.raises(TreeReplayError): tree.describe_node(["-1"])
    with pytest.raises(TreeReplayError): tree.describe_node([1])


def test_postflop_raise_is_street_total_and_folded_dead_money_is_preserved():
    rules = rules_from_settings(settings((1000, 1000, 1000)))
    state = initial_state(rules)
    actions = [HRCAction(3, 0, 0, 200), HRCAction(0, 1, 0, 0), HRCAction(2, 2, 0, 100),
               HRCAction(1, 2, 1, 0), HRCAction(3, 0, 1, 150), HRCAction(2, 2, 1, 150),
               HRCAction(1, 2, 2, 0), HRCAction(1, 0, 2, 0),
               HRCAction(1, 2, 3, 0), HRCAction(1, 0, 3, 0)]
    for action in actions:
        state = apply_action(state, action, rules)
    assert state.contributions == (350, 50, 350)
    assert state.remaining == (650, 950, 650)
    assert state.street_contributions == (0, 0, 0)
    assert state.folded == (False, True, False)
    assert state.next_actor is None and state.street == 3


def test_headsup_postflop_big_blind_acts_first():
    rules = rules_from_settings(settings())
    state = apply_action(initial_state(rules), HRCAction(2, 0, 0, 50), rules)
    state = apply_action(state, HRCAction(1, 1, 0, 0), rules)
    with pytest.raises(TreeReplayError, match="Wrong actor"):
        apply_action(state, HRCAction(1, 0, 1, 0), rules)
    state = apply_action(state, HRCAction(1, 1, 1, 0), rules)
    assert state.next_actor == 0


def test_underraise_does_not_reopen_prior_player():
    rules = rules_from_settings(settings((1000, 350, 1000)))
    state = initial_state(rules)
    for action in [HRCAction(3, 0, 0, 300), HRCAction(3, 1, 0, 350, True), HRCAction(2, 2, 0, 250)]:
        state = apply_action(state, action, rules)
    with pytest.raises(TreeReplayError, match="not reopened"):
        apply_action(state, HRCAction(3, 0, 0, 550), rules)
    state = apply_action(state, HRCAction(2, 0, 0, 50), rules)
    assert state.contributions == (350, 350, 350)


def test_cumulative_short_allins_reopen_at_full_raise_threshold():
    rules = rules_from_settings(settings((1000, 350, 500, 1000)))
    state = initial_state(rules)
    for action in [HRCAction(3, 0, 0, 300), HRCAction(3, 1, 0, 350, True),
                   HRCAction(3, 2, 0, 500, True), HRCAction(2, 3, 0, 400)]:
        state = apply_action(state, action, rules)
    state = apply_action(state, HRCAction(3, 0, 0, 700), rules)
    assert state.current_bet == 700 and state.last_full_raise == 200
    assert state.next_actor == 3


@pytest.mark.parametrize("action,reason", [
    (HRCAction(1, 0, 0, 0), "Check faces"),
    (HRCAction(2, 0, 0, 100), "Call amount"),
    (HRCAction(3, 0, 0, 150), "below minimum"),
    (HRCAction(3, 0, 0, 1001, True), "exceeds stack"),
    (HRCAction(3, 0, 0, 1000, False), "All-in flag"),
    (HRCAction(1, 1, 0, 0), "Wrong actor"),
    (HRCAction(1, 1, 1, 0), "round closed"),
])
def test_reject_illegal_amount_turn_flags_and_round_transitions(action, reason):
    rules = rules_from_settings(settings())
    with pytest.raises(TreeReplayError, match=reason):
        apply_action(initial_state(rules), action, rules)


def test_reject_early_leaf_with_future_betting(tmp_path):
    records = [(0, -1, 0, 0, [], [1]),
               (1, 0, None, None, [word(2, 0, 50), word(1, 1)], [])]
    with pytest.raises(TreeReplayError, match="future betting streets"):
        load_hrc_tree(archive(tmp_path / "early.hrcz", records))


@pytest.mark.parametrize("mutation", ["truncated", "extra_bytes", "reused_child", "wrong_parent", "bad_action"])
def test_reject_structural_corruption(mutation):
    records = hu_records()
    if mutation == "reused_child":
        records[0] = (*records[0][:-1], [1, 1])
    elif mutation == "wrong_parent":
        records[1] = (1, 2, *records[1][2:])
    elif mutation == "bad_action":
        records[1] = (*records[1][:4], [4], [])
    data = tree_bytes(records)
    if mutation == "truncated": data = data[:-1]
    if mutation == "extra_bytes": data += b"x"
    with pytest.raises(TreeReplayError):
        parse_gametree(data)


@pytest.mark.parametrize("field,value", [("blinds", [100, 50, 10]), ("skipSb", True),
                                         ("movingBu", True), ("straddleType", "SINGLE")])
def test_fail_closed_for_unverified_rule_variants(field, value):
    config = settings()
    config["handdata"][field] = value
    with pytest.raises(TreeReplayError):
        rules_from_settings(config)


@pytest.mark.parametrize("filename,nodes,decisions,terminals,actions,forced", [
    ("hu10bb-pushfold-10m.hrcz", 5, 2, 3, 5, 1),
    ("nine10bb-raise-call-postflop-initial.hrcz", 6629, 3090, 3539, 7049, 421),
    ("nine20bb-raise-call-postflop-60m.hrcz", 12193, 5322, 6871, 12627, 435),
])
def test_real_archives_every_node_action_and_terminal_layer(filename, nodes, decisions, terminals, actions, forced):
    path = ROOT / "analysis/hrc-desktop" / filename
    if not path.exists(): pytest.skip("Local user-authorized HRC archive is absent")
    tree = load_hrc_tree(path)
    assert tree.validation["nodes"] == nodes
    assert tree.validation["decision_nodes"] == decisions
    assert tree.validation["terminal_nodes"] == terminals
    assert tree.validation["replayed_actions"] == actions
    assert tree.validation["forced_suffix_actions"] == forced
    for state in tree.states:
        assert tuple(r+c for r,c in zip(state.remaining,state.contributions)) == tree.rules.initial_stacks
        assert state.pot + sum(state.remaining) == sum(tree.rules.initial_stacks)
    assert tree.validation["all_terminal_pot_layers_have_eligible_players"]
    exported = tree.compact_export()
    assert len(exported["terminals"]) == terminals
    for node in exported["nodes"]:
        assert len(node["actions"]) == len(node["children"])
        if node["actor"] >= 0:
            assert node["buckets"] == (169,1024,256,256)[node["street"]]


@pytest.mark.parametrize("first,second", [
    ("hu10bb-pushfold-initial.hrcz", "hu10bb-pushfold-10m.hrcz"),
    ("hu10bb-pushfold-10m.hrcz", "hu10bb-pushfold-reloaded.hrcz"),
    ("nine10bb-raise-call-postflop-initial.hrcz", "nine10bb-raise-call-postflop-reloaded.hrcz"),
    ("nine20bb-raise-call-postflop-initial.hrcz", "nine20bb-raise-call-postflop-60m.hrcz"),
])
def test_training_and_reload_preserve_configuration_and_imported_topology(first, second):
    first, second = (ROOT / "analysis/hrc-desktop" / name for name in (first, second))
    if not first.exists() or not second.exists(): pytest.skip("Local authorized archives are absent")
    with zipfile.ZipFile(first) as a, zipfile.ZipFile(second) as b:
        assert a.read("settings.json") == b.read("settings.json")
        # HRC reload reorders serialized records; semantic nodes must be keyed
        # by their stored IDs, never by ZIP record position.
        assert parse_gametree(a.read("gametree.dat")) == parse_gametree(b.read("gametree.dat"))
    assert load_hrc_tree(first).states == load_hrc_tree(second).states
