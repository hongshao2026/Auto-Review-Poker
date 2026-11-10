"""Train independently, then compare checkpoints to a separately read HRC save."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_benchmarks import BENCHMARKS, CACHE, config_for
from preflop_lab.hrc_native import run
from preflop_lab.hrc_research import HRCResearchSolver, Reference


def evaluate(solver, all_preflop=False):
    root = solver.result_node([])
    result = {'root': root['strategy']['comparison'],
              'selected_hands': {h: root['strategy']['hands'][h] for h in ('AA', 'KK', 'AKs', '22', '72o')}}
    if all_preflop:
        rows = []
        for n in solver.tree.nodes:
            if n.street == 0 and not n.terminal:
                path = solver.tree.node_path(n.id)
                data = solver.result_node(path)
                rows.append({'node_id': n.id, 'path': path, 'actor': n.actor,
                             'updates': data['strategy']['visits'], **data['strategy']['comparison']})
        covered = [r for r in rows if r['frequency_mae_pp'] is not None]
        full = [r for r in rows if r['covered_combos'] == 1326]
        result['preflop'] = {'nodes': len(rows), 'visited_nodes': len(covered), 'fully_covered_nodes': len(full),
                            'unweighted_mean_node_frequency_mae_pp': sum(r['frequency_mae_pp'] for r in covered)/len(covered) if covered else None,
                            'interpretation': 'Descriptive conditional errors, not reach-weighted game error or exploitability.',
                            'node_errors': rows}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', default='nine20bb', choices=list(BENCHMARKS))
    parser.add_argument('--budgets', type=int, nargs='+', default=[100_000, 1_000_000, 10_000_000, 60_000_000])
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--all-preflop', action='store_true')
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    solver = HRCResearchSolver(config_for(args.benchmark, max(args.budgets), args.seed))
    compact = solver.tree.compact_export()
    checkpoint = folder / 'checkpoint.bin'
    if checkpoint.exists() and not args.resume:
        parser.error('Output already contains a checkpoint; choose a new directory or --resume.')
    report_file = folder / 'benchmark.json'
    report = json.loads(report_file.read_text()) if args.resume and report_file.exists() else {
        'schema': 'independent-hrc-comparison-v1', 'benchmark': args.benchmark, 'seed': args.seed,
        'training_original_strategy_loaded': False, 'topology': solver.tree.provenance,
        'limitations': ['Imported topology and shipped abstraction data; independently trained strategy.',
                        'Independent random seed stream and serial scheduling, not bitwise original replay.',
                        'Equal sample counts alone do not establish convergence or HRC equivalence.'], 'checkpoints': []}
    for budget in sorted(set(args.budgets)):
        if checkpoint.exists():
            previous = json.loads((folder/'index.json').read_text())['samples']
            if previous >= budget:
                continue
        result = run(compact, CACHE/'abstractions', budget, args.seed, folder,
                     progress_callback=lambda e: print(json.dumps(e), flush=True),
                     resume_from=checkpoint if checkpoint.exists() else None)
        solver.output = folder
        solver.index = json.loads((folder/'index.json').read_text())
        if solver.reference is None:
            solver.reference = Reference(solver.archive)
        metrics = evaluate(solver, args.all_preflop)
        entry = {'samples': budget, 'generated_utc': datetime.now(timezone.utc).isoformat(),
                 'summary': result['summary'], **metrics}
        report['checkpoints'].append(entry)
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        print(json.dumps({'samples': budget, 'comparison': metrics['root']}), flush=True)
    print(json.dumps({'report': str(report_file)}))


if __name__ == '__main__':
    main()
