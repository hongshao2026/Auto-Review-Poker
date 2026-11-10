"""Custom inputs reach generated native trees, including BB ante and ten seats."""
from copy import deepcopy

import pytest

from test_server import app, await_job
from preflop_lab.hrc_custom import HRCCustomSolver, default_config


def pushfold(players):
    cfg = default_config(players)
    cfg['tree_settings']['preflop']['settings']['PREFLOP_SIZES'] = ['all-in'] * 4
    cfg['tree_settings']['preflop']['settings']['ALLOWED_FLATS_PER_RAISE'] = [0] * 5
    cfg['iterations'] = 1000
    return cfg


@pytest.mark.parametrize('players', [2, 3, 6, 8, 9, 10])
def test_custom_tables_with_short_stack_and_big_blind_ante_train(players):
    cfg = pushfold(players)
    cfg['players'][0]['stack'] = .1
    cfg['ante'] = .25
    solver = HRCCustomSolver(cfg)
    root = solver.describe_node([])
    assert len(root['remaining']) == players
    assert sum(root['remaining']) + root['pot'] == pytest.approx(sum(p['stack'] for p in cfg['players']))
    result = solver.run(1000)
    assert result['summary']['iterations_completed'] == 1000
    assert result['summary']['utility'] == 'net_bb'
    assert solver.reference is None


def test_native_custom_ten_player_pko_http_roundtrip(app):
    cfg = pushfold(10)
    cfg.update(utility='icm', payouts=[50, 30, 20], ante=.1)
    cfg['bounty'] = {'mode': 'pko', 'amounts': list(range(1, 11)), 'other_amounts': [], 'immediate_fraction': .5}
    code, node = app('/api/tree', {'config': cfg})
    assert code == 200 and len(node['remaining']) == 10 and node['utility_unit'] == 'currency'
    code, job = app('/api/jobs', {'config': cfg})
    assert code == 202
    done = await_job(app, job['id'])
    assert done['status'] == 'completed', done
    result = app(f"/api/jobs/{job['id']}/export")[1]
    assert result['config']['tree_settings'] == cfg['tree_settings']
    assert 'relative_ev' in result['nodes']['root']['hands']['AA']
    assert 'comparison' not in result['nodes']['root']


@pytest.mark.parametrize('change', [
    {'moving_button': 'yes'}, {'players': []}, {'utility': 'bad'}, {'ante_type': 'bad'},
    {'small_blind': 2}, {'bounty': ['pko']}, {'max_active': 1},
    {'tree_settings': {'mode': 'script'}}, {'ante': .00001},
])
def test_invalid_custom_config_rejected_before_training(change):
    cfg = default_config()
    cfg.update(deepcopy(change))
    with pytest.raises(ValueError):
        HRCCustomSolver(cfg)


def test_moving_button_preserves_current_hand_topology_and_checkpoint():
    cfg = pushfold(3)
    ordinary = HRCCustomSolver(cfg)
    cfg['moving_button'] = True
    moving = HRCCustomSolver(cfg)
    for key in ('nodes', 'terminals', 'initial_stacks'):
        assert moving.tree.compact_export()[key] == ordinary.tree.compact_export()[key]
    assert moving.tree.settings['handdata']['movingBu'] is True
    result = moving.run(1000)
    assert result['summary']['iterations_completed'] == 1000


def test_general_policy_runs_with_custom_pko():
    from preflop_lab.hrc_tree_builder import default_settings
    cfg = default_config(2)
    cfg.update(iterations=1000, utility='icm', payouts=[70, 30], moving_button=True)
    cfg['bounty'] = {'mode': 'pko', 'amounts': [10, 20], 'other_amounts': [], 'immediate_fraction': .5}
    cfg['tree_settings'] = default_settings(2, preflop_policy='general', postflop_policy='general')['treeconfig']
    solver = HRCCustomSolver(cfg)
    result = solver.run(1000)
    assert result['summary']['iterations_completed'] == 1000
    assert result['summary']['bounty_model'] == 'pko'
