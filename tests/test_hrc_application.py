"""Fixed benchmark boundaries and the real HTTP tree route."""
import pytest

from test_server import app
from preflop_lab.hrc_benchmarks import config_for, validated_config
from preflop_lab.hrc_research import HRCResearchSolver, compare_hands


def test_fixed_benchmark_budget_and_parameters(app):
    cfg = config_for(iterations=60_000_000)
    assert validated_config(cfg)['iterations'] == 60_000_000
    assert app('/api/tree', {'config': cfg})[0] == 200
    cfg['iterations'] = 1_000_000_000_001
    assert app('/api/tree', {'config': cfg})[0] == 400
    cfg = config_for()
    cfg['players'][0]['stack'] = 19
    assert app('/api/tree', {'config': cfg})[0] == 400
    assert app('/api/tree', {'config': {'engine': 'unknown'}})[0] == 400


def test_nine_player_preview_has_all_streets_without_training(app):
    cfg = config_for()
    status, root = app('/api/tree', {'config': cfg})
    assert status == 200 and root['actor_name'] == 'UTG'
    assert len(root['remaining']) == 9 and root['pot'] == 1.5
    assert [a['kind'] for a in root['actions']] == ['fold', 'raise', 'allin']
    solver = HRCResearchSolver(cfg)
    post = next(n for n in solver.tree.nodes if n.street == 1)
    path = solver.tree.node_path(post.id)
    status, node = app('/api/tree', {'config': cfg, 'path': path})
    assert status == 200 and node['street'] == 1 and node['buckets'] == 1024
    assert node['strategy'] is None
    assert sum(node['remaining']) + sum(node['contributions']) == pytest.approx(180)
    assert app('/api/tree', {'config': cfg, 'path': ['-1']})[0] == 400
    assert app('/api/tree', {'config': cfg, 'path': ['00']})[0] == 400


def test_comparison_excludes_untrained_rows_and_zero_ev_baseline():
    actual = {'AA': {'visits': 4, 'frequencies': [.25, .75], 'relative_ev_bb': [0, 2]},
              'KK': {'visits': 0, 'frequencies': [1, 0], 'relative_ev_bb': None}}
    reference = {'AA': {'frequencies': [.5, .5], 'relative_ev_bb': [0, 1]},
                 'KK': {'frequencies': [.5, .5], 'relative_ev_bb': [0, 10]}}
    error = compare_hands(actual, reference)
    assert error['covered_combos'] == 6
    assert error['frequency_mae_pp'] == 25
    assert error['relative_ev_mae_bb'] == 1


def test_meta_exposes_available_research_presets(app):
    meta = app('/api/meta')[1]
    assert meta['research']['max_samples'] == 1_000_000_000_000
    assert all(p['available'] for p in meta['research']['presets'])
