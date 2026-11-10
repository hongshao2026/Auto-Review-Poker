"""Exact isolated lock-scope sampler equivalence; no production build mutation."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'.research-cache/throughput-round2-20261108/choose-lock-candidate'

@pytest.fixture(scope='module')
def probe(tmp_path_factory):
    compiler=Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')
    if not compiler.is_file():pytest.skip('Existing Zig unavailable')
    exe=tmp_path_factory.mktemp('choose-lock-probe')/'probe.exe'
    subprocess.run([str(compiler),'c++','-O3','-std=c++17','-ffp-contract=off',str(ROOT/'scripts/native/choose_lock_probe.cpp'),'-o',str(exe)],check=True,capture_output=True,text=True)
    return exe

@pytest.mark.parametrize('mode,minimum',[('tapes',320000),('choose',72000)])
def test_actions_and_complete_rng_state_after_every_sample(probe,mode,minimum):
    result=subprocess.run([str(probe),mode],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    row=json.loads(result.stdout)
    assert row['passed'] and row['snapshots']>=minimum
    (CANDIDATE/(mode+'-validation.json')).write_text(json.dumps(row,indent=2)+'\n')

def test_serial_sampler_is_unchanged_and_parallel_sampler_has_no_node_access():
    baseline=(CANDIDATE.parent/'baseline/hrc_research_solver.cpp').read_text()
    revised=(CANDIDATE/'hrc_research_solver.cpp').read_text()
    start='    int sample(const Node& n,const double* p){'
    assert baseline.split(start)[1].split('\n    }',1)[0]==revised.split(start)[1].split('\n    }',1)[0]
    helper=revised.split('    int sample_policy(',1)[1].split('\n    }',1)[0]
    assert 'Node' not in helper and 'n.' not in helper
    assert 'n.strategy(h,p);return sample(n,p);' in revised
