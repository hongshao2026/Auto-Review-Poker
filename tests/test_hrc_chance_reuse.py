"""Reused native deal storage must preserve the independent Python draw log."""
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess

import pytest

from preflop_lab.hrc_chance import ChanceSampler

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def probe():
    source = ROOT / 'scripts/native/chance_probe.cpp'
    header = ROOT / 'native/hrc_chance.hpp'
    digest = hashlib.sha256(source.read_bytes() + header.read_bytes()).hexdigest()[:20]
    folder = ROOT / '.research-cache/chance-reuse-tests'
    folder.mkdir(exist_ok=True)
    exe = folder / (digest + '.exe')
    zig = Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')
    if not zig.exists():
        pytest.skip('Local native test compiler unavailable')
    if not exe.exists():
        subprocess.run([str(zig), 'c++', '-O2', '-std=c++17', str(source), '-o', str(exe)],
                       check=True, capture_output=True, timeout=120)
    return exe


@pytest.mark.parametrize('reuse', [False, True])
def test_deal_and_every_random_draw_match_python_across_reused_configurations(tmp_path, probe, reuse):
    flop = (1 << 40) | (1 << 44) | (1 << 48)
    board = [0, flop, flop | (1 << 50), flop | (1 << 50) | (1 << 51)]
    rng = random.Random(824)
    integers = list(range(1326))
    rng.shuffle(integers)
    doubles = [rng.random() for _ in range(500)]
    lines, expected = [], {}
    # Alternate seat counts/prefix lengths, exercising scratch resets between
    # preflop, flop, turn and river; include dead cards and mode2 uniform target.
    for seats in (2, 8, 3):
        for length in (4, 1, 3, 2):
            for skip in (-1, 0):
                name = f'n{seats}-b{length}-s{skip}'
                ranges = [[1.] * 1326 if p < 2 else None for p in range(seats)]
                for row in ranges[:2]:
                    row[0], row[100], row[1325] = 0., 4., 2.
                spec = ';'.join('1|0:0,100:4,1325:2' if row is not None else '-' for row in ranges)
                lines.append('\t'.join([name, ','.join(map(str, board[:length])), spec,
                                       ','.join(map(repr, doubles)), ','.join(map(str, integers)), str(skip)]))
                ii = di = 0
                calls = bytearray()
                def integer(bound):
                    nonlocal ii
                    value = integers[ii % len(integers)] % bound
                    ii += 1
                    calls.extend(struct.pack('<IQ', bound, value))
                    return value
                def real():
                    nonlocal di
                    value = doubles[di % len(doubles)]
                    di += 1
                    calls.extend(struct.pack('<I', 0) + struct.pack('<d', value))
                    return value
                deal = ChanceSampler(ranges, board[:length], max_attempts=10000).sample_callbacks(
                    integer, real, skip_player=skip)
                expected[name] = (deal, bytes(calls), ii, di)
    source = tmp_path / 'cases.tsv'
    source.write_text('\n'.join(lines), encoding='utf-8')
    output = tmp_path / 'calls'
    cmd = [str(probe), str(source), str(output)] + (['--reuse'] if reuse else [])
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
    rows = [json.loads(line) for line in completed.stdout.splitlines()]
    assert len(rows) == len(expected)
    for row in rows:
        deal, calls, ii, di = expected[row['id']]
        assert row['status'] == 'ok'
        assert row['combos'] == list(deal.combos)
        assert row['board'] == list(deal.board_history)
        assert row['used'] == deal.used_mask and row['attempts'] == deal.attempts
        assert row['integer_calls'] == ii and row['double_calls'] == di
        assert (output / (row['id'] + '.calls')).read_bytes() == calls
