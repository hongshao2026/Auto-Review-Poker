"""Pairwise monetary risk analysis, including shared native model semantics."""
from copy import deepcopy
import math

import pytest

from preflop_lab.hrc_analysis import analyze_solver
from preflop_lab.hrc_custom import default_config, HRCCustomSolver
from test_server import app


def config():
    cfg = default_config(3)
    cfg.update(utility='icm', payouts=[50, 30, 20])
    cfg['tree_settings']['preflop']['settings']['PREFLOP_SIZES'] = ['all-in'] * 4
    cfg['tree_settings']['preflop']['settings']['ALLOWED_FLATS_PER_RAISE'] = [0] * 5
    return cfg


def test_three_equal_stacks_formula_and_units(app):
    cfg = config()
    code, result = app('/api/tournament-analysis', {'config': cfg})
    assert code == 200, result
    assert result['baseline_equities'] == pytest.approx([100/3] * 3)
    for pair in result['pairs']:
        assert pair['bubble_factor'] == pytest.approx(4/3)
        assert pair['risk_premium_pp'] == pytest.approx(100/14)
        assert pair['win_equity'] == pytest.approx(130/3)
        assert pair['lose_equity'] == 20
    assert all(result['bubble_factors'][i][i] is None for i in range(3))
    cfg.update(fgs={'enabled': True, 'depth': 3}, ante=2)
    changed = analyze_solver(HRCCustomSolver(cfg))
    assert changed['baseline_equities'] == result['baseline_equities']
    assert changed['bubble_factors'] == result['bubble_factors'] and not changed['fgs_applied']


@pytest.mark.parametrize('kind', ['none', 'ko', 'pko'])
def test_mtt_bounty_pairwise_values_against_combined_field_oracle(kind):
    from test_hrc_equity import oracle
    cfg = config()
    cfg.update(utility='mtt_icm', other_stacks=[10, 30], payouts=[50, 30, 15, 5])
    heads = [0, 0, 0] if kind == 'none' else [10, 10, 10] if kind == 'ko' else [5, 10, 20]
    outer = [0, 0] if kind == 'none' else [10, 10]
    cfg['bounty'] = {'mode': kind, 'amounts': heads, 'other_amounts': outer, 'immediate_fraction': .5 if kind == 'pko' else 1}
    solver = HRCCustomSolver(cfg)
    result = analyze_solver(solver)
    initial = list(solver.tree.rules.initial_stacks)
    base_case = {'initial': initial, 'payouts': cfg['payouts'], 'bounty_mode': ('none', 'ko', 'pko').index(kind),
                 'bounties': heads, 'other_stacks': [100000, 300000], 'other_bounties': outer, 'alpha': cfg['bounty']['immediate_fraction']}
    for pair in result['pairs']:
        i, j = pair['row'], pair['column']
        effective = min(initial[i], initial[j])
        for name, winner, loser in [('win_equity', i, j), ('lose_equity', j, i)]:
            final = initial[:]
            final[winner] += effective
            final[loser] -= effective
            masks = [0] * 3
            if not final[loser]:
                masks[loser] = 1 << winner
            target = oracle({**base_case, 'final': final, 'masks': masks})['total'][i]
            # MTT intentionally reproduces the original numerical quadrature,
            # whose integration stopping tolerance is not exact finite ICM.
            assert pair[name] == pytest.approx(target, abs=2e-5)


def test_flat_prizes_are_explicitly_undefined():
    cfg = config()
    cfg['payouts'] = [10] * 3
    result = analyze_solver(HRCCustomSolver(cfg))
    assert all(p['state'] == 'undefined' and p['bubble_factor'] is None and p['risk_premium_pp'] is None for p in result['pairs'])
