"""Ticket scheduler tests against the real production Engine, with synthetic leaves."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def adaptive_probe(tmp_path_factory):
    info=json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text())
    candidates=[Path(info['compiler'])] if info.get('compiler') else []
    candidates.extend([Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe'),
                       Path('D:/Tools/REA-Research/zig-x86_64-windows-0.15.2/zig.exe')])
    compiler=next((p for p in candidates if p.is_file()),None)
    if compiler is None:pytest.skip('Existing Zig compiler was not found')
    out=tmp_path_factory.mktemp('adaptive-parallel')/'probe.exe'
    subprocess.run([str(compiler),'c++','-O2','-std=c++17','-ffp-contract=off',
        str(ROOT/'scripts/native/adaptive_parallel_probe.cpp'),'-o',str(out)],check=True,capture_output=True,text=True)
    return out


def invoke(executable,mode,threads,tmp_path):
    result=subprocess.run([str(executable),mode,str(threads),str(tmp_path)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('threads',[2,3,8])
def test_tickets_exact_counts_and_legacy_switch(adaptive_probe,tmp_path,threads):
    row=invoke(adaptive_probe,'budgets',threads,tmp_path)
    assert row['samples']==12909
    assert row['rounds']==8
    assert row['claimed_blocks']>row['rounds']


@pytest.mark.parametrize('threads',[2,8])
@pytest.mark.parametrize('mode',['counter_lookup','counter_settle'])
def test_terminal_counters_aggregate_once_and_table_is_shared_after_worker_construction(adaptive_probe,tmp_path,threads,mode):
    row=invoke(adaptive_probe,mode,threads,tmp_path)
    assert row['samples']==4009
    assert row['terminal_table_lookups']==(8018 if mode=='counter_lookup' else 0)
    assert row['terminal_settlements']==(8018 if mode=='counter_settle' else 0)


@pytest.mark.parametrize('mode',['deadline','pause'])
@pytest.mark.parametrize('threads',[2,8])
def test_control_pause_quiesces_and_allows_next_slice(adaptive_probe,tmp_path,mode,threads):
    row=invoke(adaptive_probe,mode,threads,tmp_path)
    assert row['paused'] and 1003<row['samples']<1_000_000_000
    assert row['rounds']==2


@pytest.mark.parametrize('threads',[2,8])
def test_saved_worker_rng_and_raw_survive_no_work_resume(adaptive_probe,tmp_path,threads):
    row=invoke(adaptive_probe,'resume',threads,tmp_path)
    assert row['samples']==6010
    assert (tmp_path/'source/checkpoint.bin').read_bytes()==(tmp_path/'unchanged/checkpoint.bin').read_bytes()
    before=json.loads((tmp_path/'source/index.json').read_text())
    after=json.loads((tmp_path/'continued/index.json').read_text())
    assert before['samples']==5003 and after['samples']==6010


@pytest.mark.parametrize('threads',[2,8])
@pytest.mark.parametrize('mode',['exception','exception_legacy'])
def test_worker_failure_is_joined_before_propagation_and_trainer_cannot_reuse(adaptive_probe,tmp_path,threads,mode):
    row=invoke(adaptive_probe,mode,threads,tmp_path)
    assert row['failed_quiescent'] and row['rounds']==1
    assert not (tmp_path/'checkpoint.bin').exists()
