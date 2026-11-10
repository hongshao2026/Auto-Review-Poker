"""Durable jobs restore all native nodes and resume without replacing evidence."""
from copy import deepcopy
from pathlib import Path

from test_server import app, await_job, hu_config
from preflop_lab import server
from preflop_lab.tournament import default_config


def test_legacy_saved_result_survives_empty_manager(app):
    _, created = app('/api/jobs', {'config': hu_config(app)})
    assert await_job(app, created['id'])['status'] == 'completed'
    before = app(f"/api/jobs/{created['id']}/export")[1]
    server.JOBS = server.JobManager()
    assert app('/api/jobs')[1]['jobs'][0]['id'] == created['id']
    restored = app(f"/api/jobs/{created['id']}")[1]
    assert restored['restored'] and not restored['can_resume']
    assert app(f"/api/jobs/{created['id']}/export")[1] == before
    assert app(f"/api/jobs/{created['id']}/node")[1]['strategy']['hands']['AA']['visits'] > 0


def test_native_monetary_nodes_and_continuation_survive_restart(app):
    config = default_config('hu10bb')
    config['iterations'] = 1000
    config['bounty'] = {'mode': 'pko', 'amounts': [10, 20], 'other_amounts': [], 'immediate_fraction': .5}
    _, created = app('/api/jobs', {'config': config})
    assert await_job(app, created['id'])['status'] == 'completed'
    before = deepcopy(app(f"/api/jobs/{created['id']}/export")[1])
    checkpoint = Path(before['native_artifacts']['checkpoint_path'])
    checkpoint_bytes = checkpoint.read_bytes()
    server.JOBS = server.JobManager()
    assert app(f"/api/jobs/{created['id']}")[1]['can_resume']
    node = app(f"/api/jobs/{created['id']}/node?path=%5B%221%22%5D")[1]
    assert node['strategy']['utility_unit'] == 'currency'
    assert 'relative_ev' in node['strategy']['hands']['AA']
    assert 'reference' not in node['strategy']['hands']['AA']
    assert app(f"/api/jobs/{created['id']}/resume", {'iterations': 1000})[0] == 400
    code, resumed = app(f"/api/jobs/{created['id']}/resume", {'iterations': 1500})
    assert code == 202
    done = await_job(app, resumed['id'])
    assert done['status'] == 'completed' and done['summary']['resumed']
    assert done['summary']['iterations_completed'] == 1500
    assert done['parent_job_id'] == created['id']
    assert checkpoint.read_bytes() == checkpoint_bytes
    assert app(f"/api/jobs/{created['id']}/export")[1] == before
    assert len(app('/api/jobs')[1]['jobs']) == 2
