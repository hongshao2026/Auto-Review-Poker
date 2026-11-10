"""Formal sampling targets, run-only CI and immutable-source continuation."""
import copy
import json

import pytest

from preflop_lab.hrc_sampling import iteration_limit, sampling_selection, validated_sampling
from preflop_lab.hrc_training import validated_training
from preflop_lab.hrc_native import run
from preflop_lab.hrc_benchmarks import config_for
from preflop_lab.hrc_custom import default_config as custom_config, validated_config as validate_custom
from test_hrc_kernel import hu_tree
from test_server import app, await_job


def test_ci_mode_owns_default_target_and_tracker():
    options = validated_training({'stopping_mode': 'ci'})
    assert options['track_ci'] is True and options['target_ci'] == 10.
    assert iteration_limit({'stopping_mode': 'ci'}) == 1_000_000_000
    assert iteration_limit({'stopping_mode': 'ci', 'iterations': 2000}) == 2000
    cfg = custom_config(2); cfg.pop('iterations'); cfg['stopping_mode'] = 'ci'
    checked = validate_custom(cfg)
    assert checked['iterations'] == 1_000_000_000 and checked['track_ci']


def test_large_ci_memory_budget_does_not_change_default_or_allocate_the_limit(tmp_path):
    assert validated_training({'max_memory_bytes': 8 << 30})['max_memory_bytes'] == 8 << 30
    with pytest.raises(ValueError, match='8GiB'):
        validated_training({'max_memory_bytes': (8 << 30) + 1})
    result = run(hu_tree(), tmp_path, 500, 43, tmp_path/'large-budget', max_memory_bytes=6 << 30)
    assert result['summary']['max_memory_bytes'] == 6 << 30
    assert result['summary']['estimated_memory_bytes'] < 1 << 30


@pytest.mark.parametrize('raw', [
    {'stopping_mode': 'unknown'}, {'stopping_mode': None},
    {'stopping_mode': 'ci', 'target_ci': 0}, {'stopping_mode': 'ci', 'target_ci': None},
    {'stopping_mode': 'ci', 'target_ci': True}, {'stopping_mode': 'ci', 'stop_after_seconds': 1},
    {'stopping_mode': 'samples', 'target_ci': 10}, {'stopping_mode': 'samples', 'stop_after_seconds': 1},
    {'stopping_mode': 'time'}, {'stopping_mode': 'time', 'stop_after_seconds': 1, 'target_ci': 10},
    {'sampling_scope': 'all'}, {'sampling_scope': 'entire_tree', 'sampling_path': [0]},
    {'sampling_scope': 'selected_subtree', 'sampling_path': [True]},
    {'sampling_scope': 'selected_subtree', 'sampling_path': [16]},
    {'sampling_stage': 'initialization', 'stopping_mode': 'ci'},
])
def test_incompatible_or_invalid_run_controls_fail(raw):
    with pytest.raises(ValueError):
        validated_training(raw)


def test_scope_selection_means_a_decision_and_rejects_terminal_and_postflop():
    tree = hu_tree()
    assert sampling_selection(tree, 'selected_subtree', [1])['root_node_id'] == 2
    for path in ([0], [2], [1, 0, 0]):
        with pytest.raises(ValueError): sampling_selection(tree, 'selected_subtree', path)
    tree['nodes'][2]['street'] = 1
    with pytest.raises(ValueError, match='翻前'):
        sampling_selection(tree, 'selected_subtree', [1])


def test_runtime_ci_can_be_enabled_without_migrating_existing_checkpoint(tmp_path):
    tree = hu_tree()
    first = tmp_path/'first'; resumed = tmp_path/'resumed'
    run(tree, tmp_path, 500, 43, first)
    source = (first/'checkpoint.bin').read_bytes()
    changed = copy.deepcopy(tree); changed['ci'] = {'enabled': True}
    result = run(changed, tmp_path, 1000, 43, resumed, resume_from=first/'checkpoint.bin',
                 track_ci=True, stopping_mode='ci', target_ci=10.)
    assert (resumed/'checkpoint.bin').read_bytes()[8:16] == source[8:16]
    assert 'ci' not in json.loads((resumed/'tree.json').read_text())
    assert result['summary']['ci'] is not None
    assert result['summary']['stop_reason'] == 'sample_cap'
    assert result['summary']['target_reached'] is False
    assert (first/'checkpoint.bin').read_bytes() == source


def test_formal_sampling_algorithm_can_change_without_mutating_source(tmp_path):
    tree = hu_tree(); first = tmp_path/'first'
    run(tree, tmp_path, 500, 43, first, mode='v4')
    before = (first/'checkpoint.bin').read_bytes()
    result = run(tree, tmp_path, 1000, 43, tmp_path/'v3', resume_from=first/'checkpoint.bin',
                 mode='v3', allow_algorithm_change=True)
    assert result['summary']['algorithm_change']['from'] == 'v4'
    assert result['summary']['algorithm_change']['to'] == 'v3'
    assert (first/'checkpoint.bin').read_bytes() == before


def test_subtree_root_mean_is_not_reenabled_by_full_tree_resume(tmp_path):
    tree = hu_tree(); first = tmp_path/'first'; subtree = tmp_path/'subtree'; whole = tmp_path/'whole'
    run(tree, tmp_path, 500, 43, first)
    scoped = run(tree, tmp_path, 1000, 43, subtree, resume_from=first/'checkpoint.bin',
                 sampling_scope='selected_subtree', sampling_path=[1])
    assert scoped['summary']['root_mean_valid'] is False
    continued = run(tree, tmp_path, 1500, 43, whole, resume_from=subtree/'checkpoint.bin',
                    mode='v3', allow_algorithm_change=True, root_mean_valid=True)
    index = json.loads((whole/'index.json').read_text())
    assert continued['summary']['root_mean_valid'] is False
    assert index['root_mean_valid'] is False and index['root_mean_net_bb'] is None


def test_formal_reset_regret_also_resets_strategy_accumulators(tmp_path):
    from test_hrc_native_features import raw_node
    tree = hu_tree(); first = tmp_path/'first'; reset = tmp_path/'reset'
    run(tree, tmp_path, 500, 43, first)
    before = raw_node(first)
    result = run(tree, tmp_path, 500, 43, reset, resume_from=first/'checkpoint.bin',
                 stopping_mode='samples', reset_regret=True, reset_average=False)
    assert result['summary']['reset_average'] is True
    assert raw_node(reset)[1:] == pytest.approx([v*1e-20 for v in before[1:]], abs=1e-26)


def test_api_initialization_then_formal_ci_run_and_archive(app):
    from preflop_lab import server
    from preflop_lab.hrc_archive import export_archive
    cfg = config_for('hu10bb', iterations=500)
    cfg.update(stopping_mode='samples', sampling_stage='initialization', track_ci=False)
    code, initial = app('/api/jobs', {'config': cfg})
    assert code == 202, initial
    result = await_job(app, initial['id'])
    assert result['summary']['sampling_stage'] == 'initialization'
    source = server.JOBS.get(initial['id'])
    before = (source.solver.output/'checkpoint.bin').read_bytes()
    code, formal = app(f"/api/jobs/{initial['id']}/resume", {
        'stopping_mode': 'ci', 'target_ci': 10., 'hard_seconds': .1,
        'sampling_scope': 'entire_tree', 'threads': 2})
    assert code == 202, formal
    result = await_job(app, formal['id'])
    assert result['status'] == 'completed', result
    assert result['config']['iterations'] == 1_000_000_000
    assert result['summary']['sampling_stage'] == 'calculation'
    assert result['summary']['stopping_mode'] == 'ci'
    assert not result['summary']['target_reached']
    continued = server.JOBS.get(formal['id'])
    code, imported = app('/api/import', raw=export_archive(continued).read_bytes(),
                         headers={'Content-Type': 'application/octet-stream'})
    assert code == 201, imported
    assert imported['config']['target_ci'] == 10.
    code, fixed = app(f"/api/jobs/{imported['id']}/resume", {
        'stopping_mode': 'samples', 'iterations': result['summary']['iterations_completed']+500,
        'solver_mode': 'v3', 'sampling_scope': 'entire_tree'})
    assert code == 202, fixed
    fixed_result = await_job(app, fixed['id'])
    assert fixed_result['status'] == 'completed', fixed_result
    assert 'target_ci' not in fixed_result['config']
    assert (source.solver.output/'checkpoint.bin').read_bytes() == before


def test_new_subtree_job_requires_initialized_hand(app):
    cfg = config_for('hu10bb', iterations=500)
    cfg.update(sampling_scope='selected_subtree', sampling_path=[1])
    code, error = app('/api/jobs', {'config': cfg})
    assert code == 400 and '初始化' in error['error']
    assert app('/api/jobs')[1]['jobs'] == []
