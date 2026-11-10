"""CI reservations precede optional terminal tables without mutating solver state."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def ci_memory_probe(tmp_path_factory):
    manifest=json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text())
    candidates=[Path(manifest['compiler'])] if manifest.get('compiler') else []
    candidates.extend([Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe'),
                       Path('D:/Tools/REA-Research/zig-x86_64-windows-0.15.2/zig.exe')])
    compiler=next((p for p in candidates if p.is_file()),None)
    if compiler is None:pytest.skip('Existing Zig compiler unavailable')
    exe=tmp_path_factory.mktemp('ci-memory-probe')/'probe.exe'
    subprocess.run([str(compiler),'c++','-O2','-std=c++17','-ffp-contract=off',
        str(ROOT/'scripts/native/ci_memory_probe.cpp'),'-o',str(exe)],check=True,capture_output=True,text=True)
    return exe


def invoke(probe,mode):
    result=subprocess.run([str(probe),mode],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    return json.loads(result.stdout)


def test_reservation_is_idempotent_and_flush_occurs_only_at_start(ci_memory_probe):
    row=invoke(ci_memory_probe,'idempotent')
    assert row['tracker'] and row['reserved']==row['required']


def test_ci_off_does_not_reserve_or_mutate_anything(ci_memory_probe):
    row=invoke(ci_memory_probe,'ci_off')
    assert row['reserved']==0 and not row['tracker']


def test_one_byte_below_required_memory_rejects_without_storage_mutation(ci_memory_probe):
    row=invoke(ci_memory_probe,'one_byte_short')
    assert row['rejected'] and row['reserved']==0


@pytest.mark.parametrize('mode',['exact','tiny_headroom','table_fits'])
def test_required_ci_preempts_optional_table_budget(ci_memory_probe,mode):
    row=invoke(ci_memory_probe,mode)
    assert row['tracker'] and row['estimated']<=row['maximum']
    assert row['table']==(mode=='table_fits')
