"""Real HRC archives, native continuation, and ZIP boundary integration."""
from io import BytesIO
import json
from pathlib import Path
import struct
import zipfile

import pytest
from test_server import app, await_job
from preflop_lab import server
from preflop_lab.hrc_benchmarks import archive_for
from preflop_lab.hrc_hrcz import SourceArchive, encode_gametree, export_hrcz


def _rewrite(path, change):
    result = BytesIO()
    with zipfile.ZipFile(path) as before, zipfile.ZipFile(result,'w') as after:
        for name in before.namelist():
            data = change(name,before.read(name))
            if data is not None:
                after.writestr(name,data)
    return result.getvalue()


def test_saved_tree_and_payload_mapping_preserve_original_order():
    for benchmark in ('hu10bb','eight15bb'):
        source = SourceArchive(archive_for(benchmark))
        assert encode_gametree(source.tree)[0] == source.members['gametree.dat']
        assert len(source.records) == len(source.tree.nodes)


def test_original_import_has_real_policy_and_separate_sample_clock(app):
    payload = archive_for('hu10bb').read_bytes()
    code, imported = app('/api/import',raw=payload,headers={'Content-Type':'application/zip'})
    assert code == 201, imported
    assert imported['config']['engine']=='hrc_imported'
    assert imported['can_resume'] and imported['can_export_hrcz']
    assert imported['summary']['iterations_completed']==0
    root = app(f"/api/jobs/{imported['id']}/node")[1]
    source = SourceArchive(archive_for('hu10bb'))
    from preflop_lab.hrc_research import decoder
    rows = decoder().decode_storage(source.decoder_records[source.tree.root],source.nodes[source.tree.root])['buckets']
    for row in rows:
        hand = root['strategy']['hands'][row['hand']]
        assert hand['frequencies']==pytest.approx(row['display_strategy'])
        assert hand['visits'] in (None,0) and hand['new_visits']==0
        assert hand['has_saved_policy']
    job = server.JOBS.get(imported['id'])
    assert export_hrcz(job).read_bytes()==payload
    branch = app('/api/strategy-table',{'job_id':imported['id']})[1]
    assert branch['rows'][0]['covered_combinations']==1326
    assert branch['rows'][0]['frequency'] is not None


def test_source_resume_and_native_extension_restore_exact_checkpoint(app):
    code, imported=app('/api/import',raw=archive_for('hu10bb').read_bytes(),headers={'Content-Type':'application/zip'})
    assert code==201,imported
    code, resumed=app(f"/api/jobs/{imported['id']}/resume",{'iterations':1000})
    assert code==202,resumed
    done=await_job(app,resumed['id'])
    assert done['status']=='completed',done
    job=server.JOBS.get(resumed['id'])
    assert job.solver.index['samples']==1000
    payload=export_hrcz(job).read_bytes()
    with zipfile.ZipFile(BytesIO(payload)) as z:
        assert 'prefloplab/checkpoint.plabz' in z.namelist()
    code, restored=app('/api/import',raw=payload,headers={'Content-Type':'application/zip'})
    assert code==201,restored
    other=server.JOBS.get(restored['id'])
    assert (other.solver.output/'checkpoint.bin').read_bytes()==(job.solver.output/'checkpoint.bin').read_bytes()
    assert restored['summary']['iterations_completed']==1000
    # Standard HRC core also imports after optional native metadata is removed.
    path=export_hrcz(job)
    core=_rewrite(path,lambda name,data:None if name.startswith('prefloplab/') else data)
    code, foreign=app('/api/import',raw=core,headers={'Content-Type':'application/zip'})
    assert code==201,foreign
    assert foreign['summary']['iterations_completed']==0
    assert foreign['can_resume']


def test_foreign_archive_integrity_and_paths_are_checked(app):
    source=archive_for('hu10bb')
    def corrupt(name,data):
        if name=='idx.dat':
            return struct.pack('<q',99999)+data[8:]
        return data
    code,error=app('/api/import',raw=_rewrite(source,corrupt),headers={'Content-Type':'application/zip'})
    assert code==400 and 'idx.dat' in error['error']
    output=BytesIO()
    with zipfile.ZipFile(source) as before,zipfile.ZipFile(output,'w') as after:
        for name in before.namelist():after.writestr(name,before.read(name))
        after.writestr('../outside.txt',b'no')
    assert app('/api/import',raw=output.getvalue(),headers={'Content-Type':'application/zip'})[0]==400


def test_unknown_profile_stays_read_only_and_original_bytes_can_be_saved(app):
    source=archive_for('eight15bb')
    def unknown(name,data):
        if name=='settings.json':
            value=json.loads(data)
            value['engine']['configuration']['abstractions'][1]['id']='unavailable-profile'
            return json.dumps(value).encode()
        return data
    payload=_rewrite(source,unknown)
    code, imported=app('/api/import',raw=payload,headers={'Content-Type':'application/zip'})
    assert code==201,imported
    assert not imported['can_resume'] and imported['can_export_hrcz']
    assert imported['summary']['hrcz_import']['training_supported'] is False
    assert app(f"/api/jobs/{imported['id']}/node")[1]['strategy']['hands']['AA']['has_saved_policy']
    assert export_hrcz(server.JOBS.get(imported['id'])).read_bytes()==payload


def test_changed_hrc_core_never_uses_stale_native_extension(app):
    from preflop_lab.hrc_benchmarks import config_for
    _,created=app('/api/jobs',{'config':config_for('hu10bb',1000)})
    assert await_job(app,created['id'])['status']=='completed'
    original=export_hrcz(server.JOBS.get(created['id']))
    def changed(name,data):
        if name=='settings.json':
            value=json.loads(data);value['interop_test']='changed by another program'
            return json.dumps(value).encode()
        return data
    code, imported=app('/api/import',raw=_rewrite(original,changed),headers={'Content-Type':'application/zip'})
    assert code==201,imported
    assert imported['config']['engine']=='hrc_imported'
    assert imported['summary']['iterations_completed']==0
    assert imported['summary']['hrcz_import']['history_unknown']
