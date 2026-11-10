"""Reproducible original-bytecode ICM comparison against a forward finish-order oracle."""
from collections import Counter
from functools import lru_cache
import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/hrc-deep/probes'
OUT.mkdir(parents=True, exist_ok=True)
JAVA = Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
JAR = Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')

def forward_rank_oracle(stacks, prizes):
    """Propagate probabilities from preceding winners to the NEXT winner."""
    n = len(stacks)
    rank_values = [[0.0] * n for _ in prizes[:n]]
    states = {0: 1.0}
    for rank, prize in enumerate(prizes[:n]):
        next_states = {}
        for eliminated, probability in states.items():
            remaining = [i for i in range(n) if not eliminated & (1 << i)]
            remaining_chips = sum(stacks[i] for i in remaining)
            for i in remaining:
                p = probability * stacks[i] / remaining_chips
                rank_values[rank][i] += prize * p
                nxt = eliminated | (1 << i)
                next_states[nxt] = next_states.get(nxt, 0.0) + p
        states = next_states
    return rank_values

def permutation_oracle(stacks, prizes):
    total = [0.0] * len(stacks)
    for order in itertools.permutations(range(len(stacks))):
        probability, chips = 1.0, sum(stacks)
        for i in order:
            probability *= stacks[i] / chips
            chips -= stacks[i]
        for rank, i in enumerate(order[:len(prizes)]):
            total[i] += probability * prizes[rank]
    return total

cases = []
def case(name, stacks, prizes):
    cases.append((name, stacks, prizes))

case('one_player', [100], [1000])
case('known_3', [50, 30, 20], [500, 300, 200])
case('known_3_scaled', [5000, 3000, 2000], [500, 300, 200])
case('nine_equal', [100] * 9, [900, 600, 400, 300, 200])
case('nine_winner_only', [11, 17, 25, 38, 42, 60, 75, 83, 95], [1000])
rng = random.Random(20261104)
for n in range(2, 11):
    for variant in range(4):
        stacks = [rng.randint(1, 300) for _ in range(n)]
        if variant == 0: prizes = [1000]
        elif variant == 1: prizes = [100] * n
        elif variant == 2: prizes = sorted([rng.randint(0, 1000) for _ in range(n)], reverse=True)
        else: prizes = [500, 300, 200][:min(3, n)]
        case(f'random_{n}_{variant}', stacks, prizes)
input_path = OUT / 'icm-inputs.tsv'
input_path.write_text(''.join(f'{name}\t{",".join(map(str,stacks))}\t{",".join(map(str,prizes))}\n' for name,stacks,prizes in cases), encoding='utf-8')
command = [str(JAVA), '-cp', str(ROOT / 'analysis/hrc-deep/java-tools'), 'OriginalIcmProbe', str(JAR), str(input_path)]
classes = ROOT / 'analysis/hrc-deep/java-tools'
classes.mkdir(parents=True, exist_ok=True)
subprocess.run([str(JAVA.with_name('javac.exe')), '-d', str(classes), str(ROOT / 'scripts/java/OriginalIcmProbe.java')], check=True, capture_output=True)
run = subprocess.run(command, check=True, capture_output=True, text=True)
(OUT / 'icm-original-output.jsonl').write_text(run.stdout, encoding='utf-8')
records = [json.loads(line) for line in run.stdout.splitlines()]
results = []
for record in records:
    if record['kind'] != 'case': continue
    expected_ranks = forward_rank_oracle(record['stacks'], record['prizes'])
    expected = [sum(row[i] for row in expected_ranks) for i in range(len(record['stacks']))]
    value_error = max(abs(x-y) for x,y in zip(expected, record['values']))
    rank_error = max(abs(x-y) for r,s in zip(expected_ranks,record['rank_values']) for x,y in zip(r,s))
    permutation_error = None
    if len(record['stacks']) <= 6:
        permutation_error = max(abs(x-y) for x,y in zip(expected,permutation_oracle(record['stacks'],record['prizes'])))
    conservation_error = abs(sum(record['values']) - sum(record['prizes'][:len(record['stacks'])]))
    passed = max(value_error, rank_error, conservation_error, permutation_error or 0.0) < 1e-9
    results.append({**record, 'expected':expected, 'max_value_error':value_error,'max_rank_error':rank_error,'prize_conservation_error':conservation_error,'permutation_crosscheck_error':permutation_error,'passed':passed})
summary = {'artifact':str(JAR),'sha256':hashlib.sha256(JAR.read_bytes()).hexdigest(),'command':command,
           'scope':'Unmodified kV/kU/kW, isolated classloader with platform-only parent; positive stack kernel only; no application initialization, FGS, KO, MTT, zero-stack wrapper or full solve covered.',
           'oracle':'Forward transition probabilities over previous finishers; exhaustive finish-order permutations also used for <=6 players.',
           'case_count':len(results),'passed':all(r['passed'] for r in results),'max_value_error':max(r['max_value_error'] for r in results),
           'class_hashes':[r for r in records if r['kind']=='class'],'cases':results}
report = ROOT / 'reports/hrc-original-icm-validation.json'
report.write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps({k:summary[k] for k in ('case_count','passed','max_value_error')}, indent=2))
if not summary['passed']: raise SystemExit(1)
