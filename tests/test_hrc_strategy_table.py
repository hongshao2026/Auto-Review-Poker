import pytest

from test_server import app, await_job
from preflop_lab.hrc_benchmarks import config_for
from preflop_lab.hrc_custom import default_config


def test_preview_lists_each_unopened_position_without_inventing_frequencies(app):
    status, branch = app('/api/strategy-table', {'config': config_for('eight15bb', 1000)})
    assert status == 200
    rows = branch['rows']
    assert {row['actor'] for row in rows} == set(range(7))
    assert len(rows) == 14
    assert all(row['frequency'] is None and not row['range_text'] for row in rows)
    assert rows[0]['path'] == [] and rows[2]['path'] == ['0']
    assert rows[0]['action']['amount'] == 2
    assert all(row['action']['kind'] != 'fold' for row in rows)


def test_solved_action_frequency_matches_selected_parent_policy(app):
    cfg = default_config(2)
    cfg['iterations'] = 1000
    _, job = app('/api/jobs', {'config': cfg})
    assert await_job(app, job['id'])['status'] == 'completed'
    code, branch = app('/api/strategy-table', {'job_id': job['id']})
    assert code == 200
    first = branch['rows'][0]
    root = app(f"/api/jobs/{job['id']}/node")[1]
    action_index = next(i for i, action in enumerate(root['actions']) if action['id'] == first['action']['id'])
    total = weighted = 0
    for label, hand in root['strategy']['hands'].items():
        if not hand['visits']:
            continue
        w = 6 if len(label) == 2 else 4 if label.endswith('s') else 12
        total += w
        weighted += w * hand['frequencies'][action_index]
    assert first['frequency'] == pytest.approx(weighted / total)
    assert first['covered_combinations'] == total
    assert app('/api/strategy-table', {'job_id': job['id'], 'path': first['child_path']})[0] == 200


def test_invalid_branch_rejected_without_training(app):
    assert app('/api/strategy-table', {'config': config_for('eight15bb'), 'path': ['9999']})[0] == 400
