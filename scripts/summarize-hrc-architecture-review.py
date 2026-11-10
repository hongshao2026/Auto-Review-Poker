"""Read frozen local reports only; never starts solvers or changes production."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def main():
    sources = {}
    formal = {}
    for case in ('current8', 'current20'):
        path = f'reports/hrc-three40bb-ci10-round3-{case}-20261108.json'
        report = read(path)
        sources[path] = hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        f, n = report['formal'], report['formal_new_samples']
        s = f['summary']
        formal[case] = {
            'samples': n, 'executable_sha256': report['executable_sha256'],
            'training_seconds': s['elapsed_seconds'],
            'process_wall_seconds': f['wall_seconds'],
            'process_cpu_seconds': f['process_cpu_seconds'],
            'training_million_samples_per_second': n / s['elapsed_seconds'] / 1e6,
            'process_million_samples_per_second': n / f['wall_seconds'] / 1e6,
            'process_cpu_seconds_per_million_samples': f['process_cpu_seconds'] / n * 1e6,
            'average_logical_cpus': f['process_cpu_seconds'] / f['wall_seconds'],
            'ci': s['ci']['value'], 'ci_selected_nodes': s['ci']['selected_nodes'],
            'peak_working_set_bytes': f['peak_working_set_bytes'],
            'checkpoint_training_seconds': s['training_checkpoint_seconds'],
            'checkpoint_fraction': s['training_checkpoint_seconds'] / s['elapsed_seconds'],
            'control_rounds': s['parallel_control_rounds'],
            'mean_wall_ms_per_control_round': 1000*s['elapsed_seconds']/s['parallel_control_rounds'],
            'wall_minus_50ms_times_rounds_seconds': s['elapsed_seconds'] - .05*s['parallel_control_rounds'],
            'wall_minus_50ms_times_rounds_is_not_measured_worker_idle': True,
            'terminal_settlements': s['terminal_settlements'],
            'scalar_calls_per_deal': s['scalar_calls']/n,
            'vector_calls_per_deal': s['vector_calls']/n,
            'table_lookups_per_deal': s['terminal_table_lookups']/n,
        }
    fixed = {}
    for state, name in [('early_own_10m', 'final'), ('mature_own_975030250', 'mature')]:
        path = f'reports/hrc-throughput-round3-{name}-20261108.json'
        report = read(path)
        sources[path] = hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        fixed[state] = report['medians']
        for row in fixed[state].values():
            row['median_cpu_seconds_per_million'] = row['cpu_seconds']/20
        fixed[state]['note'] = 'Each field is a separately computed median across three trials; do not treat all fields as one trial.'
    a, b = formal['current8'], formal['current20']
    decomposition = {
        'current20_vs_current8_process_throughput_ratio': b['process_million_samples_per_second']/a['process_million_samples_per_second'],
        'average_core_ratio': b['average_logical_cpus']/a['average_logical_cpus'],
        'cpu_work_efficiency_ratio': a['process_cpu_seconds_per_million_samples']/b['process_cpu_seconds_per_million_samples'],
        'identity': 'throughput_ratio = average_core_ratio * cpu_work_efficiency_ratio',
        'causality_limit': 'Exact accounting identity for distinct observed runs, not causal attribution; policy state, RNG/interleaving, background load and core placement differ.'
    }
    native_sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((ROOT/'native').iterdir()) if p.suffix in ('.cpp','.hpp','.h')}
    output = {
        'schema': 'independent-native-architecture-review-v1', 'date': '2026-11-08',
        'production_modified': False, 'fresh_training_performed_by_review': False,
        'formal': formal, 'parallel_accounting': decomposition, 'fixed_sample_medians': fixed,
        'report_sha256': sources, 'reviewed_native_source_sha256': native_sources,
        'production_build_at_review': read('analysis/hrc-native/build/build.json'),
        'scheduler_diagnostics': read('.research-cache/architecture-review-20261108/scheduler-profile/validation.json'),
        'hypotheses_not_measured': [
            'Default-store regret/average/counter cache-line separation reduces coherence traffic.',
            'Longer event-driven worker residency reduces control-tail idle materially.',
            'Profile-guided code layout/default-mode dispatch reduces branch/instruction-cache work.',
            'CPU topology or background applications explain any specific historical timing difference.'
        ],
        'limitations': [
            'CI is strategy-drift heuristic, not exploitability or an accuracy guarantee.',
            'Old phase instrumentation was a different locked-read build and perturbed wall time about 9.8%.',
            'No hardware PMU/cache-miss/branch-miss measurement, no current per-phase CPU attribution.',
            'Native20 vs historical HRC8 is not a matched-thread comparison.',
            'Scheduler instrumented throughput overhead must be measured by same-executable on/off plus production shadow.'
        ]
    }
    interpretation = ROOT/'reports/hrc-scheduler-profile-interpretation-20261108.json'
    if interpretation.is_file():
        output['scheduler_measurement'] = json.loads(interpretation.read_text())
        output['report_sha256'][str(interpretation.relative_to(ROOT))] = hashlib.sha256(interpretation.read_bytes()).hexdigest()
        output['limitations'][-1] = 'Same-executable on/off ranges overlap in three trials; no clear observer overhead detected, not proof of zero overhead. Production shadow differs by about 2.1-2.5% in median elapsed.'
    etw_review = ROOT/'reports/hrc-etw-cswitch-prefix-review-20261108.json'
    if etw_review.is_file():
        audited = json.loads(etw_review.read_text()).get('final_diagnostic_review')
        if audited:
            output['current_etw_review'] = audited
            output['next_priority'] = ['shared-policy read path and runtime raw layout',
                                       'writer synchronization/yield attribution', 'bucket mapping',
                                       'scheduler changes only if new measurements justify']
            output['report_sha256'][str(etw_review.relative_to(ROOT))] = hashlib.sha256(etw_review.read_bytes()).hexdigest()
    target = ROOT/'reports/hrc-architecture-review-20261108.json'
    target.write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'path':str(target),'formal':formal,'parallel_accounting':decomposition},indent=2))


if __name__ == '__main__':
    main()
