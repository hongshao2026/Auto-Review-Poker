from copy import deepcopy
import pytest

from preflop_lab.tournament import default_config, equity_spec, validated_config
from preflop_lab.server import make_solver


def test_tournament_keeps_fixed_topology_and_payout_units():
    cfg = default_config()
    cfg.update(utility='mtt_icm', other_stacks=[7.5, 30], payouts=[100, 50, 25])
    cfg['bounty'] = {'mode': 'pko', 'amounts': [10] * 8,
                     'other_amounts': [5, 20], 'immediate_fraction': .5}
    actual = validated_config(cfg)
    model = equity_spec(actual, 10000)
    assert model['other_stacks'] == [75000, 300000]
    assert model['payouts'] == [100, 50, 25]
    assert model['bounty']['amounts'] == [10] * 8
    solver = make_solver(actual)
    node = solver.describe_node(['0'] * 5)
    assert node['actor_name'] == 'BTN' and node['remaining'][5] == 15
    assert node['utility_unit'] == 'currency'
    assert solver.reference is None


@pytest.mark.parametrize('change', [
    {'players': []}, {'open_sizes': [3]}, {'utility': 'chips'},
    {'other_stacks': [10]}, {'payouts': [50, 100]}, {'payouts': []},
    {'payouts': [0]}, {'payouts': [float('nan')]},
    {'utility': 'mtt_icm', 'other_stacks': [0]},
    {'bounty': {'mode': 'none', 'amounts': [10] * 8}},
    {'bounty': {'mode': 'ko', 'amounts': [10] * 7 + [20]}},
    {'bounty': {'mode': 'ko', 'amounts': [10] * 8, 'immediate_fraction': .5}},
    {'bounty': {'mode': 'pko', 'amounts': [10] * 7}},
    {'bounty': {'mode': 'pko', 'amounts': [10] * 8, 'immediate_fraction': 1.1}},
])
def test_inconsistent_tournament_fields_fail_before_training(change):
    cfg = default_config()
    cfg.update(deepcopy(change))
    with pytest.raises(ValueError):
        validated_config(cfg)


def test_bounty_only_event_and_zero_bounty_players_are_explicit():
    cfg = default_config()
    cfg.update(payouts=[0], bounty={'mode': 'pko', 'amounts': [0, 20] + [5] * 6,
                                  'other_amounts': [], 'immediate_fraction': .5})
    assert validated_config(cfg)['payouts'] == [0]
