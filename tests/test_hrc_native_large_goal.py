"""Explicit CLI cumulative limits; high-count headers are isolated test fixtures.

No benchmark or user checkpoint is modified. A synthetic header changes only
the global counter; learned arrays/RNG are compared with a real short resume.
"""
import json
import struct
import subprocess

import pytest

from preflop_lab.hrc_native import build, run
from test_hrc_kernel import hu_tree


def command(exe, tree, resources, output, goal, *, resume=None, budget=None, reset=False):
    args = [str(exe), str(tree), str(resources), str(goal), '43', str(output), 'v4',
            str(resume) if resume else '-', str(int(reset)), str(int(reset)),
            '-1', '-1', '-1', str(1<<30), '1', '1', '-', '0', '0']
    if budget is not None: args.append(str(budget))
    return args


def execute(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=20)


@pytest.fixture(scope='module')
def executable(): return build()


@pytest.mark.parametrize('goal,budget,error', [
    (1_000_000_001, None, 'Maximum 1000000000 samples'),
    (1_000_000_000_001, 1, 'Maximum cumulative samples'),
    (100, 0, 'Additional sample budget'),
    (100, 1_000_000_000_001, 'Additional sample budget'),
])
def test_large_goal_and_budget_domains_reject_before_loading(executable, tmp_path, goal, budget, error):
    output = tmp_path/'output'
    result = execute(command(executable, tmp_path/'missing.bin', tmp_path, output, goal, budget=budget))
    assert result.returncode != 0 and error in result.stderr
    assert not output.exists()


def synthetic_header(source, destination, samples):
    destination.mkdir()
    data = bytearray((source/'checkpoint.bin').read_bytes())
    struct.pack_into('<Q', data, 16, samples)
    (destination/'checkpoint.bin').write_bytes(data)
    index = json.loads((source/'index.json').read_text())
    index.update(samples=samples, root_mean_valid=False)
    (destination/'index.json').write_text(json.dumps(index))
    (destination/'FIXTURE_ONLY.txt').write_text('Synthetic global counter for isolated validator test; not a training result.')


def test_cross_1b_resume_preserves_rng_and_every_learned_byte(executable, tmp_path):
    base = tmp_path/'base'; run(hu_tree(), tmp_path, 500, 43, base)
    artificial = tmp_path/'synthetic'; before = 999_999_500
    synthetic_header(base, artificial, before)
    high = tmp_path/'high'
    result = execute(command(executable, base/'tree.bin', tmp_path, high, before+1000,
                             resume=artificial/'checkpoint.bin', budget=1000))
    assert result.returncode == 0, result.stderr
    low = tmp_path/'control'; run(hu_tree(), tmp_path, 1500, 43, low,
                                 resume_from=base/'checkpoint.bin', root_mean_valid=False)
    a, b = (high/'checkpoint.bin').read_bytes(), (low/'checkpoint.bin').read_bytes()
    assert a[:16]+a[24:] == b[:16]+b[24:]
    assert struct.unpack_from('<Q', a, 16)[0] == 1_000_000_500
    index = json.loads((high/'index.json').read_text())
    assert index['samples'] == 1_000_000_500 and index['nodes'][0]['updates'] == 1500
    assert not index['root_mean_valid']


def test_incremental_budget_checked_before_reset_output_or_save(executable, tmp_path):
    base = tmp_path/'base'; run(hu_tree(), tmp_path, 500, 43, base)
    source = (base/'checkpoint.bin').read_bytes(); output = tmp_path/'rejected'
    result = execute(command(executable, base/'tree.bin', tmp_path, output, 1001,
                             resume=base/'checkpoint.bin', budget=500, reset=True))
    assert result.returncode != 0 and 'additional samples exceed' in result.stderr
    assert not output.exists() and (base/'checkpoint.bin').read_bytes() == source


def test_upper_cumulative_boundary_round_trips_without_training(executable, tmp_path):
    base = tmp_path/'base'; run(hu_tree(), tmp_path, 0, 43, base)
    artificial = tmp_path/'synthetic'; synthetic_header(base, artificial, 1_000_000_000_000)
    output = tmp_path/'no_work'
    result = execute(command(executable, base/'tree.bin', tmp_path, output, 1_000_000_000_000,
                             resume=artificial/'checkpoint.bin', budget=1))
    assert result.returncode == 0, result.stderr
    assert (output/'checkpoint.bin').read_bytes() == (artificial/'checkpoint.bin').read_bytes()
    last = json.loads(result.stdout.splitlines()[-1])
    assert last['iteration'] == 1_000_000_000_000 and last['scalar_calls'] == last['vector_calls'] == 0


def test_python_run_limit_matches_explicit_native_cumulative_domain(tmp_path):
    with pytest.raises(ValueError, match='1,000,000,000,000'):
        run(hu_tree(), tmp_path, 1_000_000_000_001, 43, tmp_path/'no_run')


def test_python_adapter_large_resume_preserves_rng_and_learned_bytes(tmp_path):
    base = tmp_path/'base'; run(hu_tree(), tmp_path, 500, 43, base)
    artificial = tmp_path/'synthetic'; before = 2_999_999_500
    synthetic_header(base, artificial, before)
    high = tmp_path/'high'
    result = run(hu_tree(), tmp_path, before+1000, 43, high,
                 resume_from=artificial/'checkpoint.bin', root_mean_valid=False)
    low = tmp_path/'control'; run(hu_tree(), tmp_path, 1500, 43, low,
                                 resume_from=base/'checkpoint.bin', root_mean_valid=False)
    a, b = (high/'checkpoint.bin').read_bytes(), (low/'checkpoint.bin').read_bytes()
    assert a[:16]+a[24:] == b[:16]+b[24:]
    assert result['summary']['iteration'] == 3_000_000_500
