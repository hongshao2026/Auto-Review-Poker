"""Render opening policies from registered fixed HRC benchmarks as 13x13 grids."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Patch, Rectangle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.cards import HAND_LABELS, RANKS


def require(condition, message):
    if not condition:
        raise ValueError(message)


def chinese_number(value):
    return {2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '七', 8: '八', 9: '九'}.get(value, str(value))


def fold_path_to_btn(solver, players):
    """Follow actual legal folds; player names determine the target seat."""
    names = [p['name'] for p in players]
    require(len(names) == len(set(names)) and names.count('BTN') == 1, 'Expected one uniquely named BTN seat')
    target = names.index('BTN')
    node = solver.describe_node([])
    first_actor, initial_pot = node['actor'], node['pot']
    require(first_actor is not None and first_actor <= target, 'BTN must follow the initial actor in this fixed preflop order')
    require(not any(node['folded']), 'Opening comparison requires an unacted initial state')
    path, labels = [], []
    for actor in range(first_actor, target):
        require(not node['terminal'] and node['street'] == 0 and node['actor'] == actor,
                'Fold path changed street or skipped the expected player')
        require(node['actor_name'] == names[actor] and not node['folded'][actor], 'Unexpected actor on BTN fold path')
        folds = [a for a in node['actions'] if a['kind'] == 'fold']
        require(len(folds) == 1, 'Expected exactly one legal fold action')
        previous_folded = list(node['folded'])
        labels.append(node['actor_name'] + ' 弃牌')
        path.append(folds[0]['id'])
        node = solver.describe_node(path)
        previous_folded[actor] = True
        require(node['folded'] == previous_folded, 'Fold edge changed an unexpected player state')
        require(math.isclose(node['pot'], initial_pot, abs_tol=1e-12), 'Pure fold path changed the pot')
    require(not node['terminal'] and node['street'] == 0 and node['actor'] == target
            and node['actor_name'] == 'BTN', 'Fold path did not reach a live preflop BTN decision')
    require(len(path) == target-first_actor and sum(node['folded']) == len(path), 'Fold path count mismatch')
    return node, path, labels


def reference_counts(reference, archive, node_id, metadata_path=None):
    """Read observed saved counters; explicit caller counts must bind the archive."""
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    roots = [i for i, n in reference.nodes.items() if n['parent_id'] == -1]
    require(len(roots) == 1, 'Reference archive does not have exactly one root')
    def counter(i):
        decoded = reference.decoder.decode_storage(reference.records[i], reference.nodes[i])
        value = decoded.get('saved_counter_float32')
        require(isinstance(value, (int, float)) and math.isfinite(value) and value > 0,
                'Reference archive has no positive finite saved node counter')
        return value
    root_count, node_count = counter(roots[0]), counter(node_id)
    result = {'archive': str(archive.resolve()), 'archive_sha256': archive_hash,
              'root_counter_float32': root_count, 'selected_node_counter_float32': node_count,
              'samples': root_count, 'sample_source': 'archive saved root update counter (float32 snapshot)',
              'count_semantics': 'Root and selected-node update counters are distinct; neither is a per-hand visit count.'}
    if metadata_path is not None:
        supplied = json.loads(metadata_path.read_text(encoding='utf-8'))
        require(supplied.get('archive_sha256') == archive_hash, 'Reference metadata archive SHA256 does not match')
        value = supplied.get('samples')
        require(isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value > 0, 'Reference metadata samples must be finite and positive')
        require(isinstance(supplied.get('source'), str) and supplied['source'].strip(), 'Reference metadata needs a sample source description')
        result.update(samples=value, sample_source=supplied['source'], caller_metadata=supplied,
                      caller_metadata_path=str(metadata_path.resolve()),
                      caller_metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest())
    return result


def load_comparison(data, fold_to_btn=False, reference_metadata=None):
    from preflop_lab.hrc_research import HRCResearchSolver, Reference
    require(data['summary']['status'] == 'completed', 'Only completed training results can be compared')
    monetary = data['config'].get('engine') == 'hrc_tournament'
    if monetary:
        from preflop_lab.hrc_tournament import HRCTournamentSolver
        from preflop_lab.hrc_tournament_reference import matching_reference, PKO_REFERENCE
        solver = HRCTournamentSolver(data['config'])
        solver.reference = matching_reference(solver)
        require(solver.reference is not None, 'No verified same-model tournament reference is registered')
        reference_archive = PKO_REFERENCE
    else:
        solver = HRCResearchSolver(data['config'])  # validates registered, pinned scenario
        solver.reference = Reference(solver.archive)
        reference_archive = solver.archive
    config = solver.config
    players = config['players']
    seats = len(players)
    stacks = [p['stack'] for p in players]
    require(len(set(stacks)) == 1 and stacks[0] > 0, 'This opening plot requires equal positive starting stacks')
    node = solver.describe_node([])
    first_actor = node['actor_name']
    require(first_actor == players[node['actor']]['name'], 'Initial actor/config mismatch')
    for key in ('settings_sha256', 'gametree_sha256'):
        expected = data.get('tree_provenance', {}).get(key)
        require(expected is None or expected == solver.tree.provenance[key], 'Result and registered reference tree identities differ')
    path, labels = [], []
    if fold_to_btn or monetary:
        solver.output = Path(data['native_artifacts']['checkpoint_path']).parent
        solver.index = json.loads((solver.output/'index.json').read_text(encoding='utf-8'))
        if fold_to_btn:
            node, path, labels = fold_path_to_btn(solver, players)
        strategy = solver.strategy_for(node)
    else:
        strategy = data['nodes']['root']
    require([a['kind'] for a in strategy['actions']] == ['fold', 'raise', 'allin'],
            'This plot expects exactly fold, non-all-in raise and all-in actions')
    raise_to = strategy['actions'][1]['amount']
    shove_to = strategy['actions'][2]['amount']
    require(math.isfinite(raise_to) and math.isfinite(shove_to) and 0 < raise_to < shove_to,
            'Invalid opening raise/all-in amounts')
    require(math.isclose(shove_to, stacks[node['actor']], abs_tol=1e-12), 'All-in amount differs from the selected fixed starting stack')
    observed = solver.reference.node(node['native_id'])
    require(all(strategy['hands'][h].get('reference') == observed[h] for h in HAND_LABELS),
            'Embedded comparison values differ from the pinned original reference')
    return {'strategy': strategy, 'benchmark': config['benchmark'], 'seats': seats, 'stack_bb': stacks[0],
            'first_actor': first_actor, 'actor': node['actor_name'], 'native_id': node['native_id'],
            'path': path, 'path_labels': labels, 'raise_to_bb': raise_to, 'shove_to_bb': shove_to,
            'utility_unit': 'currency' if monetary else 'BB',
            'reference': reference_counts(solver.reference, reference_archive, node['native_id'], reference_metadata)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path)
    parser.add_argument('--fold-to-btn', action='store_true', help='Compare BTN after every preceding player folds.')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reference-metadata', type=Path,
                        help='Optional JSON with archive_sha256, samples and source; otherwise read the saved root counter.')
    args = parser.parse_args()
    data = json.loads(args.result.read_text(encoding='utf-8'))
    context_data = load_comparison(data, args.fold_to_btn, args.reference_metadata)
    actor, path = context_data['actor'], context_data['path']
    path_labels, native_id = context_data['path_labels'], context_data['native_id']
    stack, seats = context_data['stack_bb'], context_data['seats']
    raise_to, shove_to = context_data['raise_to_bb'], context_data['shove_to_bb']
    root = context_data['strategy']
    if args.output is None:
        suffix = '-btn' if args.fold_to_btn else ''
        model_suffix = '-pko' if context_data['utility_unit'] == 'currency' else ''
        args.output = ROOT/f'reports/figures/hrc-{stack:g}bb{suffix}{model_suffix}-strategy-comparison'
    assert [a['kind'] for a in root['actions']] == ['fold', 'raise', 'allin']
    hands = root['hands']
    policies = [[hands[h]['reference']['frequencies'] for h in HAND_LABELS],
                [hands[h]['frequencies'] for h in HAND_LABELS]]
    for policy in policies:
        assert len(policy) == 169
        for values in policy:
            assert len(values) == 3 and all(math.isfinite(v) and 0 <= v <= 1 for v in values)
            assert abs(sum(values)-1) < 1e-6
    assert all(hands[h]['visits'] > 0 for h in HAND_LABELS)
    weights = [6 if len(h) == 2 else 4 if h.endswith('s') else 12 for h in HAND_LABELS]
    assert sum(weights) == 1326
    totals = [[sum(w*p[i] for w,p in zip(weights,policy))/1326 for i in range(3)] for policy in policies]
    colors = ['#DCE3EB', '#E6B07D', '#D8887E']
    ink, muted = '#20354A', '#637386'
    chinese = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    font = lambda size: FontProperties(fname=chinese.get_file(), size=size)
    fig = plt.figure(figsize=(18, 10.5), facecolor='#F7F9FC')
    model_title = ' · ICM PKO' if context_data['utility_unit'] == 'currency' else ''
    fig.text(.045,.948,f'{chinese_number(seats)}人 {stack:g}BB{model_title} · {actor} 策略对照',fontproperties=font(23),color=ink)
    context = f'前面{chinese_number(len(path))}人全部弃牌，BTN 首入池。' if args.fold_to_btn else f'{actor} 起始节点。'
    fig.text(.045,.908,context+f'每格色带宽度 = 行动概率；格内数字 = 加注到 {raise_to:g}BB 的频率。',fontproperties=font(11),color=muted)
    names = ['HRC 原版', f"我们的求解器 · seed {data['config']['seed']}"]
    for side, policy in enumerate(policies):
        left = .045 + side*.485
        ax = fig.add_axes([left,.165,.425,.67])
        ax.set_xlim(0,13); ax.set_ylim(13,0); ax.set_aspect('equal')
        ax.set_xticks([i+.5 for i in range(13)],RANKS)
        ax.set_yticks([i+.5 for i in range(13)],RANKS)
        ax.xaxis.tick_top(); ax.tick_params(axis='both',length=0,labelsize=10,pad=7,colors=muted)
        for spine in ax.spines.values(): spine.set_visible(False)
        for i,(hand,values) in enumerate(zip(HAND_LABELS,policy)):
            row,col=divmod(i,13)
            offset=0
            for probability,color in zip(values,colors):
                ax.add_patch(Rectangle((col+.025+offset*.95,row+.025),probability*.95,.95,facecolor=color,edgecolor='none'))
                offset += probability
            ax.text(col+.5,row+.38,hand,ha='center',va='center',fontsize=10,fontweight='bold',color=ink,
                    bbox={'facecolor':'white','edgecolor':'none','alpha':.72,'pad':1.2})
            ax.text(col+.5,row+.73,f'{100*values[1]:.1f}%',ha='center',va='center',fontsize=7.5,color=ink)
        fig.text(left,.86,names[side],fontproperties=font(16),color=ink)
        values=totals[side]
        fig.text(left,.113,f'弃牌 {values[0]*100:.4f}%     加注 {values[1]*100:.4f}%     全下 {values[2]*100:.4f}%',fontproperties=font(11),color=ink)
    fig.legend(handles=[Patch(facecolor=c,label=t) for c,t in zip(colors,['弃牌',f'加注到 {raise_to:g}BB',f'全下到 {shove_to:g}BB'])],
               loc='lower left',bbox_to_anchor=(.04,.042),ncol=3,frameon=False,prop=font(11))
    reference_samples = context_data['reference']['samples']
    reference_label = f'{int(reference_samples):,}' if int(reference_samples) == reference_samples else f'{reference_samples:,.3f}'
    fig.text(.53,.066,f"原版 {reference_label} 次 / 我们 {data['summary']['iterations_completed']:,} 次",fontproperties=font(10),color=muted)
    fig.text(.53,.038,'该节点平均策略，按 1326 组合加权；非到达范围加权。',fontproperties=font(10),color=muted)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(args.output.with_suffix('.png'),dpi=180,facecolor=fig.get_facecolor())
    fig.savefig(args.output.with_suffix('.svg'),facecolor=fig.get_facecolor())
    plt.close(fig)
    with args.output.with_suffix('.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.writer(stream)
        writer.writerow(['hand','hrc_fold',f'hrc_raise_{raise_to:g}bb',f'hrc_shove_{shove_to:g}bb',
                         'ours_fold',f'ours_raise_{raise_to:g}bb',f'ours_shove_{shove_to:g}bb'])
        for h,p,q in zip(HAND_LABELS,*policies): writer.writerow([h,*p,*q])
    meta={'source':str(args.result.resolve()),'source_sha256':hashlib.sha256(args.result.read_bytes()).hexdigest(),
          'node':'/'.join(path) or 'root','native_id':native_id,'actor':actor,'path':path,'path_labels':path_labels,
          'node_updates':root['visits'],'benchmark':context_data['benchmark'],'seed':data['config']['seed'],
          'seats':seats,'stack_bb':stack,'first_actor':context_data['first_actor'],
          'raise_to_bb':raise_to,'shove_to_bb':shove_to,'reference':context_data['reference'],
          'samples':data['summary']['iterations_completed'],'grid':[13,13],'hands':169,'utility_unit':context_data['utility_unit'],
          'hrc_action_totals':totals[0],'ours_action_totals':totals[1],
          'frequencies_validated':True,'cell_numeric_value':f'raise-to-{raise_to:g}BB frequency percent'}
    from preflop_lab.hrc_research import compare_hands
    meta['comparison'] = compare_hands(hands, {h:hands[h]['reference'] for h in HAND_LABELS},
                                      ev_key='relative_ev' if context_data['utility_unit'] == 'currency' else 'relative_ev_bb')
    meta['largest_raise_frequency_differences'] = sorted(
        [{'hand':h,'hrc_percent':100*p[1],'ours_percent':100*q[1],'delta_pp':100*(q[1]-p[1])}
         for h,p,q in zip(HAND_LABELS,*policies)],key=lambda x:abs(x['delta_pp']),reverse=True)[:8]
    args.output.with_suffix('.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps(meta))


if __name__ == '__main__':
    main()
