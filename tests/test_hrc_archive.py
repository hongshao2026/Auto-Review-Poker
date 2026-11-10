"""Whole calculation saves retain native state and reject corrupt archive data."""
from io import BytesIO
import json
from pathlib import Path
import zipfile

from test_server import app, await_job
from preflop_lab import server
from preflop_lab.hrc_archive import export_archive
from preflop_lab.hrc_custom import default_config


def test_fixed_archive_import_and_resume_without_original_fixture(app, monkeypatch):
    from preflop_lab import hrc_benchmarks, hrc_research
    from preflop_lab.tournament import default_config as tournament_config
    cfg = tournament_config('hu10bb')
    cfg['iterations'] = 1000
    _, created = app('/api/jobs', {'config': cfg})
    assert await_job(app, created['id'])['status'] == 'completed'
    source = server.JOBS.get(created['id'])
    payload = export_archive(source).read_bytes()
    def unavailable(*args):
        raise AssertionError('Portable restore must not read the original HRC fixture')
    monkeypatch.setattr(hrc_benchmarks, 'archive_for', unavailable)
    monkeypatch.setattr(hrc_research, 'archive_for', unavailable)
    monkeypatch.setattr(hrc_research, 'imported_tree', unavailable)
    server.JOBS = server.JobManager()
    code, imported = app('/api/import', raw=payload, headers={'Content-Type': 'application/octet-stream'})
    assert code == 201, imported
    assert server.JOBS.get(imported['id']).solver.archive is None
    code, continued = app(f"/api/jobs/{imported['id']}/resume", {'iterations': 1500})
    assert code == 202, continued
    assert await_job(app, continued['id'])['status'] == 'completed'


def create_saved_job(app):
    cfg = default_config(3)
    cfg.update(iterations=1000, ante=.25, utility='icm', payouts=[50, 30, 20])
    cfg['tree_settings']['preflop']['settings']['PREFLOP_SIZES'] = ['all-in'] * 4
    cfg['tree_settings']['preflop']['settings']['ALLOWED_FLATS_PER_RAISE'] = [0] * 5
    cfg['bounty'] = {'mode': 'pko', 'amounts': [5, 10, 20], 'other_amounts': [], 'immediate_fraction': .5}
    _, created = app('/api/jobs', {'config': cfg})
    assert await_job(app, created['id'])['status'] == 'completed'
    return server.JOBS.get(created['id'])


def test_full_tree_checkpoint_import_and_resume(app):
    source = create_saved_job(app)
    original = (source.solver.output / 'checkpoint.bin').read_bytes()
    payload = export_archive(source).read_bytes()
    code, imported = app('/api/import', raw=payload, headers={'Content-Type': 'application/octet-stream'})
    assert code == 201, imported
    assert imported['id'] != source.id and imported['can_resume'] and imported['can_export_archive']
    restored = server.JOBS.get(imported['id'])
    assert (restored.solver.output / 'checkpoint.bin').read_bytes() == original
    assert restored.solver.tree.compact_export() == source.solver.tree.compact_export()
    assert restored.node(['1'])['strategy'] == source.node(['1'])['strategy']
    code, continuation = app(f"/api/jobs/{imported['id']}/resume", {'iterations': 1500})
    assert code == 202
    assert await_job(app, continuation['id'])['status'] == 'completed'
    assert (source.solver.output / 'checkpoint.bin').read_bytes() == original


def test_corrupt_and_escaping_archives_are_rejected(app):
    source = create_saved_job(app)
    original = export_archive(source)
    for kind in ('hash', 'path', 'index'):
        output = BytesIO()
        with zipfile.ZipFile(original) as before, zipfile.ZipFile(output, 'w') as after:
            for name in before.namelist():
                data = before.read(name)
                if kind == 'hash' and name == 'native/checkpoint.bin':
                    data = data[:-1] + bytes([data[-1] ^ 1])
                if kind == 'index' and name == 'native/index.json':
                    value = json.loads(data)
                    value['nodes'][0]['raw_offset'] += 8
                    data = json.dumps(value).encode()
                after.writestr(name, data)
            if kind == 'path':
                after.writestr('../escaped.txt', 'not allowed')
        code, result = app('/api/import', raw=output.getvalue(), headers={'Content-Type': 'application/octet-stream'})
        assert code == 400 and result['error']
