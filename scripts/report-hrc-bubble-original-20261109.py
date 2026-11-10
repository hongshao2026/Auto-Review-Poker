"""Summarize the observed original HRC EP CI10 run; never starts training."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_tree import parse_gametree
from preflop_lab.hrc_hrcz_tree import _record_order

CASE = ROOT / 'analysis/hrc-desktop/bubble-ci10-original-20261109'
SOURCE = Path('C:/Users/Shao/HoldemResources/SavedHands/Hand bubble.hrcz')
JOBS = ('2a1837784df843b5ac81031b7e0a89d0', 'a649bb63d04344a2b591382aa29dec70')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def archive_input(path):
    with zipfile.ZipFile(path) as archive:
        settings = archive.read('settings.json')
        tree = archive.read('gametree.dat')
    nodes, root = parse_gametree(tree)
    return settings, nodes, root, hashlib.sha256(tree).hexdigest(), _record_order(tree)


def saved_node_changes(before, after, selected):
    """Compare saved bytes for validation only; do not decode or train policies."""
    with zipfile.ZipFile(before) as archive:
        before_index, before_data = archive.read('idx.dat'), archive.read('nodedata.dat')
    with zipfile.ZipFile(after) as archive:
        after_index, after_data = archive.read('idx.dat'), archive.read('nodedata.dat')
    assert len(before_index) == len(after_index) and len(before_index) % 24 == 0
    changed, outside = [], []
    for node_id in range(len(before_index) // 24):
        _, _, left, left_len = struct.unpack_from('<qiqi', before_index, node_id * 24)
        _, _, right, right_len = struct.unpack_from('<qiqi', after_index, node_id * 24)
        if before_data[left:left + left_len] != after_data[right:right + right_len]:
            changed.append(node_id)
            if node_id not in selected:
                outside.append(node_id)
    assert 1 in changed, 'Selected EP strategy did not change'
    return {'outside_nodes_checked': len(before_index) // 24 - len(selected),
            'changed_inside_subtree_nodes': len(changed) - len(outside),
            'changed_outside_node_ids': outside,
            'all_outside_saved_node_records_byte_identical': not outside,
            'strategy_payload_use': 'comparison only after original timing; never used as own solver training input'}


def main():
    evidence = json.loads((CASE / 'formal/observation-result.json').read_text(encoding='utf8'))
    assert evidence['ci_target_reached'] and not evidence['cancel_sent']
    assert evidence['reason'] == 'observed_idle_with_ci_below_target'
    assert evidence['pid'] == 48432
    events = [json.loads(line) for line in (CASE / 'formal/agent-events.jsonl').read_text().splitlines()]
    installed = [row for row in events if row['event'] == 'installed']
    assert len(installed) == 1 and installed[0]['original_worker_count'] == 20
    assert installed[0]['epoch_millis'] < evidence['start_epoch_millis']
    assert any(row['event'] == 'removed_and_original_class_restored' and row['remove_returned_true'] for row in events)
    ci = evidence['ci_records']
    first_target = next(row for row in ci if row['ci'] is not None and row['ci'] < 10)
    rows = [json.loads(line) for line in (CASE / 'formal/win32-observations.jsonl').read_text().splitlines()]
    polls = [row for row in rows if 'rows' in row and 'event' not in row]
    active = [row for row in polls if any('MC-CFR' in x['text'] or ': Monte Carlo Sampling' in x['text'] for x in row['rows'])]
    last_active = active[-1]
    first_idle = next(row for row in polls if row['elapsed_seconds'] > last_active['elapsed_seconds'])
    assert not any('MC-CFR' in x['text'] or ': Monte Carlo Sampling' in x['text'] for x in first_idle['rows'])
    original = {
        'source': 'HRC Pro original desktop, CFR HRC 4.0 (Default)',
        'training_threads': installed[0]['original_worker_count'],
        'start_utc': evidence['start_utc'],
        'ci_target': 10,
        'scope': 'Selected Subtree: UTG folds, then EP decision (all EP actions)',
        'source_archive_used_as_warm_start': False,
        'fresh_rebuild_then_automatic_initialization_samples': 10000000,
        'initialization_included_in_formal_timer': False,
        'first_target_record_ci': first_target['ci'],
        'first_target_record_samples_in_formal_run': first_target['original_samples'],
        'first_target_record_elapsed_seconds': (first_target['original_epoch_millis'] - evidence['start_epoch_millis']) / 1000,
        'last_active_poll_seconds': last_active['elapsed_seconds'],
        'first_idle_poll_seconds': first_idle['elapsed_seconds'],
        'observer_finished_seconds': evidence['observer_elapsed_seconds'],
        'completion_detection_resolution_seconds': first_idle['elapsed_seconds'] - last_active['elapsed_seconds'],
        'native_solver_elapsed_seconds': None,
        'formal_successful_cycles_per_second_to_ci_record': first_target['original_samples'] / ((first_target['original_epoch_millis'] - evidence['start_epoch_millis']) / 1000),
        'process_cpu_seconds_delta_to_observer_finish': evidence['process_cpu_seconds_delta'],
        'mean_logical_cpus_to_observer_finish': evidence['process_cpu_seconds_delta'] / evidence['observer_elapsed_seconds'],
        'max_observed_working_set_bytes': max(row['process_memory']['WorkingSetSize'] for row in polls),
        'reason': evidence['reason'],
        'ci_records': ci,
        'timing_method': 'monotonic wall timer before posting OK, read-only original CI constructor arguments, 1 Hz scoped Win32 idle polling',
    }
    jobs = []
    for ident in JOBS:
        target = CASE / f'own-job-{ident}.json'
        if target.exists():
            job = json.loads(target.read_text(encoding='utf8'))
        else:
            with urllib.request.urlopen(f'http://127.0.0.1:8772/api/jobs/{ident}', timeout=15) as response:
                job = json.load(response)
            target.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf8')
        assert job['id'] == ident and job['summary']['training_threads'] == 20
        assert job['summary']['sampling_path'] == [0] and job['summary']['sampling_root_node_id'] == 1
        assert job['summary']['ci']['selected_nodes'] == 2278
        jobs.append(job)
    assert jobs[-1]['status'] == 'completed' and jobs[-1]['summary']['ci']['value'] < 10
    training = sum(job['summary']['elapsed_seconds'] for job in jobs)
    wall = sum(job['elapsed_seconds'] for job in jobs)
    io = sum(job['summary']['training_checkpoint_seconds'] for job in jobs)
    setup = sum(job['summary']['terminal_table_setup_seconds'] for job in jobs)
    cycles = sum(job['summary']['scope_effective_samples'] for job in jobs)
    own = {
        'jobs': list(JOBS), 'training_threads': 20,
        'independent_initialization_samples_excluded': 10000000,
        'formal_successful_cycles': cycles,
        'final_cumulative_samples': jobs[-1]['summary']['iteration'],
        'final_ci': jobs[-1]['summary']['ci']['value'],
        'formal_application_wall_seconds_sum': wall,
        'formal_native_training_seconds_sum': training,
        'training_checkpoint_seconds': io,
        'terminal_table_setup_seconds': setup,
        'formal_training_cycles_per_second_including_checkpoints': cycles / training,
        'kernel_identity': '033dc7741886ae9e70743c99ae3b17d9666db17410f98e3da00c6f04c4b40808',
        'latest_small_optimization_included': False,
        'two_invocations_pause_excluded': True,
        'checkpoint_io_fraction_of_native_training': io / training,
        'ideal_speedup_if_checkpoint_io_eliminated': training / (training - io),
        'ideal_speedup_if_observed_setup_and_training_checkpoint_time_eliminated': wall / (training - io),
        'table_bytes': jobs[-1]['summary']['terminal_table_bytes'],
        'runtime_terminal_settlements': sum(job['summary']['terminal_settlements'] for job in jobs),
    }
    inputs = [archive_input(path) for path in (SOURCE, CASE / 'initialization20.hrcz', CASE / 'final-ci10-20threads.hrcz')]
    assert all(item[0] == inputs[0][0] for item in inputs)
    assert all(item[1:3] == inputs[0][1:3] for item in inputs)
    settings, nodes, root, _, _ = inputs[0]
    selected, pending = set(), [nodes[root].children[0]]
    while pending:
        ident = pending.pop()
        assert ident not in selected
        selected.add(ident)
        pending.extend(nodes[ident].children)
    assert nodes[1].actor == 1 and len(nodes[1].children) == 3
    assert len(selected) == 82610
    saved_changes = saved_node_changes(CASE / 'initialization20.hrcz', CASE / 'final-ci10-20threads.hrcz', selected)
    assert saved_changes['all_outside_saved_node_records_byte_identical']
    pinned = '0657418a1d2f237e585d04c29dfd507ebff4f7d04755ad916989b023e71ea376'
    source_sha = sha(SOURCE)
    assert source_sha == pinned, 'User source archive changed'
    report = {
        'schema': 'bubble-original-ci10-20-worker-20261109-v1',
        'original': original,
        'own_previous_complete_solve': own,
        'original_subtree_saved_node_audit': saved_changes,
        'configuration_audit': {
            'settings_bytes_equal_source_initial_final': True,
            'parsed_all_nodes_equal_source_initial_final': True,
            'total_nodes': len(nodes),
            'decision_nodes': sum(bool(node.children) for node in nodes),
            'selected_subtree_nodes': len(selected),
            'selected_preflop_decisions': sum(bool(nodes[i].children) and nodes[i].street == 0 for i in selected),
            'gametree_binary_sha256_source_initial_final': [item[3] for item in inputs],
            'physical_record_order_equal_source_initial': inputs[0][4] == inputs[1][4],
            'physical_record_order_equal_initial_final': inputs[1][4] == inputs[2][4],
            'binary_tree_hash_note': 'Physical serialization order differs; every parsed ID, parent, child order, action, actor, street and terminal kind is equal.',
            'source_archive_sha256_unchanged': source_sha,
            'initialization_archive_sha256': sha(CASE / 'initialization20.hrcz'),
            'final_archive_sha256': sha(CASE / 'final-ci10-20threads.hrcz'),
        },
        'observed_comparison': {
            'own_application_wall_divided_by_original_first_idle_wall': wall / first_idle['elapsed_seconds'],
            'own_formal_cycles_divided_by_original_cycles_to_target_record': cycles / first_target['original_samples'],
            'single_run_not_a_controlled_kernel_speed_ratio': True,
        },
        'limitations': [
            'Both sides initialize independently for 10m full-tree cycles; frozen UTG prefix policies and RNG trajectories are not byte-identical.',
            'Own result comprises two invocations with a restarted CI history; original is one uninterrupted invocation.',
            'Original automatic initialization time was not measured; all listed main comparison times exclude initialization.',
            'Own latest accepted 3.7% fixed-work optimization was not run to CI10 again; no estimated runtime is labelled measured.',
            'The original read-only CI observation hook was installed before timing; its small remaining observation overhead has not been separately measured.',
            'HRC uses about 6 GiB working set in this run; our native memory budget was 8 GiB and observed usage about 1.6 GiB. Equal worker count does not imply identical internal allocation.',
            'Only this same-tree MTT EP workload was timed; results do not establish a CPU or memory-bandwidth ceiling or exclude future 2x architectural/algorithmic gains.',
            'CI is a policy drift/convergence diagnostic, not an exploitability certificate or a proof that equal thresholds have identical strategy error.',
        ],
    }
    target = ROOT / 'reports/hrc-bubble-original-ci10-20threads-20261109.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps({k: v for k, v in original.items() if k != 'ci_records'}, ensure_ascii=False))
    print(json.dumps({'own': own, 'comparison': report['observed_comparison'], 'report': str(target)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
