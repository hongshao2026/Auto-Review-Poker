"""Read-only, hand-level diagnostics of saved BTN policies and historical EVs.

No training is performed. Original archived values are observations only.
EV differences between separately trained profiles are NOT loss/exploitability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.cards import HAND_LABELS
from preflop_lab.hrc_native import read_node
from preflop_lab.hrc_research import Reference, HRCResearchSolver, decoder
from preflop_lab.hrc_benchmarks import config_for


def need(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def identity(path):
    path = Path(path)
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return {'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': digest}


def weight(hand):
    return 6 if len(hand) == 2 else 4 if hand.endswith('s') else 12


def statistics_of(values):
    values = sorted(values)
    return {'minimum': values[0], 'median': statistics.median(values),
            'maximum': values[-1], 'sum': sum(values)}


def btn_context(benchmark):
    config = config_for(benchmark)
    solver = HRCResearchSolver(config)
    names = [p['name'] for p in config['players']]
    target = names.index('BTN')
    path = []
    node = solver.describe_node(path)
    for actor in range(target):
        need(node['actor'] == actor and not node['terminal'] and node['street'] == 0,
             'Expected sequential preflop opening fold path')
        folds = [a for a in node['actions'] if a['kind'] == 'fold']
        need(len(folds) == 1, 'Missing unique legal fold')
        path.append(folds[0]['id'])
        node = solver.describe_node(path)
    need(node['actor'] == target and node['actor_name'] == 'BTN' and sum(node['folded']) == target,
         'Fold path did not reach BTN')
    need([a['kind'] for a in node['actions']] == ['fold', 'raise', 'allin'], 'Unexpected BTN action order')
    return {'benchmark': benchmark, 'node_id': node['native_id'], 'path': path, 'actor': target,
            'actions': node['actions'], 'players': names, 'tree_provenance': solver.tree.provenance}


def load_original(path, context, label):
    ref = Reference(path)
    target_path = 'root/' + '/'.join(context['path'])
    node_id = next(i for i, n in ref.nodes.items() if n['path'] == target_path)
    root_id = next(i for i, n in ref.nodes.items() if n['parent_id'] == -1)
    node = ref.nodes[node_id]
    need(node['street'] == 0 and node['actor'] == context['actor'], 'Original BTN identity mismatch')
    decoded = ref.decoder.decode_storage(ref.records[node_id], node)
    root = ref.decoder.decode_storage(ref.records[root_id], ref.nodes[root_id])
    with zipfile.ZipFile(path) as z:
        settings_hash = hashlib.sha256(z.read('settings.json')).hexdigest()
    canonical_tree = [{**{key:n[key] for key in ('path','kind','street','actor','incoming_actions')},
                       'children':[ref.nodes[i]['path'] if i != -1 else None for i in n['child_ids']]}
                      for n in sorted(ref.nodes.values(),key=lambda n:n['path'])]
    topology_hash = hashlib.sha256(json.dumps(canonical_tree,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    hands = ref.node(node_id)
    denominators = [r['weighted_denominator'] for r in decoded['buckets']]
    return {'label': label, 'hands': hands, 'source': identity(path),
            'node_id': node_id, 'path': context['path'], 'settings_sha256': settings_hash,
            'topology_canonical_sha256': topology_hash, 'selected_node_locked_actions':decoded.get('locked_actions'),
            'counts': {'saved_root_counter_float32': root['saved_counter_float32'],
                       'saved_btn_counter_float32': decoded['saved_counter_float32'],
                       'positive_average_buckets': decoded['positive_average_buckets'],
                       'weighted_EV_denominator': statistics_of(denominators),
                       'per_hand_actual_visits': None,
                       'semantics': 'Original root/BTN counters are float32 saved update snapshots. The weighted EV denominator is not a hand visit count; exact per-hand visit counts are absent.'}}


def load_native(folder, context, label, expected_seed=None):
    folder = Path(folder)
    index, summary, manifest = [read_json(folder / name) for name in ('index.json', 'summary.json', 'manifest.json')]
    need(summary['iteration'] == 60_000_000 and not summary['cancelled'], 'Expected completed 60m checkpoint')
    need(summary.get('mode')=='v4', 'Expected the existing v4 benchmark kernel mode')
    if expected_seed is not None:
        need(summary['seed'] == expected_seed, 'Checkpoint seed mismatch')
    record = read_node(folder, context['node_id'], index=index)
    need(record['actor'] == context['actor'] and record['street'] == 0 and record['buckets'] == 169
         and record['actions'] == 3, 'Checkpoint BTN shape mismatch')
    for key in ('settings_sha256', 'gametree_sha256'):
        need(manifest['topology_source'][key] == context['tree_provenance'][key], 'Checkpoint topology identity mismatch')
    labels = decoder().HAND_LABELS
    hands = {labels[r['bucket']]: {'frequencies': r['display_strategy'],
                                  'relative_ev_bb': r['relative_ev_to_action0'], 'visits': r['visits']}
             for r in record['hands']}
    visits = [r['visits'] for r in record['hands']]
    need(sum(visits) == record['updates'], 'Per-hand visits do not sum to BTN updates')
    with (folder/'checkpoint.bin').open('rb') as f:
        f.seek(record['raw_offset']); cached_counter, = struct.unpack('<d', f.read(8))
    return {'label': label, 'hands': hands, 'source': identity(folder/'checkpoint.bin'),
            'summary_source': identity(folder/'summary.json'), 'index_source': identity(folder/'index.json'),
            'seed': summary['seed'], 'resumed': summary.get('resumed'), 'tree_sha256': manifest['tree_sha256'],
            'algorithm':index.get('algorithm'), 'mode':summary.get('mode'),
            'node_id': context['node_id'], 'path': context['path'],
            'counts': {'iterations': summary['iteration'], 'btn_updates_uint64': record['updates'],
                       'cached_numeric_counter_double': cached_counter, 'per_hand_actual_visits': statistics_of(visits),
                       'visited_hands': sum(v > 0 for v in visits),
                       'semantics': 'Native global iterations, true BTN update total and uint64 hand visits are separate. The raw cached numeric counter can lag the true BTN update total.'}}


def policy_rows(profile):
    need(set(profile['hands']) == set(HAND_LABELS), 'Expected all 169 hands')
    for h in HAND_LABELS:
        row = profile['hands'][h]
        p, e = row['frequencies'], row['relative_ev_bb']
        need(len(p) == 3 and all(math.isfinite(x) and x >= 0 for x in p)
             and abs(sum(p)-1) < 1e-9, 'Invalid probabilities')
        need(e is not None and len(e) == 3 and all(math.isfinite(x) for x in e), 'Missing finite relative EV')
        need(abs(e[0]) < 1e-12, 'Expected action0-relative EV baseline')


def compare_profiles(baseline, candidate, actions):
    policy_rows(baseline); policy_rows(candidate)
    action_names = ['fold', f"raise_{actions[1]['amount']:g}bb", f"shove_{actions[2]['amount']:g}bb"]
    rows = []
    total_baseline = [0., 0., 0.]; total_candidate = [0., 0., 0.]
    for hand in HAND_LABELS:
        a, b = baseline['hands'][hand], candidate['hands'][hand]
        p, q = a['frequencies'], b['frequencies']
        ev_a, ev_b = a['relative_ev_bb'], b['relative_ev_bb']
        delta = [y-x for x,y in zip(p,q)]
        w = weight(hand)/1326
        tv = sum(abs(x) for x in delta)/2
        fold_continue = abs(delta[0])
        internal = max(0., tv-fold_continue)
        # This is the exact TV loss from coarsening raise+shove into continue.
        opposite_internal = min(abs(delta[1]),abs(delta[2])) if delta[1]*delta[2] < 0 else 0.
        need(abs(internal-opposite_internal) < 1e-12, 'TV decomposition failed')
        order_a = sorted(range(3), key=lambda i: ev_a[i], reverse=True)
        order_b = sorted(range(3), key=lambda i: ev_b[i], reverse=True)
        gap_a = ev_a[order_a[0]]-ev_a[order_a[1]]
        gap_b = ev_b[order_b[0]]-ev_b[order_b[1]]
        for i in range(3):
            total_baseline[i] += w*p[i]; total_candidate[i] += w*q[i]
        rows.append({'hand': hand, 'combos': weight(hand), 'baseline_probability': p, 'candidate_probability': q,
                     'delta_pp': [100*x for x in delta], 'tv_pp': 100*tv,
                     'mean_action_absolute_error_pp': 100*sum(abs(x) for x in delta)/3,
                     'weighted_TV_contribution_pp': 100*w*tv,
                     'baseline_native_hand_visits': a.get('visits'), 'candidate_native_hand_visits': b.get('visits'),
                     'fold_continue_tv_pp': 100*fold_continue, 'raise_shove_internal_tv_pp': 100*internal,
                     'baseline_relative_ev_bb': ev_a, 'candidate_relative_ev_bb': ev_b,
                     'ev_difference_bb': [y-x for x,y in zip(ev_a,ev_b)],
                     'baseline_ev_order': [action_names[i] for i in order_a],
                     'candidate_ev_order': [action_names[i] for i in order_b],
                     'baseline_best_ev_margin_bb': gap_a, 'candidate_best_ev_margin_bb': gap_b,
                     'ev_best_action_changed': order_a[0] != order_b[0],
                     'ev_best_action_changed_both_margins_over_0_01bb': order_a[0] != order_b[0] and min(gap_a,gap_b) > .01,
                     'raise_minus_shove_ev_bb': {'baseline': ev_a[1]-ev_a[2], 'candidate': ev_b[1]-ev_b[2]},
                     'raise_shove_ev_order_flipped': (ev_a[1]-ev_a[2])*(ev_b[1]-ev_b[2]) < 0,
                     'continue_best_ev_sign_flipped': max(ev_a[1:])*max(ev_b[1:]) < 0,
                     'baseline_modal_action': action_names[max(range(3),key=p.__getitem__)],
                     'candidate_modal_action': action_names[max(range(3),key=q.__getitem__)]})
    weighted = lambda key: sum(r['combos']*r[key] for r in rows)/1326
    tv = weighted('tv_pp')
    aggregate_delta = [100*(y-x) for x,y in zip(total_baseline,total_candidate)]
    aggregate_tv = sum(abs(x) for x in aggregate_delta)/2
    per_action_abs = [sum(r['combos']*abs(r['delta_pp'][i]) for r in rows)/1326 for i in range(3)]
    per_action_cancellation=[]
    for i,name in enumerate(action_names):
        positive=sum(r['combos']*max(r['delta_pp'][i],0) for r in rows)/1326
        negative=sum(r['combos']*max(-r['delta_pp'][i],0) for r in rows)/1326
        per_action_cancellation.append({'action':name,'weighted_positive_changes_pp':positive,
                                        'weighted_negative_changes_pp':negative,
                                        'mean_absolute_change_pp':positive+negative,
                                        'absolute_aggregate_change_pp':abs(positive-negative),
                                        'fraction_cancelled':2*min(positive,negative)/(positive+negative) if positive+negative else None})
    shove_to_raise=sum(r['combos']*r['raise_shove_internal_tv_pp'] for r in rows if r['delta_pp'][1]>0)/1326
    raise_to_shove=sum(r['combos']*r['raise_shove_internal_tv_pp'] for r in rows if r['delta_pp'][1]<0)/1326
    need(abs(shove_to_raise+raise_to_shove-weighted('raise_shove_internal_tv_pp'))<1e-10,'Directional internal TV mismatch')
    need(tv+1e-10 >= aggregate_tv, 'Aggregation increased total variation')
    flips = {}
    for key in ('ev_best_action_changed','ev_best_action_changed_both_margins_over_0_01bb',
                'raise_shove_ev_order_flipped','continue_best_ev_sign_flipped'):
        chosen = [r for r in rows if r[key]]
        flips[key] = {'hand_classes':len(chosen),'combos':sum(r['combos'] for r in chosen),
                      'combo_percent':100*sum(r['combos'] for r in chosen)/1326,
                      'hands':[r['hand'] for r in chosen]}
    exchanges = [r for r in rows if r['raise_shove_internal_tv_pp'] > 1e-9]
    ev_mae_by_action = [sum(r['combos']*abs(r['ev_difference_bb'][i]) for r in rows)/1326 for i in range(3)]
    return {'baseline':baseline['label'], 'candidate':candidate['label'], 'action_order':action_names,
            'weighting':'Uniform 1326 hole combinations (6/4/12 per class), NOT reach-conditioned weights or a nine/eight-player joint sampling distribution.',
            'aggregate':{'baseline_frequency':total_baseline,'candidate_frequency':total_candidate,
                         'delta_pp':aggregate_delta,'TV_pp':aggregate_tv},
            'hand_level':{'combo_weighted_TV_pp':tv,
                          'combo_weighted_mean_action_MAE_pp':weighted('mean_action_absolute_error_pp'),
                          'combo_weighted_absolute_difference_by_action_pp':per_action_abs,
                          'fold_continue_TV_pp':weighted('fold_continue_tv_pp'),
                          'raise_shove_internal_TV_pp':weighted('raise_shove_internal_tv_pp'),
                          'minimum_within_continue_reallocation_pp':{'shove_to_raise':shove_to_raise,'raise_to_shove':raise_to_shove},
                          'raise_shove_internal_share_of_TV':weighted('raise_shove_internal_tv_pp')/tv if tv else None,
                          'raise_shove_opposed_change_classes':len(exchanges),
                          'maximum_hand_TV_pp':max(r['tv_pp'] for r in rows),
                          'maximum_action_error_pp':max(abs(v) for r in rows for v in r['delta_pp']),
                          'class_TV_thresholds':{str(t):{'classes':sum(r['tv_pp']>=t for r in rows),
                                                     'combo_percent':100*sum(r['combos'] for r in rows if r['tv_pp']>=t)/1326}
                                                 for t in (5,10,25,50)}},
            'aggregate_cancellation':{'hidden_TV_pp':tv-aggregate_tv,
                                      'fraction_of_hand_TV_cancelled':1-aggregate_tv/tv if tv else None,
                                      'hand_TV_divided_by_aggregate_TV':tv/aggregate_tv if aggregate_tv else None,
                                      'by_action':per_action_cancellation,
                                      'definition':'Hand-weighted TV minus TV of aggregate action frequencies; measures cancellation of signed hand changes, not lost EV.'},
            'EV_diagnostics':{'nonfold_action_weighted_MAE_bb':sum(ev_mae_by_action[1:])/2,
                              'weighted_MAE_by_action_bb':ev_mae_by_action,
                              'ordering_flips':flips,
                              'interpretation':'Separate profiles have different opponent/reach policies and historical averaging. Cross-profile EV differences or rank flips are descriptive, not deviation loss, BR value, NashConv or exploitability; a 0.01BB margin is a descriptive filter, not statistical significance.'},
            'top_15_by_hand_TV':sorted(rows,key=lambda r:r['tv_pp'],reverse=True)[:15],
            'top_15_by_weighted_TV_contribution':sorted(rows,key=lambda r:r['weighted_TV_contribution_pp'],reverse=True)[:15],
            'all_169_hands':rows}


def mathematical_checks():
    # Aggregation can hide all changes, and coarse TV plus internal TV is exact.
    p=[[1.,0.,0.],[0.,1.,0.]];q=list(reversed(p))
    tv=sum(sum(abs(a-b) for a,b in zip(x,y))/2 for x,y in zip(p,q))/2
    aggregate=sum(abs(sum(x[i] for x in p)/2-sum(x[i] for x in q)/2) for i in range(3))/2
    need(tv==1 and aggregate==0, 'Cancellation fixture failed')
    for p,q,expected in [([.5,.4,.1],[.5,.1,.4],(0.,.3)),([.5,.4,.1],[.2,.7,.1],(.3,0.))]:
        d=[b-a for a,b in zip(p,q)];v=sum(abs(x) for x in d)/2
        need(abs(abs(d[0])-expected[0])<1e-12 and abs(v-abs(d[0])-expected[1])<1e-12,'TV component fixture failed')
    return {'aggregation_cancellation_fixture':True,'TV_coarsening_decomposition_fixtures':True}


def profile_metadata(profile):
    return {k:v for k,v in profile.items() if k!='hands'}


def load_snapshot(path, context, expected_samples, original):
    data=read_json(path)
    need(data['seed']==44 and data['samples']==expected_samples,'Seed44 snapshot identity mismatch')
    candidates=[n for n in data['nodes'].values() if n.get('path')==context['path']]
    need(len(candidates)==1,'Expected one BTN snapshot')
    node=candidates[0]; strategy=node['strategy']; hands=strategy['hands']
    need(node['actor_name']=='BTN' and node['native_id']==context['node_id'] and node['street']==0,'Snapshot BTN mismatch')
    need(node['actions']==context['actions'],'Snapshot actions differ')
    for hand in HAND_LABELS:
        need(hands[hand]['reference']==original['hands'][hand],'Snapshot reference differs from archived final HRC')
    visits=[h['visits'] for h in hands.values()]
    need(sum(visits)==strategy['visits'],'Snapshot per-hand visits do not sum to BTN updates')
    return {'label':f'eight15bb native seed44 {expected_samples//1000000}m','hands':hands,
            'source':identity(path),'seed':44,'node_id':node['native_id'],'path':node['path'],
            'counts':{'iterations':expected_samples,'btn_updates_uint64':strategy['visits'],
                      'per_hand_actual_visits':statistics_of(visits),'visited_hands':sum(v>0 for v in visits),
                      'semantics':'Native checkpoint-derived stage snapshot; actual visit counts retained, cached raw numerical counter not included in this JSON.'}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eight-result',type=Path,default=ROOT/'.runs/e0873922bdca438ba02e226571cf3569.json')
    parser.add_argument('--eight-btn-node',type=Path,default=ROOT/'reports/hrc-native-eight15bb-btn-node.json')
    parser.add_argument('--extra-eight-result',type=Path,action='append',default=[])
    parser.add_argument('--extra-eight-checkpoint-dir',type=Path,action='append',default=[])
    parser.add_argument('--seed44-diagnostic-dir',type=Path,
                        default=ROOT/'analysis/hrc-native/eight15bb-seed44-diagnostic')
    parser.add_argument('--nine-seed42-dir',type=Path,default=ROOT/'.research-cache/benchmarks/nine20bb-seed42')
    parser.add_argument('--nine-seed43-dir',type=Path,default=ROOT/'.research-cache/runs/84462222814742d895aaec23f9026496')
    parser.add_argument('--output',type=Path,default=ROOT/'reports/hrc-native-strategy-difference-diagnostics.json')
    args=parser.parse_args()
    checks=mathematical_checks()
    eight,nine=btn_context('eight15bb'),btn_context('nine20bb')
    initial=load_original(ROOT/'analysis/hrc-desktop/eight15bb-raise-call-postflop-initial.hrcz',eight,'eight15bb HRC initial')
    final=load_original(ROOT/'analysis/hrc-desktop/eight15bb-raise-call-postflop-60m.hrcz',eight,'eight15bb HRC final')
    need(initial['settings_sha256']==final['settings_sha256'],'Original initial/final settings differ')
    need(initial['topology_canonical_sha256']==final['topology_canonical_sha256'],'Original initial/final topology differs')
    need(initial['selected_node_locked_actions']==final['selected_node_locked_actions'],'Original BTN locks differ')
    app=read_json(args.eight_result); export=read_json(args.eight_btn_node)
    need(app['config']['benchmark']=='eight15bb' and app['summary']['status']=='completed','Expected completed eight-seat result')
    ours=load_native(Path(app['native_artifacts']['checkpoint_path']).parent,eight,
                     f"eight15bb native seed{app['config']['seed']}",app['config']['seed'])
    need(export['path']==eight['path'] and export['actor_name']=='BTN','Exported BTN path mismatch')
    for h in HAND_LABELS:
        need(export['strategy']['hands'][h]['frequencies']==ours['hands'][h]['frequencies'],'BTN export/checkpoint probability mismatch')
        need(export['strategy']['hands'][h]['relative_ev_bb']==ours['hands'][h]['relative_ev_bb'],'BTN export/checkpoint EV mismatch')
        need(export['strategy']['hands'][h]['reference']==final['hands'][h],'BTN export/original reference mismatch')
    profiles={'eight_initial':initial,'eight_final':final,'eight_native':ours}
    comparisons={'eight15bb_native_vs_HRC60m':compare_profiles(final,ours,eight['actions']),
                 'eight15bb_HRC_initial_to60m':compare_profiles(initial,final,eight['actions'])}
    seed44_status={'available':False,'directory':str(args.seed44_diagnostic_dir)}
    selected_table=None
    if (args.seed44_diagnostic_dir/'seed-comparison.json').exists():
        controlled=read_json(args.seed44_diagnostic_dir/'seed-comparison.json')
        need(controlled['status']=='completed' and controlled['seed']==44 and controlled['benchmark']=='eight15bb',
             'Seed44 controlled run is not complete')
        native44=load_native(args.seed44_diagnostic_dir,eight,'eight15bb native seed44 60m',44)
        stages={budget:load_snapshot(args.seed44_diagnostic_dir/f'nodes-{budget}.json',eight,budget,final)
                for budget in (10_000_000,30_000_000,60_000_000)}
        for hand in HAND_LABELS:
            for field in ('frequencies','relative_ev_bb','visits'):
                need(stages[60_000_000]['hands'][hand][field]==native44['hands'][hand][field],
                     'Seed44 final snapshot differs from final checkpoint')
        need(ours['seed']==43,'The controlled comparison expects original native seed43')
        profiles['eight_native44']=native44
        profiles.update({f'eight_native44_{n//1000000}m':p for n,p in stages.items()})
        comparisons['eight15bb_seed43_to_seed44']=compare_profiles(ours,native44,eight['actions'])
        comparisons['eight15bb_seed44_vs_HRC60m']=compare_profiles(final,native44,eight['actions'])
        for a,b in ((10_000_000,30_000_000),(30_000_000,60_000_000),(10_000_000,60_000_000)):
            comparisons[f'eight15bb_seed44_{a//1000000}m_to{b//1000000}m']=compare_profiles(stages[a],stages[b],eight['actions'])
        seed44_status.update(available=True,report=identity(args.seed44_diagnostic_dir/'seed-comparison.json'),
                             stage_budgets=controlled['stage_budgets'],segmentation=controlled['segmentation'],
                             baseline_and_frozen_sources_unchanged=controlled['baseline_and_frozen_sources_unchanged'],
                             final_snapshot_matches_checkpoint=True,
                             qualification='Two observed 60m seeds demonstrate observed seed sensitivity, not a confidence interval; they cannot exclude a shared implementation bug or establish equilibrium equivalence.')
        selected_table={'action':'all-in to 15BB','units':'percent of each hand class, not conditional reach',
                        'columns':['HRC60m','native43_60m','native44_60m'],
                        'rows':[{'hand':h,'HRC60m':100*final['hands'][h]['frequencies'][2],
                                 'native43_60m':100*ours['hands'][h]['frequencies'][2],
                                 'native44_60m':100*native44['hands'][h]['frequencies'][2]}
                                for h in ('A6s','A2s','QTs','55')]}
    nine_status={'available':False,'searched_paths':[str(args.nine_seed42_dir),str(args.nine_seed43_dir)]}
    if all((p/'checkpoint.bin').exists() for p in (args.nine_seed42_dir,args.nine_seed43_dir)):
        a=load_native(args.nine_seed42_dir,nine,'nine20bb native seed42',42)
        b=load_native(args.nine_seed43_dir,nine,'nine20bb native seed43',43)
        need(a['tree_sha256']==b['tree_sha256'],'Nine-seat checkpoint trees differ')
        hrc=load_original(ROOT/'analysis/hrc-desktop/nine20bb-raise-call-postflop-60m.hrcz',nine,'nine20bb HRC final')
        profiles.update(nine_native42=a,nine_native43=b,nine_final=hrc)
        comparisons.update(nine20bb_seed42_to_seed43=compare_profiles(a,b,nine['actions']),
                           nine20bb_seed42_vs_HRC60m=compare_profiles(hrc,a,nine['actions']),
                           nine20bb_seed43_vs_HRC60m=compare_profiles(hrc,b,nine['actions']))
        nine_status.update(available=True,meaning='Two existing 60m checkpoints; seed42 is resumed, seed43 is one run. Native resume restores saved RNG state, but two seeds are not a confidence interval or an eight-seat noise bound.')
    extra_folders=[]
    for extra_path in args.extra_eight_result:
        extra=read_json(extra_path);seed=extra['config']['seed']
        need(extra['config']['benchmark']=='eight15bb' and extra['summary']['status']=='completed','Invalid additional eight-seat result')
        extra_folders.append((Path(extra['native_artifacts']['checkpoint_path']).parent,seed))
    for folder in args.extra_eight_checkpoint_dir:
        extra_folders.append((folder,read_json(folder/'summary.json')['seed']))
    for folder,seed in extra_folders:
        p=load_native(folder,eight,f'eight15bb native additional seed{seed}',seed)
        key=f'eight_extra_seed{seed}'
        need(key not in profiles,'Duplicate extra seed')
        profiles[key]=p
        comparisons[f'eight15bb_additional_seed{seed}_vs_HRC60m']=compare_profiles(final,p,eight['actions'])
        comparisons[f'eight15bb_native_to_additional_seed{seed}']=compare_profiles(ours,p,eight['actions'])
    report={'schema':'saved-policy-difference-diagnostics-v1','source_script':identity(Path(__file__)),
            'input_application_result':identity(args.eight_result),'input_btn_export':identity(args.eight_btn_node),
            'training_performed':False,'mathematical_checks':checks,'contexts':{'eight15bb':eight,'nine20bb':nine},
            'eight_original_progression':{
                'saved_root_update_delta':final['counts']['saved_root_counter_float32']-initial['counts']['saved_root_counter_float32'],
                'saved_BTN_update_delta':final['counts']['saved_btn_counter_float32']-initial['counts']['saved_btn_counter_float32'],
                'trajectory':'One original run continued from initial archive to final archive, not two independent original seeds.',
                'nominal_labels':'Initial about10m, final about60m; exact observed counters are listed per profile.'},
            'profiles':{k:profile_metadata(v) for k,v in profiles.items()},'nine_seed_availability':nine_status,
            'eight_seed44_controlled_diagnostic':seed44_status,'selected_allin_percent_table':selected_table,
            'comparisons':comparisons,
            'limitations':['Weights are uniform 1326 combinations at BTN, not actual reach, blocker-conditioned range or strategic importance weights.',
                           'Historical action EV estimates come from changing and different strategy environments. Their difference does not measure loss/exploitability.',
                           'Original initial-to-final is additional training on one evolving trajectory, not independent replications.',
                           'Two native seeds in an observed benchmark quantify only those outcomes, not a variance distribution, confidence interval, convergence or equilibrium equivalence. A shared implementation bug is not excluded.',
                           'Root sample/update counts, selected-node update counts, true native per-hand visits and weighted EV denominators have different semantics.',
                           'Original float32 saved counters may round large values. A nominal 60m budget does not imply equal BTN visits or identical sampling efficiency.']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    concise={k:{'aggregate_TV_pp':v['aggregate']['TV_pp'],'weighted_hand_TV_pp':v['hand_level']['combo_weighted_TV_pp'],
                'mean_action_MAE_pp':v['hand_level']['combo_weighted_mean_action_MAE_pp'],
                'fold_continue_TV_pp':v['hand_level']['fold_continue_TV_pp'],
                'raise_shove_internal_TV_pp':v['hand_level']['raise_shove_internal_TV_pp'],
                'cancellation_fraction':v['aggregate_cancellation']['fraction_of_hand_TV_cancelled'],
                'nonfold_EV_MAE_bb':v['EV_diagnostics']['nonfold_action_weighted_MAE_bb']}
             for k,v in comparisons.items()}
    print(json.dumps({'output':str(args.output.resolve()),'comparisons':concise},indent=2))


if __name__=='__main__':
    main()
