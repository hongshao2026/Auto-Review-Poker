"""Seat/config identity boundaries for fixed local research presets."""
from copy import deepcopy
import hashlib

import pytest

from preflop_lab import hrc_benchmarks as benchmarks


@pytest.fixture
def eight_pinned(tmp_path, monkeypatch):
    # This fixture tests archive identity gating only; it is not an HRC solve.
    payload = b"identity fixture for the eight-seat benchmark registry"
    case = {**benchmarks.EIGHT15BB_TEMPLATE, 'sha256': hashlib.sha256(payload).hexdigest()}
    path = tmp_path / case['archive']
    path.write_bytes(payload)
    monkeypatch.setattr(benchmarks, 'ARCHIVES', tmp_path)
    monkeypatch.setitem(benchmarks.BENCHMARKS, 'eight15bb', case)
    return path


def test_eight_seat_btn_is_after_five_earlier_seats(eight_pinned):
    cfg = benchmarks.config_for('eight15bb', iterations=60_000_000, seed=43)
    assert [p['name'] for p in cfg['players']] == ['UTG', 'EP', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']
    assert cfg['players'][5]['name'] == 'BTN'
    assert len(cfg['players']) == len(cfg['payouts']) == 8
    assert {p['stack'] for p in cfg['players']} == {15}
    assert cfg['open_sizes'] == [2]
    assert cfg['max_raises'] == 1
    assert cfg['small_blind'] == .5 and cfg['big_blind'] == 1 and cfg['ante'] == 0
    assert cfg == benchmarks.validated_config(cfg)
    assert benchmarks.archive_for('eight15bb') == eight_pinned


@pytest.mark.parametrize('name,players,stack,opening,raises', [
    ('nine20bb', 9, 20, [2], 1), ('nine10bb', 9, 10, [2], 1), ('hu10bb', 2, 10, [10], 0),
])
def test_existing_presets_keep_their_configuration(name, players, stack, opening, raises):
    cfg = benchmarks.config_for(name)
    assert len(cfg['players']) == players
    assert {p['stack'] for p in cfg['players']} == {stack}
    assert cfg['open_sizes'] == opening and cfg['max_raises'] == raises
    assert cfg['players'][-1]['name'] == 'BB'
    assert cfg['players'][-2]['name'] == ('SB/BTN' if players == 2 else 'SB')
    if players == 9:
        assert cfg['players'][6]['name'] == 'BTN'


@pytest.mark.parametrize('bad_hash', [None, '', 'pending', '0'*64])
def test_unsealed_or_wrong_identity_cannot_be_used(eight_pinned, monkeypatch, bad_hash):
    monkeypatch.setitem(benchmarks.BENCHMARKS['eight15bb'], 'sha256', bad_hash)
    with pytest.raises(ValueError):
        benchmarks.archive_for('eight15bb')
    meta = benchmarks.public_metadata()
    assert not next(p for p in meta['presets'] if p['id'] == 'eight15bb')['available']


def test_existing_filename_with_changed_bytes_is_not_available(eight_pinned):
    assert benchmarks.archive_for('eight15bb') == eight_pinned
    eight_pinned.write_bytes(b"different archive bytes")
    with pytest.raises(ValueError, match='身份校验失败'):
        benchmarks.archive_for('eight15bb')
    assert not next(p for p in benchmarks.public_metadata()['presets'] if p['id'] == 'eight15bb')['available']


def test_eight_preset_cannot_silently_change_stack_seat_or_raise(eight_pinned):
    cfg = benchmarks.config_for('eight15bb')
    for key, value in [('open_sizes', [3]), ('max_raises', 0), ('players', cfg['players'][:-1])]:
        changed = deepcopy(cfg)
        changed[key] = value
        with pytest.raises(ValueError, match='固定对照场景'):
            benchmarks.validated_config(changed)


def test_model_label_is_not_nine_seat_specific():
    assert '九人' not in benchmarks.MODEL['title']


def test_original_eight15bb_five_folds_reaches_btn_with_raise_and_shove():
    from preflop_lab.hrc_research import HRCResearchSolver

    cfg = benchmarks.config_for('eight15bb', iterations=60_000_000)
    solver = HRCResearchSolver(cfg)
    assert solver.tree.rules.players == 8
    assert solver.tree.rules.initial_stacks == (150000,) * 8
    root = solver.describe_node([])
    assert root['actor'] == 0 and root['actor_name'] == 'UTG'
    btn = solver.describe_node(['0'] * 5)
    assert btn['actor'] == 5 and btn['actor_name'] == 'BTN'
    assert btn['folded'] == [True] * 5 + [False] * 3
    assert btn['pot'] == 1.5
    assert btn['remaining'] == [15] * 6 + [14.5, 14]
    assert [(a['kind'], a['amount']) for a in btn['actions']] == [
        ('fold', 0), ('raise', 2), ('allin', 15),
    ]
    assert sum(btn['remaining']) + sum(btn['contributions']) == 120
    meta = benchmarks.public_metadata()
    assert next(p for p in meta['presets'] if p['id'] == 'eight15bb')['available']
