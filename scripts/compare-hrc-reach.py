"""Compare preflop policies on paths sampled under the original reference policy.

This is a descriptive policy-distance diagnostic, not exploitability. It deals
all nine players' cards without replacement, so folded cards remain blockers.
"""
import argparse
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_benchmarks import config_for
from preflop_lab.hrc_native import read_node
from preflop_lab.hrc_research import HRCResearchSolver, Reference


def evaluate(folder, benchmark='nine20bb', samples=100_000, seed=101):
    solver = HRCResearchSolver(config_for(benchmark))
    tree = solver.tree
    reference = Reference(solver.archive)
    index = json.loads((folder/'index.json').read_text())
    original, independent, visits = {}, {}, {}
    for n in tree.nodes:
        if n.terminal or n.street != 0:
            continue
        data = reference.decoder.decode_storage(reference.records[n.id], reference.nodes[n.id])
        original[n.id] = [r['display_strategy'] for r in data['buckets']]
        actual = read_node(folder, n.id, index=index)['hands']
        independent[n.id] = [r['display_strategy'] for r in actual]
        visits[n.id] = [r['visits'] for r in actual]
    rng = random.Random(seed)
    dealt = list(range(52))
    decisions = missing = 0
    tv_sum = path_sum = path_square = 0.0
    node_counts, node_tv = {}, {}
    for _ in range(samples):
        cards = rng.sample(dealt, 2*tree.rules.players)
        buckets = []
        for p in range(tree.rules.players):
            a,b=cards[2*p:2*p+2]
            hi,lo=max(a//4,b//4),min(a//4,b//4)
            buckets.append(hi*14 if hi==lo else hi*13+lo if a%4==b%4 else lo*13+hi)
        n = tree.nodes[tree.root]
        distance = 0.0
        while not n.terminal and n.street == 0:
            h = buckets[n.actor]
            q,p = original[n.id][h],independent[n.id][h]
            if visits[n.id][h] == 0:
                missing += 1
            tv = sum(abs(a-b) for a,b in zip(p,q))/2
            decisions += 1
            distance += tv
            tv_sum += tv
            node_counts[n.id] = node_counts.get(n.id,0)+1
            node_tv[n.id] = node_tv.get(n.id,0)+tv
            u=rng.random()
            choice=len(q)-1
            for i,probability in enumerate(q):
                u -= probability
                if u <= 0:
                    choice=i
                    break
            n = tree.nodes[n.children[choice]]
        path_sum += distance
        path_square += distance*distance
    mean=path_sum/samples
    return {'training_samples': index['samples'], 'evaluation_hands': samples, 'evaluation_seed': seed,
            'preflop_decisions': decisions, 'untrained_decisions': missing,
            'reference_reach_mean_total_variation': tv_sum/decisions,
            'mean_sum_policy_tv_per_deal': mean,
            'standard_error_mean_sum_policy_tv_per_deal': ((path_square/samples-mean*mean)/(samples-1))**.5,
            'per_node': [{'node_id': nid,'path':tree.node_path(nid),'actor':tree.nodes[nid].actor,
                          'sampled_visits':count,'mean_total_variation':node_tv[nid]/count}
                         for nid,count in sorted(node_counts.items(),key=lambda pair:-pair[1])],
            'scope': 'Preflop action-distribution distance under reference-policy reach with blockers. Not exploitability, not postflop comparison. Untrained actual decisions use uniform display fallback and are counted explicitly.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder',type=Path)
    p.add_argument('--benchmark',default='nine20bb')
    p.add_argument('--samples',type=int,default=100_000)
    args=p.parse_args()
    result=evaluate(args.folder,args.benchmark,args.samples)
    output=args.folder/'reference-reach-comparison.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='per_node'}))


if __name__=='__main__':
    main()
