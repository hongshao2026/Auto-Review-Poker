"""Constant chip continuation, cache boundaries and checkpoint I/O regressions."""
import json
import subprocess

import pytest

from preflop_lab.hrc_native import build, read_node, run
from test_hrc_kernel import hu_tree
from test_server import app, await_job


def folded_continuation():
    # BTN folds, then SB/BB continue: BTN always loses zero chips in this
    # subtree. The alternate branch is BTN shove with SB already folded.
    children = [[1, 2], [3, 4], [7, 8], [], [5, 6], [], [], [], []]
    actors = [0, 1, 2, -1, 2, -1, -1, -1, -1]
    leaves = {3: 0, 5: 1, 6: 2, 7: 3, 8: 4}
    nodes = [{'id': i, 'actor': actors[i], 'street': 0, 'buckets': 169 if c else 0,
              'children': c, 'actions': [0, 3] if c else [], 'terminal_id': leaves.get(i, -1)}
             for i, c in enumerate(children)]
    terms = []
    for paid, folded in [([0, 50, 100], [True, True, False]),
                         ([0, 1000, 100], [True, False, True]),
                         ([0, 1000, 1000], [True, False, False]),
                         ([1000, 50, 100], [False, True, True]),
                         ([1000, 50, 1000], [False, True, False])]:
        terms.append({'remaining': [1000-p for p in paid], 'contributions': paid, 'folded': folded})
    return {'root': 0, 'players': 3, 'big_blind': 100,
            'initial_stacks': [1000]*3, 'nodes': nodes, 'terminals': terms}


def test_constant_scalar_proof_and_winner_cache_probes():
    rows = {r['id']: r['actual'] for r in map(json.loads, subprocess.check_output([str(build()), '--self-test'], text=True).splitlines())}
    assert rows['constant_scalar.reordered_tree_exact_value'] == [1, -.5, 0]
    assert rows['constant_scalar.never_skips_target_decision'] == [0]
    assert rows['constant_scalar.rake_disabled'] == [0, 0]
    assert rows['winner_cache.exhaustive_subsets_and_epochs'] == [0, 49_104]
    assert rows['checkpoint.fast_write_time_boundaries'] == [0, 1]
    assert rows['checkpoint.expensive_write_backoff'] == [140, 0, 1]
    assert rows['checkpoint.recovery_interval_bounds'] == [30, 300]


@pytest.mark.parametrize('mode', ['v3', 'v4'])
@pytest.mark.parametrize('reverse_ids', [False, True])
def test_shortcut_resume_and_reordered_topology(tmp_path, mode, reverse_ids):
    tree = folded_continuation()
    if reverse_ids:
        count = len(tree['nodes'])
        for n in tree['nodes']:
            n['id'] = count-1-n['id']; n['children'] = [count-1-c for c in n['children']]
        tree['nodes'].reverse(); tree['root'] = count-1
    direct, partial, resumed = [tmp_path/n for n in ('direct', 'partial', 'resumed')]
    result = run(tree, tmp_path, 3000, 43, direct, mode=mode)
    assert result['summary']['constant_scalar_shortcuts']
    assert result['summary']['constant_scalar_nodes'] > 0
    assert result['summary']['constant_scalar_calls'] > 0
    run(tree, tmp_path, 1377, 43, partial, mode=mode)
    run(tree, tmp_path, 3000, 1, resumed, mode=mode, resume_from=partial/'checkpoint.bin')
    assert (direct/'checkpoint.bin').read_bytes() == (resumed/'checkpoint.bin').read_bytes()
    run(tree, tmp_path, 4000, 1, tmp_path/'off', mode=mode,
        resume_from=partial/'checkpoint.bin', constant_scalar_shortcuts=False)
    assert not json.loads((tmp_path/'off/summary.json').read_text())['constant_scalar_shortcuts']
    assert read_node(tmp_path/'off', tree['root'])['updates'] == 4000


@pytest.mark.parametrize('kind', ['icm', 'pko', 'mtt'])
def test_monetary_models_disable_chip_shortcuts_exactly(tmp_path, kind):
    tree = folded_continuation()
    tree['equity'] = {'mode': 'mtt_icm' if kind == 'mtt' else 'icm', 'payouts': [70, 30],
                      'other_stacks': [1000] if kind == 'mtt' else [],
                      'bounty': {'mode': 'pko' if kind == 'pko' else 'none',
                                 'amounts': [10]*3 if kind == 'pko' else [0]*3,
                                 'other_amounts': [0] if kind == 'mtt' else [], 'immediate_fraction': .5}}
    for enabled in (True, False):
        result = run(tree, tmp_path, 2000, 43, tmp_path/str(enabled), constant_scalar_shortcuts=enabled)
        assert not result['summary']['constant_scalar_shortcuts']
        assert result['summary']['constant_scalar_calls'] == 0
    assert (tmp_path/'True/checkpoint.bin').read_bytes() == (tmp_path/'False/checkpoint.bin').read_bytes()


def test_shared_workers_count_shortcuts_and_keep_global_samples(tmp_path):
    tree = folded_continuation()
    result = run(tree, tmp_path, 4000, 43, tmp_path/'parallel', threads=4)
    assert result['summary']['constant_scalar_calls'] > 0
    node = read_node(tmp_path/'parallel', 0)
    assert node['updates'] == sum(h['visits'] for h in node['hands']) == 4000


@pytest.mark.parametrize('threads', [1, 4])
@pytest.mark.parametrize('samples,writes', [(0, 1), (1_000_000, 2), (1_000_250, 2)])
def test_short_runs_save_complete_state_without_sample_based_pauses(tmp_path, samples, writes, threads):
    result = run(hu_tree(), tmp_path, samples, 43, tmp_path/'run', threads=threads)
    assert result['summary']['checkpoint_writes'] == writes
    assert result['summary']['checkpoint_seconds'] >= 0
    assert result['summary']['checkpoint_policy'] == 'adaptive_wall_time'
    index = json.loads((tmp_path/'run/index.json').read_text())
    assert index['samples'] == samples and index['training_threads'] == threads
    node = read_node(tmp_path/'run', 0)
    assert node['updates'] == sum(h['visits'] for h in node['hands']) == samples


def test_graceful_cancel_saves_latest_state_and_resume_is_exact(tmp_path):
    tree = hu_tree()
    progress = []
    result = run(tree, tmp_path, 100_000_000, 43, tmp_path/'cancelled',
                 progress_callback=lambda row: progress.append(row),
                 cancel_check=lambda: any(row.get('kind') == 'progress' for row in progress))
    saved = result['summary']['iteration']
    assert result['summary']['stop_reason'] == 'cancelled'
    assert 0 < saved < 100_000_000
    index = json.loads((tmp_path/'cancelled/index.json').read_text())
    assert index['samples'] == saved
    assert read_node(tmp_path/'cancelled', 0)['updates'] == saved
    # Cancellation occurs long before the periodic interval; final saving must
    # retain every completed sample, the primary RNG and all accumulator bytes.
    target = saved+1250
    run(tree, tmp_path, target, 99, tmp_path/'resumed', resume_from=tmp_path/'cancelled/checkpoint.bin')
    run(tree, tmp_path, target, 43, tmp_path/'direct')
    assert (tmp_path/'resumed/checkpoint.bin').read_bytes() == (tmp_path/'direct/checkpoint.bin').read_bytes()


def test_no_work_ci_resume_saves_flushed_store_and_ci_metadata(tmp_path):
    tree = hu_tree()
    run(tree, tmp_path, 1200, 43, tmp_path/'first')
    before = (tmp_path/'first/checkpoint.bin').read_bytes()
    result = run(tree, tmp_path, 1200, 99, tmp_path/'ci',
                 resume_from=tmp_path/'first/checkpoint.bin', track_ci=True)
    index = json.loads((tmp_path/'ci/index.json').read_text())
    assert index['samples'] == 1200 and index['ci'] is not None
    assert result['summary']['checkpoint_writes'] == 2
    assert (tmp_path/'first/checkpoint.bin').read_bytes() == before
    assert read_node(tmp_path/'ci', 0)['updates'] == 1200


@pytest.mark.parametrize('bad', [0, 1, 'true', None])
def test_shortcut_setting_rejects_non_boolean_before_output(tmp_path, bad):
    with pytest.raises(ValueError, match='constant_scalar_shortcuts'):
        run(folded_continuation(), tmp_path, 100, 43, tmp_path/'bad', constant_scalar_shortcuts=bad)
    assert not (tmp_path/'bad').exists()


def test_api_shortcuts_control_roundtrip_and_resume(app):
    from preflop_lab.hrc_custom import default_config
    from preflop_lab import server
    from preflop_lab.hrc_archive import export_archive
    cfg = default_config(3); cfg.update(iterations=1000, constant_scalar_shortcuts=False)
    code, created = app('/api/jobs', {'config': cfg})
    assert code == 202, created
    done = await_job(app, created['id'])
    assert done['status'] == 'completed', done
    assert not done['summary']['constant_scalar_shortcuts_requested']
    original = server.JOBS.get(created['id'])
    before = (original.solver.output/'checkpoint.bin').read_bytes()
    code, loaded = app('/api/import', raw=export_archive(original).read_bytes(),
                       headers={'Content-Type': 'application/octet-stream'})
    assert code == 201, loaded
    assert loaded['config']['constant_scalar_shortcuts'] is False
    code, resumed = app(f"/api/jobs/{loaded['id']}/resume",
                        {'iterations': 2000, 'constant_scalar_shortcuts': True})
    assert code == 202, resumed
    done = await_job(app, resumed['id'])
    assert done['status'] == 'completed', done
    assert done['summary']['constant_scalar_shortcuts_requested']
    assert (original.solver.output/'checkpoint.bin').read_bytes() == before
    assert app('/api/meta')[1]['training']['constant_scalar_shortcuts']['utility'] == 'chip_ev_only'
