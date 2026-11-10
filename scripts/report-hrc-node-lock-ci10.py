"""Summarize observed CI10 timings and strategy comparisons; no training/build."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def snapshots(path):
    return [json.loads(line) for line in (ROOT / path).read_text(encoding='utf-8').splitlines()]


def main():
    original = read('reports/hrc-three40bb-ci10-original-20261107.json')
    previous = read('reports/hrc-three40bb-ci10-independent-20261107.json')
    current = read('reports/hrc-three40bb-ci10-node-lock-20261108.json')
    benchmark = read('reports/hrc-throughput-round2-final-20261108.json')
    old_policy = read('reports/hrc-three40bb-ci10-strategy-comparison-20261107.json')
    new_policy = read('reports/hrc-three40bb-ci10-node-lock-strategy-20261108.json')
    if not (current['target_reached'] and current['ci'] < 10 and
            current['initial_unchanged'] and current['old_formal_unchanged'] and
            benchmark['serial_equal']):
        raise RuntimeError('CI10 completion and preserved-reference checks required')
    old_history = snapshots('.research-cache/three40bb-ci10-independent-20261107/formal/ci-snapshots.jsonl')
    new_history = snapshots('.research-cache/three40bb-ci10-node-lock-20261108/formal/ci-snapshots.jsonl')
    if not old_history[-1]['value'] < 10 or not new_history[-1]['value'] < 10:
        raise RuntimeError('Missing observed CI10 records')
    hrc = original['formal']
    rows = [{'engine': 'HRC original',
             'first_observed_ci10_seconds': hrc['ci_target_reached_elapsed_seconds'],
             'formal_window_seconds': hrc['last_observed_elapsed_seconds'],
             'formal_new_samples': hrc['last_ci_run_samples'],
             'process_cpu_seconds': hrc['process_cpu_seconds_delta'],
             'ci': hrc['last_ci']}]
    for name, phase, history in [('Our original', previous['phases']['formal'], old_history),
                                 ('Our optimized', current['formal'], new_history)]:
        summary = phase['summary']
        rows.append({'engine': name,
                     'first_observed_ci10_seconds': history[-1]['timestamp_ms'] / 1000,
                     'training_including_saves_seconds': summary['elapsed_seconds'],
                     'formal_window_seconds': phase['wall_seconds'],
                     'formal_new_samples': summary['iteration'] - 10_000_000,
                     'process_cpu_seconds': phase['process_cpu_seconds'],
                     'average_logical_cpus': phase['average_logical_cpus'],
                     'peak_working_set_bytes': phase['peak_working_set_bytes'],
                     'training_checkpoint_seconds': summary['training_checkpoint_seconds'],
                     'ci': summary['ci']['value']})
    for row in rows:
        row['formal_window_samples_per_second'] = row['formal_new_samples'] / row['formal_window_seconds']
        row['cpu_seconds_per_million_samples'] = row['process_cpu_seconds'] / (row['formal_new_samples'] / 1e6)
        row['first_ci10_time_relative_to_hrc'] = row['first_observed_ci10_seconds'] / rows[0]['first_observed_ci10_seconds']
    selected = []
    for new in new_policy['selected']:
        old = next(n for n in old_policy['selected'] if n['slug'] == new['slug'])
        selected.append({'slug': new['slug'], 'label': new['label'],
                         'hrc_frequency': new['metrics']['hrc_frequency'],
                         'current_frequency': new['metrics']['ours_frequency'],
                         'previous_hand_TV_pp': old['metrics']['combo_weighted_hand_TV_pp'],
                         'current_hand_TV_pp': new['metrics']['combo_weighted_hand_TV_pp'],
                         'previous_aggregate_TV_pp': old['metrics']['aggregate_TV_pp'],
                         'current_aggregate_TV_pp': new['metrics']['aggregate_TV_pp']})
    result = {'schema': 'node-lock-ci10-comparison-v1', 'timings': rows,
              'ci10_speedup_vs_original_native': rows[1]['first_observed_ci10_seconds'] / rows[2]['first_observed_ci10_seconds'],
              'fixed_sample_benchmark': benchmark['medians'],
              'preflop_nodes_compared': new_policy['preflop_nodes_compared'],
              'selected_strategy_metrics': selected,
              'limits': ['One formal trajectory per implementation; asynchronous interleavings differ.',
                         'Same native double initialization state; original HRC used its independently generated float32 saved state.',
                         'Formal windows exclude reused initialization. HRC includes GUI completion; native includes startup and final saves.',
                         'CI is recent strategy drift, not exploitability or a confidence interval.',
                         'Downstream per-hand TV uses uniform combo weights, not reach probabilities.',
                         'Historical HRC measurement was not repeated during this optimization round.']}
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5), layout='constrained')
    trajectories = [
        ('HRC original', '#166534', [(r['elapsed_since_ok_seconds'] / 60, r['ci']) for r in original['ci_trajectory']]),
        ('Our original', '#b45309', [(r['timestamp_ms'] / 60000, r['value']) for r in old_history]),
        ('Our optimized', '#1d4ed8', [(r['timestamp_ms'] / 60000, r['value']) for r in new_history])]
    for label, color, points in trajectories:
        ax.plot(*zip(*points), label=label, color=color, linewidth=1.8, marker='.', markersize=3)
    ax.axhline(10, linestyle='--', color='#6b7280', linewidth=1, label='CI target = 10')
    ax.set_yscale('log'); ax.set_xlabel('Formal run elapsed time (minutes)')
    ax.set_ylabel('CI (recent policy drift)'); ax.set_title('3 players / 40BB / full tree / 8 workers')
    ax.grid(True, which='both', alpha=.18); ax.legend(frameon=False)
    fig.text(.5, -.015, 'One observed run per engine. CI is not an exploitability bound. Initialization excluded.',
             ha='center', fontsize=8)
    output = ROOT / 'reports/hrc-node-lock-ci10-comparison-20261108'
    figure = output.with_suffix('.png'); fig.savefig(figure, dpi=170, bbox_inches='tight'); plt.close(fig)
    result['figure'] = str(figure)
    output.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'timings': rows, 'selected_strategy_metrics': selected,
                      'report': str(output.with_suffix('.json'))}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
