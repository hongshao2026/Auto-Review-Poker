"""Exact integer remainder, rejection boundaries and random-stream parity."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('portable',[False,True])
def test_exact_fast_bound_and_rng_state(tmp_path,portable):
    info=json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text())
    exe=tmp_path/'probe.exe'
    command=[info['compiler'],'c++','-O2','-std=c++17','-ffp-contract=off']
    if portable: command+=['-DHRC_FAST_BOUND_PORTABLE=1']
    compiled=subprocess.run(command+[str(ROOT/'scripts/native/fast_bound_probe.cpp'),'-o',str(exe)],capture_output=True,text=True,timeout=120)
    assert compiled.returncode==0,compiled.stdout+compiled.stderr
    result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    row=json.loads(result.stdout)
    assert row['passed'] and row['exact_checks']>2_000_000
