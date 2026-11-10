"""Audit pairwise factors against original static monetary outcome evaluators.

The original UI handler/formula are inspected, not initialized. The unchanged
allowlisted BountyProbe supplies baseline/win/loss using original pure classes.
"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_analysis import analyze_solver
from preflop_lab.hrc_custom import default_config

JAVA = Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
JAR = Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')


def main():
    helper = runpy.run_path(str(ROOT / 'tests/test_hrc_equity.py'))
    out = ROOT / 'analysis/hrc-deep/bubble-factors'
    out.mkdir(parents=True, exist_ok=True)
    declarations = subprocess.run([str(JAVA.with_name('javap.exe')), '-c', '-p', '-s', '-classpath', str(JAR),
                                   'net.holdemresources.internal.eC', 'net.holdemresources.internal.D'], capture_output=True, text=True, check=True)
    (out / 'formula-bytecode.txt').write_text(declarations.stdout, encoding='utf-8')
    cases, results = [], []
    for n in range(2, 11):
        for kind in ('none', 'ko', 'pko'):
            cfg = default_config(n)
            cfg.update(utility='icm', payouts=[50, 30, 20][:n])
            stacks = [100 * (1 + (i * 7) % 4) for i in range(n)]
            heads = [0] * n if kind == 'none' else [10] * n if kind == 'ko' else [5 + 5 * i for i in range(n)]
            alpha = .5 if kind == 'pko' else 1
            cfg['bounty'] = {'mode': kind, 'amounts': heads, 'other_amounts': [], 'immediate_fraction': alpha}
            equity = {'mode': 'icm', 'payouts': cfg['payouts'], 'other_stacks': [], 'bounty': cfg['bounty']}
            solver = SimpleNamespace(config=cfg, equity_config=equity,
                                     tree=SimpleNamespace(rules=SimpleNamespace(players=n, initial_stacks=stacks, big_blind=100)))
            observed = analyze_solver(solver)
            scenario = f'{n}_{kind}'
            for pair in observed['pairs']:
                i, j = pair['row'], pair['column']
                for name, winner, loser in [('win', i, j), ('lose', j, i)]:
                    final, masks = stacks[:], [0] * n
                    amount = min(stacks[i], stacks[j])
                    final[winner] += amount
                    final[loser] -= amount
                    if not final[loser]:
                        masks[loser] = 1 << winner
                    cases.append({'id': f'{scenario}_{i}_{j}_{name}', 'initial': stacks, 'final': final,
                                  'payouts': cfg['payouts'], 'bounties': heads, 'bounty_mode': ('none', 'ko', 'pko').index(kind),
                                  'alpha': alpha, 'masks': masks})
            results.append({'id': scenario, 'config': equity, 'stacks': stacks, 'independent': observed})
    inputs = out / 'original-inputs.tsv'
    inputs.write_text('\n'.join(helper['terminal_line'](c) for c in cases) + '\n')
    classes = out / 'classes'
    classes.mkdir(exist_ok=True)
    source = ROOT / 'scripts/java/OriginalBountyProbe.java'
    subprocess.run([str(JAVA.with_name('javac.exe')), '-d', str(classes), str(source)], capture_output=True, check=True)
    original = subprocess.run([str(JAVA), '-cp', str(classes), 'OriginalBountyProbe', str(JAR), str(inputs)], capture_output=True, text=True, check=True)
    (out / 'original-output.jsonl').write_text(original.stdout)
    rows = [json.loads(line) for line in original.stdout.splitlines()]
    outputs = {r['id']: r for r in rows if r['kind'] == 'case'}
    errors, factors, premiums = [], [], []
    for item in results:
        for pair in item['independent']['pairs']:
            i, j = pair['row'], pair['column']
            win = outputs[f'{item["id"]}_{i}_{j}_win']
            lose = outputs[f'{item["id"]}_{i}_{j}_lose']
            base, w, l = win['baseline'][i], win['total'][i], lose['total'][i]
            bf = (base - l) / (w - base)
            rp = 100 * (bf / (bf + 1) - .5)
            errors += [abs(base-item['independent']['baseline_equities'][i]), abs(w-pair['win_equity']), abs(l-pair['lose_equity'])]
            factors.append(abs(bf - pair['bubble_factor']))
            premiums.append(abs(rp - pair['risk_premium_pp']))
    report = {'scope': 'Local-table ICM/KO/PKO pairwise all-in analysis. Original pure evaluators supply baseline/win/loss; eC and D formula inspected as bytecode, not invoked as GUI handlers. MTT uses the separately validated original-matching MTT evaluator; not part of this matrix.',
              'jar_sha256': hashlib.sha256(JAR.read_bytes()).hexdigest(), 'scenario_count': len(results),
              'ordered_pair_count': len(factors), 'original_outcome_count': len(cases),
              'max_equity_error': max(errors), 'max_bubble_factor_error': max(factors), 'max_risk_premium_pp_error': max(premiums),
              'passed': max(errors + factors + premiums) < 1e-9,
              'formula_evidence': 'analysis/hrc-deep/bubble-factors/formula-bytecode.txt',
              'original_class_hashes': [r for r in rows if r['kind'] == 'class'], 'scenarios': results}
    (ROOT / 'reports/hrc-original-bubble-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('scenarios', 'original_class_hashes')}))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
