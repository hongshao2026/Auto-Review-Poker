"""Interleaved old/new kernel measurements, exact-mode parity and seed drift.

The supplied cache must contain the retained baseline and independently generated
nine40bb_chip/nine40bb_large_chip inputs. This script never changes those inputs.
Large temporary checkpoint/index files are removed after recording hashes and
root counters; all measurements and commands remain in the report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_native import build, read_node


def timed_baseline(source):
    replacements = [
        ('    int training_threads=1;', '    int training_threads=1;uint64_t checkpoint_writes=0;double checkpoint_seconds=0;'),
        ('    void save(const fs::path& folder){', '    void save(const fs::path& folder){auto saving_start=std::chrono::steady_clock::now();'),
        ('fs::rename(folder/"index.tmp",target);', 'fs::rename(folder/"index.tmp",target);++checkpoint_writes;checkpoint_seconds+=std::chrono::duration<double>(std::chrono::steady_clock::now()-saving_start).count();'),
        ('bool cancelled=false;', 'bool cancelled=false;double initial_checkpoint_seconds=e.checkpoint_seconds;'),
        ('<<e.terminal_calls<<",\\\"ci\\\":";e.write_ci(std::cout);', '<<e.terminal_calls<<",\\\"checkpoint_writes\\\":"<<e.checkpoint_writes<<",\\\"checkpoint_seconds\\\":"<<e.checkpoint_seconds<<",\\\"training_checkpoint_seconds\\\":"<<(e.checkpoint_seconds-initial_checkpoint_seconds)<<",\\\"ci\\\":";e.write_ci(std::cout);'),
    ]
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError('Baseline timer anchor changed: ' + before)
        source = source.replace(before, after, 1)
    return source


def selected_nodes(path, scene):
    index = json.loads((path/'index.json').read_text())
    ids = {'root': 0}
    if scene == 'nine40bb_chip':
        ids.update(btn_open=6, sb_vs_btn_open=297, btn_vs_sb_3bet=654, sb_vs_btn_4bet=656)
    result = {}
    for name, node_id in ids.items():
        n = read_node(path, node_id, index=index)
        result[name] = {'node_id': node_id, 'updates': n['updates'], 'actions': n['actions'],
                        'hands': [{'bucket': h['bucket'], 'visits': h['visits'],
                                   'display_strategy': h['display_strategy']} for h in n['hands']]}
    return result


def distance(left, right):
    weighted = 0.; mass = 0
    for a, b in zip(left['hands'], right['hands']):
        r, c = divmod(a['bucket'], 13)
        weight = 6 if r == c else 4 if r > c else 12
        weighted += weight*sum(abs(x-y) for x,y in zip(a['display_strategy'],b['display_strategy']))/left['actions']
        mass += weight
    return {'combo_weighted_hand_action_mae_pp': 100*weighted/mass,
            'left_updates': left['updates'], 'right_updates': right['updates'],
            'left_unvisited_hands': sum(h['visits'] == 0 for h in left['hands']),
            'right_unvisited_hands': sum(h['visits'] == 0 for h in right['hands'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 5:
        parser.error('repeats must be 1..5')
    cache, output = args.cache.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=args.resume)
    helper = runpy.run_path(str(ROOT/'scripts/audit-hrc-performance.py'))
    executable = build()
    original = cache/'baseline/solver.exe'
    baseline = output/'baseline-timed.exe'
    baseline_source = cache/'baseline/native/hrc_research_solver.cpp'
    if not baseline.exists():
        patched = output/'baseline-timed.cpp'
        patched.write_text(timed_baseline(baseline_source.read_text()), encoding='utf-8')
        helper['compile_variant'](patched, baseline, [], cache/'baseline/native')
    scenes = {
        'nine40bb_chip': (cache/'nine40bb_chip/tree.bin', 1_000_000, 1<<30),
        'nine40bb_large_chip': (cache/'nine40bb_large_chip/tree.bin', 100_000, 4<<30),
        'eight15bb_pko': (helper['SCENES']['eight15bb_pko'], 1_000_000, 1<<30),
    }
    report_path = output/'report.json'
    report = {'schema': 'hrc-deep-tree-optimization-v1', 'generated_utc': datetime.now(timezone.utc).isoformat(),
              'repeats': args.repeats, 'executables': {name: {'path': str(p), 'sha256': helper['sha'](p)}
                   for name,p in [('original',original),('baseline_timed',baseline),('optimized',executable)]},
              'source_sha256': {str(p.relative_to(ROOT)): helper['sha'](p) for p in (ROOT/'native').iterdir() if p.is_file()},
              'scenes': {k: {'tree':str(v[0]), 'tree_sha256':helper['sha'](v[0]), 'samples':v[1], 'memory_budget_bytes':v[2]}
                         for k,v in scenes.items()}, 'trials': [], 'checks': [],
              'limits': ['Independent nine-player 40BB trees, maxactive4, no ante; not the user\'s complete unknown configuration.',
                         'Large tree timing uses 100k samples and includes final checkpoint I/O; this is not a 60M convergence measurement.',
                         'ChipEV constant-scalar shortcuts skip no target updates, but consume fewer random draws; enabled checkpoints need not match.',
                         'ICM/MTT/bounties/rake/FGS cannot use chip-only shortcuts.',
                         'Seed distances are descriptive and are not exploitability or a convergence guarantee.',
                         'No CPU affinity/clock control; timed baseline differs only by save-time instrumentation.']}
    if args.resume:
        previous = json.loads(report_path.read_text())
        if previous['executables'] != report['executables'] or previous['scenes'] != report['scenes'] or previous['repeats'] != args.repeats:
            raise ValueError('Resume inputs changed')
        report = previous

    def save():
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')

    def trial(scene, variant, repeat, threads=1, seed=43, exact=False, check=False):
        rows = report['checks' if check else 'trials']
        key = f'{scene}-{variant}-{repeat}-t{threads}-s{seed}'
        if any(r['key'] == key for r in rows):
            return next(r for r in rows if r['key'] == key)
        tree, samples, memory = scenes[scene]
        exe = original if variant == 'original' else baseline if variant == 'baseline' else executable
        folder = output/key
        r = helper['run_case'](exe, tree, folder, samples, seed, threads=threads,
                               max_memory_bytes=memory, constant_scalar_shortcuts=not exact)
        nodes = selected_nodes(folder, scene)
        root = nodes['root']
        if root['updates'] != samples or sum(h['visits'] for h in root['hands']) != samples:
            raise ValueError('Lost global samples')
        r.update(key=key, scene=scene, variant=variant, repeat=repeat, threads=threads, seed=seed,
                 nodes=nodes, constant_scalar_requested=not exact)
        timed_io = r['summary'].get('training_checkpoint_seconds')
        r['training_without_checkpoint_seconds'] = r['native_seconds']-timed_io if timed_io is not None else None
        rows.append(r); save()
        print(json.dumps({'kind':'trial', 'key':key, 'seconds':r['native_seconds'],
                          'compute_seconds':r['training_without_checkpoint_seconds'],
                          'shortcut_calls':r['summary'].get('constant_scalar_calls',0)}), flush=True)
        if scene == 'nine40bb_large_chip':
            for name in ('checkpoint.bin', 'index.json'):
                target = (folder/name).resolve()
                if not target.is_relative_to(output) or target.parent != folder:
                    raise ValueError('Temporary checkpoint escaped benchmark directory')
                target.unlink()
        return r

    for repeat in range(args.repeats):
        order = [('baseline',1), ('optimized',1), ('baseline',8), ('optimized',8)]
        order = order[repeat:]+order[:repeat]
        for scene in scenes:
            for variant, threads in order:
                trial(scene, variant, repeat, threads)

    report['results'] = {}
    for scene in scenes:
        results = {}
        for threads in (1,8):
            result = {}
            for variant in ('baseline','optimized'):
                rows = [r for r in report['trials'] if r['scene']==scene and r['variant']==variant and r['threads']==threads]
                result[variant] = {'median_native_seconds': statistics.median(r['native_seconds'] for r in rows),
                    'median_training_without_checkpoint_seconds': statistics.median(r['training_without_checkpoint_seconds'] for r in rows),
                    'median_wall_seconds':statistics.median(r['wall_seconds'] for r in rows),
                    'median_peak_mib':statistics.median(r['peak_working_set_bytes']/1048576 for r in rows),
                    'median_logical_cpus':statistics.median(r['average_logical_cpus'] for r in rows)}
            result['speedup'] = result['baseline']['median_native_seconds']/result['optimized']['median_native_seconds']
            result['compute_speedup'] = result['baseline']['median_training_without_checkpoint_seconds']/result['optimized']['median_training_without_checkpoint_seconds']
            results[threads] = result
        report['results'][scene] = results
    save()

    report['exact_mode_checkpoint_parity'] = {}
    for scene in scenes:
        base = next(r for r in report['trials'] if r['scene']==scene and r['variant']=='baseline' and r['threads']==1)
        exact = trial(scene,'optimized_exact',0,exact=True,check=True)
        same = base['checkpoint_sha256'] == exact['checkpoint_sha256']
        report['exact_mode_checkpoint_parity'][scene] = same
        if not same:
            raise ValueError('Exact-mode checkpoint mismatch: '+scene)

    # Ensure the timing instrumentation itself did not change the old kernel.
    original_trial = trial('nine40bb_chip','original',0,check=True)
    base43 = next(r for r in report['trials'] if r['scene']=='nine40bb_chip' and r['variant']=='baseline' and r['threads']==1)
    report['baseline_instrumentation_checkpoint_parity'] = original_trial['checkpoint_sha256'] == base43['checkpoint_sha256']
    if not report['baseline_instrumentation_checkpoint_parity']:
        raise ValueError('Baseline timer instrumentation changed checkpoint')

    report['strategy_comparisons'] = []
    for seed in (44,45):
        base = trial('nine40bb_chip','baseline',0,seed=seed,check=True)
        optimized = trial('nine40bb_chip','optimized',0,seed=seed,check=True)
        report['strategy_comparisons'].append({'seed': seed,
            'baseline_seed43_vs_seed': {name: distance(base43['nodes'][name],node) for name,node in base['nodes'].items()},
            'optimized_vs_baseline_same_seed': {name: distance(base['nodes'][name],node) for name,node in optimized['nodes'].items()}})
    save()
    print(json.dumps({'kind':'completed', 'results':report['results'], 'report':str(report_path)}), flush=True)


if __name__ == '__main__':
    main()
