"""Exact outcome compression, independently settled chips, and bounded setup.

No original HRC payoffs/policies are inputs. Optional frozen-engine comparison
checks the prior production arithmetic in addition to the integer Python oracle.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import runpy
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/native/terminal_table_probe.cpp'
HEADER = ROOT / 'native/hrc_terminal_table.hpp'
FROZEN = ROOT / '.research-cache/throughput-architecture-20261107/baseline/hrc_research_solver.cpp'


def build_probe(frozen=False):
    digest = hashlib.sha256(SOURCE.read_bytes() + HEADER.read_bytes())
    if frozen:
        for file in sorted(FROZEN.parent.glob('*.hpp')):
            digest.update(file.read_bytes())
        digest.update(FROZEN.read_bytes())
    else:
        # This probe includes the production engine, whose scratch, layout and
        # dispatch may change independently of the terminal-table header.
        digest.update((ROOT/'native/hrc_research_solver.cpp').read_bytes())
        for file in sorted((ROOT/'native').glob('*.hpp')):
            digest.update(file.read_bytes())
    folder = ROOT / '.research-cache/terminal-table-tests'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (digest.hexdigest()[:20] + ('.exe' if os.name == 'nt' else ''))
    if not target.exists():
        zig = Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
        if zig.exists():
            command = [str(zig), 'c++']
        elif shutil.which('g++'):
            command = ['g++']
        else:
            pytest.skip('C++17 compiler unavailable')
        command += ['-O2', '-std=c++17', '-ffp-contract=off', '-pthread']
        if frozen:
            command += [f'-DHRC_TABLE_FROZEN_ENGINE="{FROZEN.as_posix()}"']
        subprocess.run(command + [str(SOURCE), '-o', str(target)], check=True,
                       capture_output=True, text=True, timeout=120)
    return target


@pytest.fixture(scope='module')
def probe():
    return build_probe()


def case(paid, *, folded=0, dead=0, base=None, ranks=None, scale=1,
         budget=100_000_000, cancel=0, mutation=0):
    paid = list(paid)
    if base is None:
        base = [-x for x in paid]
        base[0] -= dead
    return dict(paid=paid, folded=folded, dead=dead, base=base,
                ranks=list(ranks or [list(range(len(paid)))]), scale=scale,
                budget=budget, cancel=cancel, mutation=mutation)


def run(probe, cases):
    lines = [str(len(cases))]
    for x in cases:
        lines.append(' '.join(map(str, [len(x['paid']), x['folded'], x['dead'],
                                       x['scale'], x['budget'], x['cancel'],
                                       x['mutation'], len(x['ranks']),
                                       *x['base'], *x['paid'],
                                       *itertools.chain.from_iterable(x['ranks'])])))
    result = subprocess.run([str(probe)], input='\n'.join(lines)+'\n', capture_output=True,
                            text=True, check=True, timeout=60)
    parsed = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(parsed) == len(cases)
    return parsed


def oracle(x, ranks):
    """Integer sidepot layering, merged identical winners before odd chips."""
    paid = x['paid']
    live = [p for p in range(len(paid)) if not (x['folded'] >> p) & 1]
    layers = [(x['dead'], live)] if x['dead'] else []
    previous = 0
    for level in sorted(set(paid) - {0}):
        members = [p for p, chips in enumerate(paid) if chips >= level]
        eligible = [p for p in live if paid[p] >= level]
        layers.append(((level-previous)*len(members), eligible))
        previous = level
    groups = []
    for amount, eligible in layers:
        best = max(ranks[p] for p in eligible)
        winners = tuple(p for p in eligible if ranks[p] == best)
        if groups and groups[-1][1] == winners:
            groups[-1] = (groups[-1][0]+amount, winners)
        else:
            groups.append((amount, winners))
    result = x['base'].copy()
    for amount, winners in groups:
        share, odd = divmod(amount, len(winners))
        for p in winners:
            result[p] += share
        result[min(winners, key=lambda p: (paid[p], -p))] += odd
    return [v/x['scale'] for v in result]


def assert_cases(probe, cases):
    for x, result in zip(cases, run(probe, cases)):
        assert result['status'] == 'ok', (x, result)
        assert result['outcomes'] == 3 ** (len(x['paid']) - x['folded'].bit_count() - 1)
        assert result['values'] == [oracle(x, ranks) for ranks in x['ranks']], (x, result)
        assert result['concurrent_reads_stable']
        if 'frozen_engine_exact' in result:
            assert result['frozen_engine_exact'], x


def three_player_cases():
    ranks = list(itertools.product(range(3), repeat=3))  # every weak ordering, plus duplicate labels
    cases = [case(paid, ranks=ranks, scale=10000)
             for paid in itertools.permutations((3, 7, 11))]
    cases += [case([7, 7, 7], ranks=ranks), case([3, 3, 11], ranks=ranks),
              case([0, 7, 11], dead=5, ranks=ranks),
              case([7, 2, 7], folded=2, ranks=ranks),
              case([7, 2, 3], folded=6, ranks=ranks),
              case([0, 0, 0], dead=1, ranks=ranks),
              case([0, 0, 0], ranks=ranks)]
    return cases


def test_all_three_player_rank_orderings_sidepots_and_paid_permutations(probe):
    assert_cases(probe, three_player_cases())


def test_two_player_all_rank_combinations_and_folded_single_survivor(probe):
    ranks = list(itertools.product(range(3), repeat=2))
    assert_cases(probe, [case([5, 20], ranks=ranks), case([11, 11], dead=1, ranks=ranks),
                         case([20, 5], folded=2, ranks=ranks)])


def test_high_seat_odd_chip_and_merged_tie_layers(probe):
    cases = [case([100, 100, 100, 1, 2], folded=24, ranks=[[5, 5, 5, 99, 99]]),
             case([100, 100, 100, 1, 1], folded=24, ranks=[[5, 5, 5, 99, 99]]),
             case([5, 10, 10], dead=1, ranks=[[8, 8, 8]])]
    assert_cases(probe, cases)
    values = run(probe, cases)
    assert values[1]['values'] == [[0, 0, 2, -1, -1]]


def test_uncalled_upper_layer_return_and_folded_dead_money(probe):
    x = case([100, 30, 70], folded=4, ranks=[[0, 9, 99]])
    assert_cases(probe, [x])
    assert run(probe, [x])[0]['values'] == [[10, 60, -70]]


def test_rank_labels_are_order_only_including_negative_and_int_limits(probe):
    x = case([8, 3, 6], ranks=[[-2147483648, 0, 2147483647], [-3, 2, 9], [0, 1, 2]])
    assert_cases(probe, [x])
    result = run(probe, [x])[0]
    assert len(set(result['keys'])) == 1


def test_four_player_complete_rank_product_and_random_five_player_states(probe):
    randomizer = random.Random(71107)
    cases = [case([13, 3, 8, 8], ranks=list(itertools.product(range(4), repeat=4))),
             case([2, 2, 2, 1], folded=8, ranks=list(itertools.product(range(4), repeat=4)))]
    for _ in range(30):
        paid = [randomizer.randrange(1, 25) for _ in range(5)]
        # Keep highest contributor live: no invalid uncontested folded-only upper layer.
        highest = max(range(5), key=lambda p: paid[p])
        folded = randomizer.randrange(32) & ~(1 << highest)
        cases.append(case(paid, folded=folded, dead=randomizer.randrange(5),
                          ranks=[[randomizer.randrange(4) for _ in paid] for _ in range(35)]))
    assert_cases(probe, cases)


def test_budget_refusal_is_atomic_and_exact_budget_is_sufficient(probe):
    x = case([10, 20, 30])
    needed = run(probe, [x])[0]['bytes']
    assert run(probe, [dict(x, budget=needed-1)])[0]['status'] == 'declined'
    assert run(probe, [dict(x, budget=needed)])[0]['status'] == 'ok'
    assert run(probe, [dict(x, budget=0)])[0]['status'] == 'declined'


def test_multiple_terminal_offsets_remain_distinct(probe):
    result = run(probe, [case([3, 7, 11], mutation=6,
                              ranks=list(itertools.product(range(3), repeat=3)))])[0]
    assert result['status'] == 'ok'
    assert result['outcomes'] == 18
    assert result['multiple_entries_separate']


def test_only_contested_pot_ranks_are_required(probe):
    cases = [case([10, 5, 2], folded=6), case([10, 10, 0]), case([0, 0, 0])]
    results = run(probe, cases)
    assert [r['rank_mask'] for r in results] == [0, 3, 0]
    assert results[0]['null_ranks_constant'] and results[2]['null_ranks_constant']
    assert results[1]['mask'] == 7  # the uninvested live seat remains represented
    assert_cases(probe, cases)


def test_cancellation_before_and_during_build_does_not_publish_partial_table(probe):
    x = case(list(range(1, 11)))
    for calls in (1, 4, 7):
        result = run(probe, [dict(x, cancel=calls)])[0]
        assert result == {'status': 'cancelled', 'calls': calls}


def test_ten_player_outcome_capacity(probe):
    x = case(list(range(1, 11)), ranks=[[2]*10, list(range(10)), list(reversed(range(10)))])
    assert_cases(probe, [x])
    assert run(probe, [x])[0]['outcomes'] == 19683


@pytest.mark.parametrize('mutation', [1, 2, 3, 4, 5])
def test_invalid_nonnested_equal_paid_split_synthetic_and_fractional_states(probe, mutation):
    paid = [10, 10, 10] if mutation == 3 else [30, 20, 10]
    assert run(probe, [case(paid, mutation=mutation)])[0]['status'] == 'error'


@pytest.mark.parametrize('scale', [0, -1])
def test_invalid_scale(probe, scale):
    assert run(probe, [case([1, 2, 3], scale=scale)])[0]['status'] == 'error'


@pytest.mark.parametrize('folded', [7, 8])
def test_no_survivor_or_mask_outside_player_domain(probe, folded):
    assert run(probe, [case([1, 2, 3], folded=folded)])[0]['status'] == 'error'


@pytest.mark.skipif(not FROZEN.exists(), reason='Optional frozen prior-production source is local evidence')
def test_frozen_production_terminal_is_bitwise_identical():
    cases = three_player_cases()
    cases += [case([100, 100, 100, 1, 2], folded=24, ranks=list(itertools.product(range(3), repeat=5))),
              case([100, 30, 70], folded=4, ranks=list(itertools.product(range(3), repeat=3)))]
    assert_cases(build_probe(frozen=True), cases)


def check_real_binary(compact, tmp_path):
    """Production binary writer and frozen loader, no copied pot construction."""
    from preflop_lab.hrc_native import prepare

    compact['ci'] = {'enabled': True}  # exercise the actual HRTREE04 envelope
    prepared = prepare(compact, tmp_path)
    assert Path(prepared['tree_binary']).read_bytes()[:8] == b'HRTREE04'
    assert prepared['manifest']['original_leaf_values_read'] is False
    masks = [sum(1 << p for p, folded in enumerate(t['folded']) if folded)
             for t in compact['terminals']]
    result = subprocess.run([str(build_probe(frozen=True)), '--tree', prepared['tree_binary']],
                            input=' '.join(map(str, [len(masks), *masks])),
                            check=True, capture_output=True, text=True, timeout=60)
    row = json.loads(result.stdout)
    assert row['status'] == 'ok' and row['bitwise_mismatches'] == 0
    assert row['terminals'] == len(compact['terminals'])
    assert row['queries'] == len(compact['terminals']) * 3 ** compact['players']
    assert row['original_ev_read'] is False
    assert row['bytes'] <= 64 << 20
    return row


@pytest.mark.skipif(not FROZEN.exists(), reason='Frozen prior-production source is local evidence')
def test_real_hrtree_hu_tree_and_zero_contribution_bb_ante(tmp_path):
    from preflop_lab.hrc_tree_builder import build_tree, default_settings

    hu_tree = runpy.run_path(str(ROOT/'tests/test_hrc_kernel.py'))['hu_tree']
    hu = check_real_binary(hu_tree(), tmp_path/'hu')
    assert hu['terminals'] == 3 and hu['card_independent_terminals'] == 2
    settings = default_settings(2, [1000, 50], 100)
    settings['handdata']['blinds'][2] = 100
    tree = build_tree(settings).compact_export()
    assert tree['terminals'][0]['contributions'] == [50, 0]
    assert tree['terminals'][0]['dead_money'] == 50
    ante = check_real_binary(tree, tmp_path/'bbante')
    assert ante['terminals'] == 1 and ante['card_independent_terminals'] == 0


THREE_ARCHIVE = ROOT/'analysis/hrc-desktop/three40bb-wide-initial-20261107.hrcz'


@pytest.mark.skipif(not FROZEN.exists() or not THREE_ARCHIVE.exists(),
                    reason='Saved local topology/frozen prior-production evidence unavailable')
def test_real_three40bb_saved_topology_all_2178_leaves(tmp_path):
    from preflop_lab.hrc_hrcz_tree import replay_archive_tree

    # Explicitly read only structure/settings. Neither state.eqpre nor any
    # nodedata/strategy/terminal payoff member is opened.
    with zipfile.ZipFile(THREE_ARCHIVE) as archive:
        settings = json.loads(archive.read('settings.json'))
        topology = archive.read('gametree.dat')
    compact = replay_archive_tree(settings, topology).compact_export()
    assert len(compact['nodes']) == 3964 and len(compact['terminals']) == 2178
    result = check_real_binary(compact, tmp_path/'three40')
    assert result['queries'] == 58_806
