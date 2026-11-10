"""Hand alignment and cancellation hidden by aggregate action frequencies."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('three40_compare', Path(__file__).resolve().parents[1]/'scripts/compare-hrc-three40bb-ci10.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_native_bucket_order_is_not_display_matrix_order():
    rows = [{'bucket': 0, 'visits': 5}, {'bucket': 168, 'visits': 99}]
    actual = module.native_hands_by_label(rows)
    assert actual['22']['visits'] == 5
    assert actual['AA']['visits'] == 99


def test_equal_aggregate_policies_can_hide_opposite_hand_errors():
    rows = [{'combos': 6, 'hrc': [1., 0.], 'ours': [0., 1.],
             'hrc_ev_bb': [0., .01], 'ours_ev_bb': [0., .02],
             'ours_visits': 10, 'hrc_average_trained': True},
            {'combos': 6, 'hrc': [0., 1.], 'ours': [1., 0.],
             'hrc_ev_bb': None, 'ours_ev_bb': None,
             'ours_visits': 0, 'hrc_average_trained': False}]
    result = module.metrics(rows)
    assert result['aggregate_TV_pp'] == 0
    assert result['combo_weighted_hand_TV_pp'] == 100
    assert result['action_MAE_pp'] == 100
    assert result['historical_relative_EV_MAE_bb'] == pytest.approx(.01)
    assert result['both_trained_combos'] == result['EV_covered_combos'] == 6
