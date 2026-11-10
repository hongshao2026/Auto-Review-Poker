"""Long-run completion must use fresh numeric CI and stable original idle."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('hrc_longrun', Path(__file__).resolve().parents[1]/'scripts/watch-hrc-ci-longrun.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def record(**values):
    return {'event': 'original_mr_constructor', 'index': 0, 'ci': 9.9,
            'original_epoch_millis': 2000, **values}


@pytest.mark.parametrize('values', [dict(index=-1), dict(original_epoch_millis=0),
    dict(ci=None), dict(ci=float('nan')), dict(ci=float('inf')), dict(ci=True), dict(ci=-1)])
def test_discard_synthetic_stale_or_invalid_ci(values):
    assert not watch.valid_ci(record(**values), 1000)


def test_live_ci_record_and_final_hand_filename():
    assert watch.valid_ci(record(), 1000)
    rows = [{'class': 'Edit', 'text': r'D:\runs\working.hrcz', 'enabled': True},
            {'class': 'Edit', 'text': 'Hand 1.hrcz', 'enabled': True}]
    assert watch.matching_edit(rows, 'working.hrcz') == [rows[0]]
    assert watch.matching_edit(rows, 'other.hrcz') == []


def test_only_fresh_ci_strictly_below_target_and_two_idle_polls_complete():
    active = [{'text': 'MC-CFR [Target CI < 10.00]'}]
    idle = [{'text': 'No operations to display at this time.'}]
    assert watch.classify(active, False, 0, 9.9, 10, False)[-1] is False
    first = watch.classify(idle, True, 0, 9.9, 10, False)
    assert first[-1] is False
    assert watch.classify(idle, True, first[2], 9.9, 10, False)[-1] is True
    for ci in (None, 10, 10.01):
        assert watch.classify(idle, True, 10, ci, 10, False)[-1] is False
    assert watch.classify(idle, True, 10, 9.9, 10, True)[-1] is False
    assert watch.classify(idle, False, 0, 9.9, 10, False)[-1] is False
    # A backgrounded progress dialog must not be mistaken for finished work.
    assert watch.classify(idle, True, 10, 9.9, 10, False, cpu_busy=True)[-1] is False
