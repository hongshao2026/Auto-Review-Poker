"""Compare shared monetary payoffs with the production fallback and saved RNG."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from preflop_lab.hrc_custom import HRCCustomSolver, default_config
from preflop_lab.hrc_native import ROOT, build, prepare
from preflop_lab.hrc_training import solver_compact


def monetary_tree(utility='mtt_icm', bounty='none', players=4):
    cfg = default_config(players)
    cfg.update(chip_scale=100, utility=utility, ante=.03, ante_type='REGULAR')
    for i, seat in enumerate(cfg['players']):
        seat['stack'] = [1.37, 2.19, 3.11, 4.23][i]
    cfg['payouts'] = [100, 60, 40][:players]
    cfg['other_stacks'] = [.75 + .05*i for i in range(50)] if utility == 'mtt_icm' else []
    if cfg['other_stacks']:
        cfg['payouts'] += [float(40-i) for i in range(1, 38)]
    cfg['bounty'] = dict(mode=bounty, amounts=[0 if bounty == 'none' else 7 if bounty == 'ko' else i+1 for i in range(players)],
        other_amounts=[0 if bounty == 'none' else 7 if bounty == 'ko' else 2]*len(cfg['other_stacks']),
        immediate_fraction=.5 if bounty == 'pko' else 1)
    cfg['tree_settings']['preflop']['settings'].update(PREFLOP_SIZES=['all-in']*4, ALLOWED_FLATS_PER_RAISE=[0]*5)
    cfg['tree_settings']['postflop']['settings']['POSTFLOP_FORCE_CHECKDOWN_AFTER'] = [0]*9
    return solver_compact(HRCCustomSolver(cfg))


@pytest.fixture(scope='module')
def monetary_probe():
    source = ROOT / 'scripts/native/monetary_terminal_table_probe.cpp'
    identity = hashlib.sha256(source.read_bytes())
    for file in [ROOT/'native/hrc_research_solver.cpp', *sorted((ROOT/'native').glob('*.hpp'))]:
        identity.update(file.read_bytes())
    target = ROOT / '.research-cache/terminal-table-tests' / (identity.hexdigest()[:20] + '.exe')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        zig = Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
        subprocess.run([str(zig), 'c++', '-O2', '-std=c++17', '-ffp-contract=off', '-pthread', str(source), '-o', str(target)],
                       check=True, capture_output=True, text=True, timeout=180)
    return target


@pytest.mark.parametrize('utility', ['icm', 'mtt_icm'])
@pytest.mark.parametrize('bounty', ['none', 'ko', 'pko'])
def test_every_live_rank_assignment_matches_legacy_settlement(monetary_probe, tmp_path, utility, bounty):
    data = prepare(monetary_tree(utility, bounty), tmp_path/'input')
    result = subprocess.run([str(monetary_probe), data['tree_binary'], str(tmp_path), str(64 << 20)],
                            check=True, capture_output=True, text=True, timeout=180)
    row = json.loads(result.stdout)
    assert row['mismatches'] == 0 and row['queries'] > row['terminals']
    assert row['rng_samples_unchanged'] and row['outcomes'] > 0
    refused = subprocess.run([str(monetary_probe), data['tree_binary'], str(tmp_path), '1'],
                             check=True, capture_output=True, text=True, timeout=60)
    assert json.loads(refused.stdout)['refused']


def command(exe, binary, resources, output, goal, table, resume=None, scope=None, threads=1):
    return [str(exe), str(binary), str(resources), str(goal), '43', str(output), 'v4',
        str(resume) if resume else '-', '0', '0', '-1', '-1', '-1', str(1 << 30), str(threads), '0',
        str(scope) if scope else '-', '0', '0' if scope else '1', str(max(1, goal)), str(int(table))]


@pytest.mark.parametrize('utility,bounty', [('icm','none'), ('mtt_icm','none'), ('mtt_icm','pko')])
def test_training_checkpoint_identical_with_and_without_tables(tmp_path, utility, bounty):
    exe = build()
    binary = prepare(monetary_tree(utility,bounty), tmp_path/'input')['tree_binary']
    outputs = []
    for enabled in (False, True):
        output = tmp_path / str(enabled)
        result = subprocess.run(command(exe, binary, tmp_path, output, 3000, enabled),
                                check=True, capture_output=True, text=True, timeout=120)
        summary = json.loads(result.stdout.splitlines()[-1])
        assert summary['terminal_tables'] == enabled
        assert summary['terminal_pointer_cache'] == enabled
        if enabled:
            assert summary['terminal_settlements'] == 0 and summary['terminal_table_lookups'] > 0
        outputs.append((output/'checkpoint.bin').read_bytes())
    assert outputs[0] == outputs[1]


def test_selected_subtree_resume_matches_frozen_old_executable(tmp_path):
    import struct
    frozen = ROOT / '.research-cache/cpu-round4-20261108/accepted/solver.exe'
    if not frozen.exists():
        pytest.skip('Pinned previous executable unavailable')
    exe = build()
    binary = prepare(monetary_tree(), tmp_path/'input')['tree_binary']
    initial = tmp_path/'initial'
    subprocess.run(command(frozen,binary,tmp_path,initial,1000,False),check=True,capture_output=True,text=True,timeout=120)
    scope = tmp_path/'scope.bin';scope.write_bytes(b'HRSCOPE1'+struct.pack('<II',1,0))
    outputs = []
    for name, current, enabled in [('old',frozen,False), ('new',exe,True)]:
        output = tmp_path/name
        result = subprocess.run(command(current,binary,tmp_path,output,4000,enabled,initial/'checkpoint.bin',scope),
                                check=True,capture_output=True,text=True,timeout=120)
        summary=json.loads(result.stdout.splitlines()[-1])
        assert summary['sampling_scope']=='selected_subtree' and summary['iteration']==4000
        outputs.append((output/'checkpoint.bin').read_bytes())
    assert outputs[0]==outputs[1]
