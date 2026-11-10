"""Cash rake reaches production training and portable archive workflows."""
import json
import pytest
from test_server import app, await_job
from preflop_lab import server
from preflop_lab.hrc_custom import default_config
from preflop_lab.hrc_archive import export_archive


@pytest.mark.parametrize('mode', ['nfnd', 'gg', 'full'])
def test_cash_rake_native_training_archive_and_resume(app, mode):
    cfg = default_config(2)
    cfg.update(iterations=500, rake={'mode': mode, 'percentage': 5, 'cap': 1})
    _, created = app('/api/jobs', {'config': cfg})
    done = await_job(app, created['id'])
    assert done['status'] == 'completed', done
    job = server.JOBS.get(created['id'])
    compact = json.loads((job.solver.output / 'tree.json').read_text())
    assert compact['rake'] == {'mode': mode, 'fraction': .05, 'cap': 10000}
    assert all('raise_count' in t and 0 <= t['street'] <= 3 for t in compact['terminals'])
    assert sum(job.solver.index['root_mean_net_bb']) < 0
    code, imported = app('/api/import', raw=export_archive(job).read_bytes(), headers={'Content-Type': 'application/octet-stream'})
    assert code == 201, imported
    code, resumed = app(f"/api/jobs/{imported['id']}/resume", {'iterations': 700})
    assert code == 202 and await_job(app, resumed['id'])['status'] == 'completed'


def test_rake_rejects_tournament_and_invalid_amounts(app):
    cfg = default_config(2)
    for change in ({'utility': 'icm', 'rake': {'mode': 'full'}},
                   {'rake': {'mode': 'full', 'percentage': 100.1}},
                   {'rake': {'mode': 'nfnd', 'cap': .00001}}, {'rake': {'mode': 'unknown'}}):
        assert app('/api/jobs', {'config': {**cfg, **change}})[0] == 400
