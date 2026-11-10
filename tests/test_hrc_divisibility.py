"""Exact cached signed divisibility, including INT_MIN and all supported powers."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def divisibility_probe(tmp_path_factory):
    compiler=Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')
    if not compiler.is_file():pytest.skip('Existing Zig unavailable')
    exe=tmp_path_factory.mktemp('divisibility-probe')/'probe.exe'
    subprocess.run([str(compiler),'c++','-O3','-std=c++17','-ffp-contract=off',str(ROOT/'scripts/native/divisibility_probe.cpp'),'-o',str(exe)],check=True,capture_output=True,text=True)
    return exe

@pytest.mark.parametrize('mode,minimum',[('boundaries',250000),('random',2000000),('cache',86)])
def test_cached_divisor_matches_original_signed_remainder(divisibility_probe,mode,minimum):
    result=subprocess.run([str(divisibility_probe),mode],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    row=json.loads(result.stdout)
    assert row['passed'] and row['checks']>=minimum
    if mode=='boundaries':assert row['divisors']>10000
