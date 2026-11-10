"""Thread controls pass through the app, archives and immutable-source resume."""
import pytest

from test_server import app, await_job
from preflop_lab import server
from preflop_lab.hrc_archive import export_archive
from preflop_lab.hrc_benchmarks import config_for
from preflop_lab.hrc_hrcz import export_hrcz


def test_real_parallel_job_archive_and_thread_override_on_resume(app):
    cfg=config_for('hu10bb',iterations=1000);cfg['threads']=4
    code,created=app('/api/jobs',{'config':cfg})
    assert code==202
    done=await_job(app,created['id'])
    assert done['status']=='completed',done
    assert done['summary']['training_threads']==4
    original=server.JOBS.get(created['id']);data=(original.solver.output/'checkpoint.bin').read_bytes()
    code,loaded=app('/api/import',raw=export_archive(original).read_bytes(),headers={'Content-Type':'application/octet-stream'})
    assert code==201,loaded
    restored=server.JOBS.get(loaded['id'])
    assert (restored.solver.output/'checkpoint.bin').read_bytes()==data
    code,hrcz=app('/api/import',raw=export_hrcz(original).read_bytes(),headers={'Content-Type':'application/zip'})
    assert code==201,hrcz
    assert (server.JOBS.get(hrcz['id']).solver.output/'checkpoint.bin').read_bytes()==data
    code,resumed=app(f"/api/jobs/{loaded['id']}/resume",{'iterations':2000,'threads':2})
    assert code==202,resumed
    result=await_job(app,resumed['id'])
    assert result['status']=='completed',result
    assert result['summary']['training_threads']==2
    assert result['summary']['iterations_completed']==2000
    assert (original.solver.output/'checkpoint.bin').read_bytes()==data
    changed=cfg.copy();changed['policies']={'version':1,'nodes':[{'node_id':0,'locks':[[.6]*169,None]}]}
    code,migrated=app(f"/api/jobs/{created['id']}/resume",{'config':changed,'iterations':1500,'threads':2,'checkpoint_migration':'preserve'})
    assert code==202,migrated
    result=await_job(app,migrated['id']);assert result['status']=='completed',result
    assert result['summary']['training_threads']==2
    root=app(f"/api/jobs/{migrated['id']}/node")[1]
    assert root['strategy']['hands']['AA']['frequencies']==pytest.approx([.6,.4])


@pytest.mark.parametrize('threads',[0,33,True,1.5,'4'])
def test_bad_parallel_controls_reject_before_launch(app,threads):
    cfg=config_for('hu10bb',iterations=1000);cfg['threads']=threads
    assert app('/api/jobs',{'config':cfg})[0]==400
    assert app('/api/jobs')[1]['jobs']==[]
