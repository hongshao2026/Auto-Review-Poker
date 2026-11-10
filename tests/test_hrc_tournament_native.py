"""Exercise tournament inputs through real native dealing, settlement and resume."""
from copy import deepcopy
import json
import subprocess

import pytest

from preflop_lab.hrc_native import build, read_node, run
from test_hrc_kernel import hu_tree


def model(kind='none', mtt=False):
    return {'mode': 'mtt_icm' if mtt else 'icm', 'payouts': [50, 30, 20] if mtt else [70, 30],
            'other_stacks': [1500, 500] if mtt else [],
            'bounty': {'mode': kind, 'amounts': [10, 10] if kind != 'none' else [0, 0],
                       'other_amounts': ([10, 10] if kind != 'none' else [0, 0]) if mtt else [],
                       'immediate_fraction': .5 if kind == 'pko' else 1}}


@pytest.mark.parametrize('kind', ['none', 'ko', 'pko'])
@pytest.mark.parametrize('mtt', [False, True])
def test_real_tournament_training_and_resume(kind, mtt, tmp_path):
    tree = hu_tree()
    tree['equity'] = model(kind, mtt)
    direct, partial, resumed = [tmp_path / name for name in ('direct', 'partial', 'resumed')]
    result = run(tree, tmp_path, 2000, 42, direct)
    run(tree, tmp_path, 750, 42, partial)
    run(tree, tmp_path, 2000, 123, resumed, resume_from=partial / 'checkpoint.bin')
    assert (direct / 'checkpoint.bin').read_bytes() == (resumed / 'checkpoint.bin').read_bytes()
    assert result['summary']['utility'] == 'net_payout'
    index = json.loads((direct / 'index.json').read_text())
    assert 'root_mean_net_bb' not in index
    assert len(index['root_mean_net_payout']) == 2
    root = read_node(direct, 0)
    assert root['updates'] == 2000
    assert sum(h['visits'] for h in root['hands']) == 2000
    assert sum(h['trained'] for h in root['hands']) > 150
    assert all(sum(h['display_strategy']) == pytest.approx(1) for h in root['hands'])
    changed = deepcopy(tree)
    changed['equity']['payouts'][0] += 1
    with pytest.raises(RuntimeError, match='identity mismatch'):
        run(changed, tmp_path, 2100, 42, tmp_path / 'wrong-model', resume_from=direct / 'checkpoint.bin')


def test_engine_assigns_bounty_to_actual_side_pot_and_shared_winners():
    rows = {r['id']: r['actual'] for r in map(json.loads, subprocess.check_output([str(build()), '--self-test'], text=True).splitlines())}
    assert rows['settlement.pko_side_pot_killer'] == pytest.approx([26, -20, 25, -31])
    assert rows['settlement.ko_shared_killer'] == pytest.approx([5, -10, 5])


def test_original_icm_three_player_fold_equity_flows_into_native_root(tmp_path):
    # Deterministic terminal, unequal stacks. Independently enumerate all rankings.
    from itertools import permutations
    initial, final, prizes = [100, 200, 300], [50, 250, 300], [60, 30, 10]
    def equity(stacks):
        values = [0.] * 3
        for order in permutations(range(3)):
            chance, left = 1., sum(stacks)
            for seat in order:
                chance *= stacks[seat] / left
                left -= stacks[seat]
            for rank, seat in enumerate(order):
                values[seat] += chance * prizes[rank]
        return values
    tree = {'root': 0, 'players': 3, 'big_blind': 100, 'initial_stacks': initial,
            'nodes': [{'id': 0, 'actor': -1, 'street': 0, 'buckets': 0, 'children': [], 'actions': [], 'terminal_id': 0}],
            'terminals': [{'remaining': [50, 100, 300], 'contributions': [50, 100, 0], 'folded': [True, False, True]}],
            'equity': {'mode': 'icm', 'payouts': prizes}}
    run(tree, tmp_path, 1, 42, tmp_path / 'terminal')
    index = json.loads((tmp_path / 'terminal/index.json').read_text())
    expected = [a - b for a, b in zip(equity(final), equity(initial))]
    assert index['root_mean_net_payout'] == pytest.approx(expected, abs=1e-12)
