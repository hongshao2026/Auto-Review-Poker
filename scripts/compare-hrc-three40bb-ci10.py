"""Read-only comparison of independently trained 3p40 full-tree CI10 results.

HRC strategies are first read here, after independent training. Hand frequency
and historical EV differences do not establish loss or exploitability.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.cards import HAND_LABELS, RANKS
from preflop_lab.hrc_hrcz_tree import load_archive_tree
from preflop_lab.hrc_native import read_node
from preflop_lab.hrc_research import Reference, decoder


def require(condition, message):
    if not condition: raise ValueError(message)


def identity(path):
    path = Path(path)
    with path.open('rb') as f: digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return {'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': digest}


def weight(hand): return 6 if len(hand) == 2 else 4 if hand.endswith('s') else 12


def native_hands_by_label(rows):
    # Storage buckets start at 22, whereas a display matrix starts at AA.
    # Bind via the audited bucket labels before ordering the rendered matrix.
    labels = decoder().HAND_LABELS
    return {labels[row['bucket']]: row for row in rows}


def historical_gap(values):
    if values is None or len(values) < 2: return None
    ordered = sorted(values, reverse=True)
    return ordered[0]-ordered[1]


def metrics(rows):
    mass = sum(r['combos'] for r in rows)
    k = len(rows[0]['hrc'])
    mean = lambda values: sum(r['combos']*v for r, v in zip(rows, values))/mass
    p = [mean([r['hrc'][a] for r in rows]) for a in range(k)]
    q = [mean([r['ours'][a] for r in rows]) for a in range(k)]
    tv = mean([sum(abs(a-b) for a, b in zip(r['hrc'], r['ours']))/2 for r in rows])
    ev_rows = [r for r in rows if r['hrc_ev_bb'] is not None and r['ours_ev_bb'] is not None]
    ev_mass = sum(r['combos'] for r in ev_rows)
    ev_mae = (sum(r['combos']*sum(abs(a-b) for a, b in zip(r['hrc_ev_bb'][1:], r['ours_ev_bb'][1:]))
                  for r in ev_rows)/ev_mass/(k-1)) if ev_mass and k > 1 else None
    covered = [r for r in rows if r['ours_visits'] > 0 and r['hrc_average_trained']]
    return {'hrc_frequency': p, 'ours_frequency': q,
        'aggregate_TV_pp': 50*sum(abs(a-b) for a, b in zip(p, q)),
        'combo_weighted_hand_TV_pp': 100*tv, 'action_MAE_pp': 200*tv/k,
        'max_hand_TV_pp': max(50*sum(abs(a-b) for a, b in zip(r['hrc'], r['ours'])) for r in rows),
        'historical_relative_EV_MAE_bb': ev_mae, 'EV_covered_combos': ev_mass,
        'both_trained_combos': sum(r['combos'] for r in covered),
        'ours_min_hand_visits': min(r['ours_visits'] for r in rows),
        'ours_max_hand_visits': max(r['ours_visits'] for r in rows),
        'weighting': 'uniform 1326 hole-card combinations at each node; not prefix reach'}


def plot(node, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import Rectangle, Patch
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    actions = node['actions']; k = len(actions)
    palette = ['#d9dfe6', '#8cb9c2', '#f2be77', '#dc9957', '#d96d66', '#b45357']
    colors = []
    raise_index = 0
    for action in actions:
        if action['kind'] == 'fold': color = palette[0]
        elif action['kind'] in ('check', 'call'): color = palette[1]
        elif action['kind'] == 'allin' or action.get('all_in'): color = palette[-1]
        else: color = palette[min(2+raise_index, 4)]; raise_index += 1
        colors.append(color)
    fig, axes = plt.subplots(1, 2, figsize=(16, 9), constrained_layout=False)
    fig.subplots_adjust(left=.04, right=.98, top=.84, bottom=.18, wspace=.16)
    fig.suptitle('3 人 40BB · '+node['label'], fontproperties=font, fontsize=20, y=.97)
    fig.text(.04, .91, '色带宽度 = 行动概率；格内数字 = 所有加注/全下频率之和。两版分别训练至各自 CI＜10。', fontproperties=font, fontsize=11)
    for ax, key, label in zip(axes, ('hrc', 'ours'), ('HRC 原版', '我们的内核')):
        ax.set(xlim=(0, 13), ylim=(13, 0), aspect='equal')
        ax.set_xticks([i+.5 for i in range(13)], RANKS)
        ax.set_yticks([i+.5 for i in range(13)], RANKS)
        ax.xaxis.tick_top(); ax.tick_params(length=0, pad=5)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.set_title(label, fontproperties=font, fontsize=15, pad=29)
        for i, row in enumerate(node['hands']):
            y, x = divmod(i, 13); offset = 0
            for probability, color in zip(row[key], colors):
                ax.add_patch(Rectangle((x+.02+offset*.96, y+.02), probability*.96, .96,
                                      facecolor=color, edgecolor='none'))
                offset += probability
            aggressive = sum(v for v, action in zip(row[key], actions) if action['kind'] in ('raise', 'allin'))
            ax.text(x+.5, y+.37, row['hand'], ha='center', va='center', fontsize=9,
                    bbox={'facecolor': 'white', 'alpha': .75, 'edgecolor': 'none', 'pad': .6})
            ax.text(x+.5, y+.75, f'{100*aggressive:.1f}%', ha='center', va='center', fontsize=7)
    labels = [a['label'] for a in actions]
    fig.legend([Patch(facecolor=c) for c in colors], labels, prop=font, ncol=min(k, 5),
               loc='lower center', bbox_to_anchor=(.5, .09), frameon=False)
    fig.text(.04, .045, f"逐手牌 TV {node['metrics']['combo_weighted_hand_TV_pp']:.3f} pp；"
             '按 1326 组合加权。历史 EV 差值不是当前策略损失或 exploitability。', fontproperties=font, fontsize=10)
    fig.savefig(output, dpi=160, bbox_inches='tight'); plt.close(fig)


def compare(original, native, compact, *, minimum_original_samples=0):
    tree = load_archive_tree(original)
    require(tree.rules.players == compact['players'] == 3, 'Expected three players')
    require(all(s == 40*tree.rules.big_blind for s in tree.rules.initial_stacks), 'Expected 40BB stacks')
    ref = Reference(original)
    root_saved = ref.decoder.decode_storage(ref.records[tree.root], ref.nodes[tree.root])['saved_counter_float32']
    require(root_saved+256 >= minimum_original_samples, 'Original archive predates the observed CI-target samples')
    index = json.loads((native/'index.json').read_text(encoding='utf-8'))
    pairs = {}; stack = [(tree.root, compact['root'], ())]
    while stack:
        oid, nid, path = stack.pop(); o, n = tree.nodes[oid], compact['nodes'][nid]
        require((o.actor if not o.terminal else -1) == n['actor'] and len(o.children) == len(n['children']), 'Topology mismatch')
        if not o.terminal and o.street == 0: pairs[path] = (oid, nid)
        for edge, (a, b) in enumerate(zip(o.children, n['children'])):
            require(tree.nodes[a].incoming_actions[0].kind == n['actions'][edge], 'Action order mismatch')
            stack.append((a, b, path+(edge,)))
    def edge(path, kind):
        o = tree.nodes[pairs[path][0]]
        found = [i for i, c in enumerate(o.children) if tree.nodes[c].incoming_actions[0].kind == kind]
        require(bool(found), 'Required decision action missing'); return path+(found[0],)
    fold, opening = edge((), 0), edge((), 3)
    sb_3bet = edge(opening, 3)
    selections = {(): ('btn', 'BTN 首入池'), fold: ('sb', 'BTN 弃牌后的 SB'),
                  edge(opening, 0): ('bb-defend', 'BB 面对 BTN 2.3BB，SB 已弃牌'),
                  edge(sb_3bet, 0): ('btn-vs-3bet', 'BTN 面对 SB 首档 3bet，BB 已弃牌')}
    selected = []; all_nodes = []
    for path, (oid, nid) in sorted(pairs.items()):
        o = tree.nodes[oid]; decoded = ref.decoder.decode_storage(ref.records[oid], ref.nodes[oid])
        original_hands = ref.node(oid)
        original_training = {r['hand']: r.get('has_positive_average_weight', False) for r in decoded['buckets']}
        ours = read_node(native, nid, index=index)
        require(len(ours['hands']) == 169 and len(original_hands) == 169, 'Expected all 169 classes')
        ours_by_label = native_hands_by_label(ours['hands'])
        hands = []
        for hand in HAND_LABELS:
            row = ours_by_label[hand]
            p, q = original_hands[hand]['frequencies'], row['display_strategy']
            require(len(p) == len(q) == len(o.children), 'Policy dimensions differ')
            require(all(math.isfinite(v) and 0 <= v <= 1 for v in p+q) and
                    abs(sum(p)-1) < 1e-6 and abs(sum(q)-1) < 1e-6, 'Invalid policy')
            original_ev, native_ev = original_hands[hand]['relative_ev_bb'], row['relative_ev_to_action0']
            hands.append({'hand': hand, 'combos': weight(hand), 'hrc': p, 'ours': q,
                'hrc_ev_bb': original_ev,
                'ours_ev_bb': native_ev, 'ours_visits': row['visits'],
                'hrc_historical_best_second_gap_bb': historical_gap(original_ev),
                'ours_historical_best_second_gap_bb': historical_gap(native_ev),
                'hrc_average_trained': original_training[hand],
                'TV_pp': 50*sum(abs(a-b) for a, b in zip(p, q))})
        node = {'path': list(path), 'original_id': oid, 'native_id': nid, 'actor': o.actor,
                'original_node_counter_float32': decoded['saved_counter_float32'],
                'native_node_updates': ours['updates'], 'metrics': metrics(hands)}
        all_nodes.append(node)
        if path in selections:
            slug, label = selections[path]
            selected.append({**node, 'slug': slug, 'label': label,
                'actions': tree.describe_node(node_id=oid)['actions'], 'hands': hands,
                'largest_differences': sorted(hands, key=lambda r: r['TV_pp'], reverse=True)[:12]})
    return selected, all_nodes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--native', type=Path, required=True)
    p.add_argument('--compact', type=Path, required=True)
    p.add_argument('--original-run', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); a.output.parent.mkdir(parents=True, exist_ok=True)
    original_ci = [json.loads(line) for line in (a.original_run/'original-ci.jsonl').read_text(encoding='utf-8').splitlines()]
    original_ci = [r for r in original_ci if r.get('index', -1) >= 0 and r.get('original_epoch_millis', 0) > 0
                   and type(r.get('ci')) in (float, int) and math.isfinite(r['ci'])]
    require(bool(original_ci) and original_ci[-1]['ci'] < 10, 'Original run has not reached CI<10')
    native_summary = json.loads((a.native/'summary.json').read_text(encoding='utf-8'))
    require(native_summary.get('stop_reason') == 'ci_target' and native_summary.get('target_reached')
            and native_summary['ci']['value'] < 10, 'Native run has not reached CI<10')
    compact = json.loads(a.compact.read_text(encoding='utf-8'))
    selected, nodes = compare(a.original, a.native, compact,
                              minimum_original_samples=original_ci[-1]['original_samples'])
    result = {'schema': 'three40bb-ci10-strategy-comparison-v1',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'original': identity(a.original),
        'native_checkpoint': identity(a.native/'checkpoint.bin'), 'compact': identity(a.compact),
        'original_last_ci': original_ci[-1]['ci'], 'native_last_ci': native_summary['ci']['value'],
        'preflop_nodes_compared': len(nodes), 'nodes': nodes, 'selected': selected,
        'limits': ['Historical EV differences are not current profile loss, best response or exploitability.',
                   'CI is recent policy drift; two CI10 runs do not prove algorithm identity.',
                   'Uniform-combo weighting at a downstream node is not prefix-reach weighting.',
                   'Different random streams and asynchronous worker ordering; one run per engine.']}
    for node in selected:
        destination = a.output.with_name(a.output.name+'-'+node['slug']+'.png')
        plot(node, destination); node['figure'] = str(destination.resolve())
    a.output.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    with a.output.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f); writer.writerow(['node', 'hand', 'TV_pp', 'hrc_action_probs', 'ours_action_probs', 'hrc_historical_ev_bb', 'ours_historical_ev_bb'])
        for node in selected:
            for r in node['hands']:
                writer.writerow([node['slug'], r['hand'], r['TV_pp'], r['hrc'], r['ours'], r['hrc_ev_bb'], r['ours_ev_bb']])
    print(json.dumps({'report': str(a.output.with_suffix('.json')), 'preflop_nodes': len(nodes),
        'selected': [{'node': n['label'], **n['metrics']} for n in selected]}, ensure_ascii=False))


if __name__ == '__main__': main()
