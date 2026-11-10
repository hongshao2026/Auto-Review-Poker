"""Rebuild the bounded original-GUI observation report; reads evidence only.

This does not start HRC, execute original classes, or run any sampling. It uses
the two independently named local archives and append-only desktop action log.
"""
from __future__ import annotations
import hashlib
import json
import struct
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'analysis/hrc-desktop'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def archive(path):
    with zipfile.ZipFile(path) as zipped:
        with zipped.open('idx.dat') as stream:
            tree_offset, tree_size, data_offset, data_size = struct.unpack('<qiqi', stream.read(24))
        info = zipped.getinfo('nodedata.dat')
        assert info.compress_type == 0, 'This bounded reader expects the observed stored ZIP entry'
        with path.open('rb') as stream:
            stream.seek(info.header_offset + 26)
            filename_length, extra_length = struct.unpack('<HH', stream.read(4))
            stream.seek(info.header_offset + 30 + filename_length + extra_length + data_offset)
            header = struct.unpack('<6iQ', stream.read(32))
            payload = stream.read(header[1])
        assert header[0] == 0 and header[3:6] == (23, 169, 0)
        tree = zipped.read('gametree.dat')
        root = struct.unpack_from('<iiBbh', tree, tree_offset)
        assert root[0:2] == (0, -1), 'Index entry 0 must be the root'
        node_count, = struct.unpack_from('<i', tree)
        position = 4
        decisions = 0
        for _ in range(node_count):
            _, _, kind, actions, children = struct.unpack_from('<iiBbh', tree, position)
            assert kind in (1, 2) and actions >= 0 and children >= 0
            decisions += kind == 1
            position += 12 + (2 if kind == 1 else 0) + 8 * actions + 4 * children
        assert position == len(tree)
        return {
            'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
            'sha256': sha(path), 'root_counter_float32': struct.unpack_from('<f', payload)[0],
            'root_payload_sha256': hashlib.sha256(payload).hexdigest(),
            'tree_sha256': hashlib.sha256(tree).hexdigest(),
            'total_nodes': node_count, 'decision_nodes': decisions,
            'terminal_nodes': node_count - decisions,
            'settings': json.loads(zipped.read('settings.json')),
            'state': json.loads(zipped.read('state.json')),
        }


def main():
    actions = [json.loads(line) for line in (DESKTOP/'actions.jsonl').read_text(encoding='utf8').splitlines()]
    start = json.loads((DESKTOP/'ci40-formal-start.json').read_text(encoding='utf8'))
    started = datetime.fromisoformat(start['utc'])
    # These are retained observations, not estimates of the solver's stop time.
    active = next((i, r) for i, r in enumerate(actions, 1)
                  if r['utc'] > start['utc'] and r['request']['action'] == 'windows'
                  and any('Monte Carlo Sampling' in w['title'] for w in r['result']))
    idle = next((i, r) for i, r in enumerate(actions, 1)
                if r['request'].get('label') == 'ci40-formal-poll-60' and r['request']['action'] == 'inspect')
    assert any('No operations to display' in x['title'] for x in idle[1]['result']['controls'])
    before = archive(DESKTOP/'nine40bb-large-ci-initial-20261106.hrcz')
    after = archive(DESKTOP/'nine40bb-large-ci-formal-first-20261106.hrcz')
    assert before['tree_sha256'] == after['tree_sha256'] and before['settings'] == after['settings']
    expected = json.loads((ROOT/'.research-cache/deep-tree-optimization-20261106/large-settings.json').read_text(encoding='utf8'))
    matched = {key: expected[key] == before['settings'][key] for key in ('handdata', 'eqmodel', 'treeconfig')}
    screens = ['ci40-preflop-configured', 'ci40-postflop-observed', 'ci40-worker-settings-confirmed',
               'ci40-formal-run-controls', 'ci40-formal-poll-60', 'ci40-final-saved',
               '36-20bb-add50m', '46-eight15bb-add50m', '64-pko-run']
    artifacts = [{'path': str((DESKTOP/'screens'/f'{name}.png').relative_to(ROOT)),
                  'sha256': sha(DESKTOP/'screens'/f'{name}.png')} for name in screens]
    report = {
        'schema': 'hrc-original-bounded-ci-observation-v1',
        'target_jar_sha256': '25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43',
        'date': '2026-11-06', 'original_pid': 38284,
        'formal_run': {'algorithm': 'HRC 4.0 (Default)', 'scope': 'Full Tree',
            'stop_mode': 'Until CI value is reached', 'target_ci': 10.0,
            'reset_regret': False, 'reset_strategies': False,
            'planned_wall_bound_seconds': 180,
            'start_utc': start['utc'], 'start_action_line': 408,
            'last_sampling_window_utc': active[1]['utc'], 'last_sampling_window_action_line': active[0],
            'last_sampling_window_elapsed_seconds': (datetime.fromisoformat(active[1]['utc'])-started).total_seconds(),
            'first_persisted_idle_utc': idle[1]['utc'], 'first_persisted_idle_action_line': idle[0],
            'first_persisted_idle_elapsed_seconds': (datetime.fromisoformat(idle[1]['utc'])-started).total_seconds(),
            'cancel_sent_by_agent': False, 'error_dialog_observed': False,
            'initial_ci': None, 'last_ci': None, 'ci_target_reached_verified': False,
            'ci10_duration_seconds': None, 'displayed_samples_per_second': None,
            'reason_numeric_ci_missing': 'Blocking Win32 inspection missed the transient progress text; neither numeric CI nor a success status was retained. Window disappearance is not proof of target achievement.',
            'root_counter_delta_float32': after['root_counter_float32']-before['root_counter_float32'],
            'counter_caveat': 'Root saved counter is float32 and may reflect batching/rounding; the difference is not an exact integer run-loop sample count.'},
        'hardware': {'cpu': '13th Gen Intel(R) Core(TM) i5-13600KF', 'physical_cores': 14, 'logical_processors': 20},
        'threads': {'ui_worker_threads': 0, 'ui_label': 'Automatic', 'source_resolution': 'Runtime.availableProcessors()',
                    'expected_workers': 20, 'actual_worker_creation_count_instrumented': False},
        'memory': {'tree_size_display': '2.0 GB', 'before_run_process': start['memory'],
                   'caveat': 'Whole HRC process including the untouched user Hand1 and test Hand2; not incremental tree or isolated peak training memory.'},
        'initialization': {'configured_samples': 10000000, 'actual_saved_root_counter_float32': before['root_counter_float32'],
            '10000L_argument': 'UI listener refresh interval in milliseconds, not a time budget',
            'fixed_count_predicate': 'count > target', 'initialization_wall_seconds': None},
        'expected_settings_matched': matched,
        'initial_archive': before, 'formal_run_archive': after,
        'old_formal_run_evidence': [
            {'scenario': 'nine20bb', 'menu_line':133, 'samples_edit_line':136, 'controls_screenshot_line':137, 'ok_line':138, 'save_lines':[140,141,142]},
            {'scenario': 'eight15bb', 'menu_line':173, 'controls_screenshot_line':175, 'ok_line':176, 'save_lines':[182,183]},
            {'scenario': 'eight15bb-pko', 'menu_line':243, 'controls_screenshot_line':245, 'ok_line':247, 'save_lines':[253,254]}
        ],
        'artifacts': artifacts,
        'limitations': ['Single original GUI observation, no controlled repeated timing.',
            'Formal run started from the live initialized state without reload/reset; saved initial archive is retained for audit.',
            'No sampled CI trajectory was captured and no CI10 achievement time is established.',
            'Not a controlled throughput comparison against the independent engine; automatic original worker setting differs from smaller fixed worker counts.',
            'Original Selected Subtree semantics were traced statically and in existing probes; this session only timed Full Tree.']
    }
    output = ROOT/'reports/hrc-original-40bb-ci-timing.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(output)
    print(json.dumps({'root_before':before['root_counter_float32'], 'root_after':after['root_counter_float32'],
                      'last_active': report['formal_run']['last_sampling_window_elapsed_seconds'],
                      'first_idle': report['formal_run']['first_persisted_idle_elapsed_seconds'], 'matched':matched}))


if __name__ == '__main__':
    main()
