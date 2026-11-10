"""Constraints and future-game utility must affect actual API training state."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from test_server import app, await_job
from preflop_lab import server
from preflop_lab.hrc_archive import export_archive
from preflop_lab.hrc_benchmarks import config_for
from preflop_lab.tournament import default_config


@pytest.mark.parametrize('policy', [
    {'node_id': 0, 'locks': [[.3] * 169, None]},
    {'node_id': 0, 'frequency': {'targets': [.4, None], 'edges': [0, .2]}},
])
def test_constraints_native_archive_and_resume(app, policy):
    cfg = config_for('hu10bb', iterations=1000)
    cfg.update(solver_mode='v3', track_ci=True, policies={'version': 1, 'nodes': [policy]})
    code, preview = app('/api/tree', {'config': cfg})
    assert code == 200 and len(preview['policy_bucket_labels']) == 169 and preview['policy'] == policy
    code, created = app('/api/jobs', {'config': cfg})
    assert code == 202
    finished = await_job(app, created['id'])
    assert finished['status'] == 'completed', finished
    assert finished['summary']['mode'] == 'v3' and finished['summary']['ci']['selected_nodes'] == 2
    job = server.JOBS.get(created['id'])
    original = (job.solver.output / 'checkpoint.bin').read_bytes()
    node = job.node([])
    if 'locks' in policy:
        assert node['strategy']['display_semantics'] == 'locked_per_bucket_average'
        for hand in node['strategy']['hands'].values():
            assert hand['frequencies'] == pytest.approx([.3, .7])
    else:
        assert node['strategy']['storage_format'] == 63
        assert node['strategy']['frequency']['targets'] == [.4, None]
        assert sum(node['strategy']['frequency']['aggregate']) == pytest.approx(1)
    code, imported = app('/api/import', raw=export_archive(job).read_bytes(), headers={'Content-Type': 'application/octet-stream'})
    assert code == 201, imported
    assert server.JOBS.get(imported['id']).node([])['strategy'] == node['strategy']
    code, resumed = app(f"/api/jobs/{imported['id']}/resume", {'iterations': 1500, 'reset_regret': True, 'reset_average': True})
    assert code == 202, resumed
    result = await_job(app, resumed['id'])
    assert result['status'] == 'completed' and result['summary']['iterations_completed'] == 1500
    assert result['summary']['reset_regret'] and result['summary']['reset_average']
    assert server.JOBS.get(resumed['id']).node([])['strategy']['visits'] == 500
    assert (job.solver.output / 'checkpoint.bin').read_bytes() == original


def test_fgs_bounty_training_and_portable_identity(app):
    cfg = default_config('hu10bb')
    cfg.update(iterations=100, fgs={'enabled': True, 'depth': 1})
    cfg['bounty'] = {'mode': 'pko', 'amounts': [10, 20], 'other_amounts': [], 'immediate_fraction': .5}
    code, created = app('/api/jobs', {'config': cfg})
    assert code == 202
    finished = await_job(app, created['id'])
    assert finished['status'] == 'completed', finished
    assert finished['summary']['fgs']['states'] > 0 and finished['summary']['fgs']['terminal_cache_hits'] > 0
    job = server.JOBS.get(created['id'])
    compact = json.loads((job.solver.output / 'tree.json').read_text())
    assert 'chance_cache' not in compact['fgs']
    assert compact['fgs']['chance_sha256']
    code, imported = app('/api/import', raw=export_archive(job).read_bytes(), headers={'Content-Type': 'application/octet-stream'})
    assert code == 201, imported
    assert server.JOBS.get(imported['id']).node([])['strategy'] == job.node([])['strategy']
    code, resumed = app(f"/api/jobs/{imported['id']}/resume", {'iterations': 200})
    assert code == 202 and await_job(app, resumed['id'])['status'] == 'completed'


@pytest.mark.parametrize('changes', [
    {'solver_mode': 'v5'}, {'track_ci': 1}, {'target_ci': 1},
    {'fgs': {'enabled': True}},
    {'policies': {'version': 1, 'nodes': [{'node_id': 100000, 'locks': [[.5] * 169, None]}]}},
    {'policies': {'version': 1, 'nodes': [{'node_id': 0, 'locks': [[.5] * 169, [.6] * 169]}]}},
    {'policies': {'version': 1, 'nodes': [{'node_id': 0, 'locks': [[.3] * 169, [.3] * 169]}]}},
])
def test_invalid_training_models_rejected_before_start(app, changes):
    cfg = config_for('hu10bb')
    cfg.update(deepcopy(changes))
    assert app('/api/jobs', {'config': cfg})[0] == 400
    assert app('/api/jobs')[1]['jobs'] == []


def test_policy_migration_creates_new_checkpoint_and_keeps_source(app):
    cfg = config_for('hu10bb', iterations=1000)
    _, source = app('/api/jobs', {'config': cfg})
    assert await_job(app, source['id'])['status'] == 'completed'
    original = server.JOBS.get(source['id'])
    data = (original.solver.output / 'checkpoint.bin').read_bytes()
    cfg['policies'] = {'version': 1, 'nodes': [{'node_id': 0, 'locks': [[.6] * 169, None]}]}
    code, migrated = app(f"/api/jobs/{source['id']}/resume", {'config': cfg, 'iterations': 1200, 'checkpoint_migration': 'preserve'})
    assert code == 202, migrated
    final = await_job(app, migrated['id'])
    assert final['status'] == 'completed', final
    assert final['summary']['iterations_completed'] == 1200
    assert server.JOBS.get(migrated['id']).node([])['strategy']['hands']['AA']['frequencies'] == pytest.approx([.6, .4])
    assert (original.solver.output / 'checkpoint.bin').read_bytes() == data


def test_extended_postflop_stores_archive_round_trip(app):
    from preflop_lab.hrc_custom import default_config as custom_config
    cfg = custom_config(2)
    cfg.update(iterations=300, stores={'version': 1, 'street_formats': [23, 27, 31, 31]})
    _, created = app('/api/jobs', {'config': cfg})
    done = await_job(app, created['id'])
    assert done['status'] == 'completed', done
    job = server.JOBS.get(created['id'])
    assert {row['format'] for row in job.solver.index['nodes']} >= {0, 23, 27, 31}
    code, imported = app('/api/import', raw=export_archive(job).read_bytes(), headers={'Content-Type': 'application/octet-stream'})
    assert code == 201, imported
    target = server.JOBS.get(imported['id'])
    assert (target.solver.output / 'checkpoint.bin').read_bytes() == (job.solver.output / 'checkpoint.bin').read_bytes()
