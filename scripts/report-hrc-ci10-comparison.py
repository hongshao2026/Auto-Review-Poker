"""Consolidate retained CI benchmark observations; never estimate a finish time."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/hrc-nine40bb-ci10-comparison-20261106.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def consolidate():
    independent = read(ROOT / 'reports/hrc-nine40bb-ci10-independent-20261106.json')
    original = read(ROOT / 'reports/hrc-nine40bb-ci10-original-20261106.json')
    phase = independent['phases']['formal']
    summary = phase['summary']
    elapsed = summary['elapsed_seconds']
    saved = summary['training_checkpoint_seconds']
    samples = summary['scope_effective_samples']
    own_ci = [{'wall_seconds': row['observed_wall_seconds'],
               'new_samples': row['samples'] - independent['initialization_samples'],
               'ci': row['value']} for row in lines(Path(phase['output']) / 'ci-snapshots.jsonl')]
    original_ci = [{'wall_seconds': row['elapsed_since_ok_seconds'],
                    'new_samples': row['original_samples'], 'ci': row['ci']}
                   for row in original['ci_trajectory'] if row.get('ci') is not None]
    report = {
        'schema': 'hrc-nine40bb-ci10-comparison-v1',
        'updated_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'no_verified_ci10_completion',
        'settings': {'players': 9, 'stack_bb': 40, 'utility': 'chip_ev',
                     'threads': 8, 'total_nodes': 494055, 'decision_nodes': 233802,
                     'target_ci': 10, 'scope': 'full_tree'},
        'hardware': original['hardware'],
        'independent': {'status': independent['status'], 'ci10_elapsed_seconds': None,
            'initialization_samples': independent['initialization_samples'],
            'initialization_wall_seconds': independent['phases']['initialization']['wall_seconds'],
            'formal_wall_seconds': phase['wall_seconds'], 'formal_training_seconds': elapsed,
            'new_samples': samples, 'last_ci': summary['ci']['value'],
            'training_checkpoint_seconds': saved, 'training_checkpoint_fraction': saved / elapsed,
            'effective_samples_per_second': samples / elapsed,
            'samples_per_non_checkpoint_second': samples / (elapsed - saved),
            'peak_working_set_bytes': phase['peak_working_set_bytes'],
            'ci_trajectory': own_ci,
            'report': 'reports/hrc-nine40bb-ci10-independent-20261106.json'},
        'original': {'status': original['status'],
            'timing': {k: v for k, v in original['timing'].items() if k != 'observer_result'},
            'memory': original['memory'],
            'cleanup': original.get('observation', {}).get('cleanup'),
            'user_document_preservation': original.get('user_document_preservation'),
            'latest_visible_progress': original.get('latest_visible_progress'),
            'ci_trajectory': original_ci,
            'report': 'reports/hrc-nine40bb-ci10-original-20261106.json'},
        'optimization_findings': [{
            'finding': 'Complete checkpoint writes dominate independent training wall time',
            'checkpoint_count': summary['checkpoint_writes'],
            'binary_checkpoint_bytes': 2433800364,
            'ideal_upper_bound_speedup_if_all_training_save_cost_removed': elapsed / (elapsed - saved),
            'measured_optimized_speedup': None,
            'candidate': 'Schedule periodic saves by elapsed time or save cost; retain safe stop and final saves.',
        }],
        'limits': [
            'Neither run has verified CI below ten; no completed-to-CI10 time is reported.',
            'Independent run was intentionally interrupted after its diagnostic trace.',
            'The original visible ETA is an early heuristic, not a measured completion time.',
            'Identical settings, node counts and abstraction resource IDs have been checked.',
            'Full path-by-path topology audit is a separate report.',
            'Different RNG, asynchronous schedules and independently trained initial strategies.',
            'Original initial state was generated with Automatic workers and reloaded as float32.',
            'Independent initialization used eight workers and CI tracking disabled.',
            'Independent wall starts at process launch; original wall starts at GUI OK.',
            'Native non-checkpoint time still includes CI and scheduling; it is not pure CFR time.',
            'Native CI throttling currently times snapshot construction; original times the whole CI measurement.',
        ],
    }
    topology_path = ROOT / 'reports/hrc-nine40bb-topology-equivalence-20261106.json'
    if topology_path.exists():
        report['topology_audit'] = read(topology_path)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def plot(report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams['axes.unicode_minus'] = False
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    for key, label, color in [('independent', '我们的内核（诊断轮已停止）', '#2474a8'),
                              ('original', 'HRC 原版', '#c65a16')]:
        rows = report[key]['ci_trajectory']
        if not rows:
            continue
        for ax, field, scale in [(axes[0], 'wall_seconds', 60), (axes[1], 'new_samples', 1e6)]:
            ax.plot([r[field] / scale for r in rows], [r['ci'] for r in rows],
                    color=color, label=label, linewidth=1.7, marker='.', markersize=3)
    for ax in axes:
        ax.set_yscale('log')
        ax.axhline(10, color='#555555', linestyle='--', linewidth=1, label='CI Target 10')
        ax.set_ylim(bottom=8)
        ax.grid(axis='y', alpha=.2)
        ax.set_ylabel('CI（对数轴）', fontproperties=font)
        ax.legend(prop=font, frameon=False, fontsize=9)
    axes[0].set_xlabel('从正式运行入口起的墙钟时间（分钟）', fontproperties=font)
    axes[1].set_xscale('log')
    axes[1].set_xlabel('本次新增采样（百万次，对数轴）', fontproperties=font)
    fig.suptitle('9 人 40BB · 8 线程 · 全树：实际 CI 轨迹（均未达到 10）', fontproperties=font)
    output = ROOT / 'reports/hrc-nine40bb-ci10-trajectories-20261106.png'
    fig.savefig(output, dpi=160, bbox_inches='tight')
    plt.close(fig)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()
    result = consolidate()
    print(json.dumps({'report': str(REPORT), 'status': result['status']}))
    if args.plot:
        print(plot(result))
