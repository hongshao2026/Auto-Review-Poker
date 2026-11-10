"""Summarize the completed, sequential same-tree 20-worker comparison."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = ROOT/'reports/hrc-three40bb-matched20-analysis-20261108'


def read(path):
    return Path(path).read_text(encoding='utf-8')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    source = ROOT/'reports/hrc-three40bb-matched20-20261108.json'
    raw = json.loads(read(source))
    original, native = raw['original'], raw['native']
    assert original['status'] == native['status'] == 'ci_target_reached'
    assert original['runtime_workers'] == native['formal']['summary']['training_threads'] == 20
    assert original['ci'] < 10 and native['ci'] < 10
    assert all(native['preserved_unchanged'].values())
    plan = json.loads(read(raw['plan']))
    assert sha(plan['source_initial_archive']) == plan['source_sha256']
    assert sha(plan['original_final_archive']) == plan['original_final_archive_sha256']
    topo = json.loads(read(ROOT/plan['saved_topology_validation']))
    assert topo['comparison']['equivalent_on_compared_fields']
    assert topo['comparison']['paired']['nodes'] == 3964
    assert not topo['settings_differences']
    action_path = ROOT/'reports/hrc-three40bb-matched20-actions-20261108.json'
    actions = json.loads(read(action_path))
    assert actions['status'] == 'equivalent'
    assert actions['rebuilt_compact_exactly_equals_timed_input']
    assert actions['original_archive_sha256'] == plan['original_final_archive_sha256']
    phase = native['formal']
    own_ci = [json.loads(line) for line in (Path(phase['output'])/'ci-snapshots.jsonl').read_text().splitlines()]
    first_own = next(row for row in own_ci if row['value'] is not None and row['value'] < 10)
    rows = [dict(engine='HRC', workers=20, first_ci10_seconds=original['first_ci10_seconds'],
                 final_ci=original['ci'], new_samples=original['formal_samples'],
                 process_cpu_seconds=original['process_cpu_seconds'],
                 average_logical_cpus=original['average_logical_cpus'],
                 peak_working_set_bytes=original['peak_working_set_bytes'],
                 process_wall_seconds=original['wall_seconds'],
                 time_boundary='OK posted to first original mr record below 10',
                 memory_scope='Entire HRC desktop/JVM process'),
            dict(engine='Native', workers=20, first_ci10_seconds=first_own['timestamp_ms']/1000,
                 final_ci=native['ci'], new_samples=native['new_samples'],
                 process_cpu_seconds=phase['process_cpu_seconds'],
                 average_logical_cpus=phase['average_logical_cpus'],
                 peak_working_set_bytes=phase['peak_working_set_bytes'],
                 process_wall_seconds=phase['wall_seconds'],
                 training_end_seconds=native['training_seconds'],
                 time_boundary='Native training clock to first tracker record below 10',
                 memory_scope='Native kernel process; excludes Python/browser/server')]
    for row in rows:
        row['cpu_seconds_per_million'] = row['process_cpu_seconds']/(row['new_samples']/1e6)
        row['million_samples_per_process_wall_second'] = row['new_samples']/row['process_wall_seconds']/1e6
        row['peak_working_set_mib'] = row['peak_working_set_bytes']/(1 << 20)
    hrc, own = rows
    result = dict(schema='hrc-matched20-analysis-v1', raw_report=str(source), rows=rows,
                  conclusion='Observed time-to-CI is essentially tied; sub-second difference is not significant evidence of superiority.',
                  observed_time_difference_seconds=own['first_ci10_seconds']-hrc['first_ci10_seconds'],
                  observed_native_cpu_per_million_reduction_percent=100*(1-own['cpu_seconds_per_million']/hrc['cpu_seconds_per_million']),
                  observed_native_average_cpu_difference=own['average_logical_cpus']-hrc['average_logical_cpus'],
                  original_archive=dict(path=plan['original_final_archive'], sha256=plan['original_final_archive_sha256']),
                  native_checkpoint=dict(path=str(Path(phase['output'])/'checkpoint.bin'), sha256=sha(Path(phase['output'])/'checkpoint.bin')),
                  topology_report=str(ROOT/plan['saved_topology_validation']),
                  full_action_and_intermediate_state_report=str(action_path),
                  exact_abstraction_ids=plan['settings']['engine']['configuration']['abstractions'],
                  native_training_save_fraction=phase['training_checkpoint_fraction'],
                  topology_nodes_compared=3964,
                  initial_states='Each engine resumes its separately generated initialization; HRC float32 saved state vs native double checkpoint.',
                  limitations=raw['limits']+[
                    'One trajectory per engine. Timing boundaries differ; the 0.877-second gap does not establish a speed advantage.',
                    'Process CPU/workset include different runtime scopes. The memory comparison is not equal-scoped kernel memory.',
                    'CI10 is policy drift, not a proof of accuracy, exploitability or algorithm identity.',
                    'Previous short ETW and scheduler diagnoses are separate runs and are not a time decomposition of this formal run.'])
    strategy_path = ROOT/'reports/hrc-three40bb-matched20-strategy-20261108.json'
    policies = json.loads(read(strategy_path))
    assert policies['original']['sha256'] == result['original_archive']['sha256']
    assert policies['native_checkpoint']['sha256'] == result['native_checkpoint']['sha256']
    assert policies['preflop_nodes_compared'] == 214
    result['strategy_comparison'] = dict(report=str(strategy_path), preflop_nodes=214,
        postflop_policies_compared=False,
        selected=[dict(label=n['label'], slug=n['slug'], figure=n['figure'],
                       uniform_combo_hand_TV_pp=n['metrics']['combo_weighted_hand_TV_pp'],
                       aggregate_TV_pp=n['metrics']['aggregate_TV_pp']) for n in policies['selected']])
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8), gridspec_kw={'width_ratios': [1.7, 1, 1]})
    colors = ['#a56933', '#286a9c']
    curves = [[(r['elapsed_since_ok_seconds'], r['ci']) for r in original['ci_trajectory']],
              [(r['timestamp_ms']/1000, r['value']) for r in own_ci]]
    for row, points, color in zip(rows, curves, colors):
        points = [(x, y) for x, y in points if y is not None and y > 0]
        axes[0].plot(*zip(*points), label=row['engine'], color=color, linewidth=1.8)
    axes[0].axhline(10, color='#666666', linestyle='--', linewidth=1)
    axes[0].set(yscale='log', xlabel='Formal time (seconds)', ylabel='CI', title='CI trajectory')
    axes[0].legend(frameon=False)
    for ax, key, title, label in [(axes[1], 'cpu_seconds_per_million', 'CPU cost per million', 'Process CPU seconds / million'),
                                   (axes[2], 'average_logical_cpus', 'Average process CPU use', 'Logical CPUs (20 available)')]:
        bars = ax.bar([r['engine'] for r in rows], [r[key] for r in rows], color=colors, width=.6)
        ax.bar_label(bars, fmt='%.2f', padding=3)
        ax.set(title=title, ylabel=label, ylim=(0, max(r[key] for r in rows)*1.17))
    for ax in axes:
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(alpha=.17, axis='y')
        ax.set_axisbelow(True)
    fig.suptitle('3 人 40BB / 相同全树与抽象 / 双方 20 线程 / CI＜10', fontproperties=font, fontsize=15)
    fig.text(.02, .035, '首次达到目标：HRC 286.604 秒，自研 285.727 秒；本次基本同速。\n各一条独立轨迹；两版计时边界及进程范围有区别。CI 不是策略误差界。', fontproperties=font, fontsize=9, color='#555555')
    fig.tight_layout(rect=[0, .14, 1, .94], w_pad=1.5)
    fig.savefig(PREFIX.with_suffix('.png'), dpi=160, bbox_inches='tight')
    plt.close(fig)
    result['figure'] = str(PREFIX.with_suffix('.png'))
    PREFIX.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'rows': rows, 'analysis': str(PREFIX.with_suffix('.json')),
                      'native_cpu_per_million_reduction_percent': result['observed_native_cpu_per_million_reduction_percent']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
