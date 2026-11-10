"""Read-only monetary PKO comparison; no solver/training invocation."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.cards import HAND_LABELS

spec = importlib.util.spec_from_file_location('pko_plot', ROOT / 'scripts/plot-hrc-strategy-comparison.py')
plot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plot)


def identity(path):
    path = Path(path)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': digest}


def compare(context):
    hands = context['strategy']['hands']
    rows = []
    for label in HAND_LABELS:
        row = hands[label]
        p, q = row['reference']['frequencies'], row['frequencies']
        ep, eq = row['reference']['relative_ev'], row['relative_ev']
        assert len(p) == len(q) == len(ep) == len(eq) == 3
        assert row['visits'] > 0 and abs(sum(p)-1) < 1e-9 and abs(sum(q)-1) < 1e-9
        assert all(math.isfinite(x) for x in [*p, *q, *ep, *eq])
        delta = [b-a for a, b in zip(p, q)]
        tv = sum(abs(x) for x in delta)/2
        fold_continue = abs(delta[0])
        internal = min(abs(delta[1]), abs(delta[2])) if delta[1]*delta[2] < 0 else 0
        assert abs(tv-fold_continue-internal) < 1e-10
        rows.append({'hand': label, 'combos': 6 if len(label) == 2 else 4 if label.endswith('s') else 12,
                     'hrc_frequency': p, 'ours_frequency': q, 'delta_pp': [100*x for x in delta],
                     'TV_pp': tv*100, 'fold_continue_TV_pp': fold_continue*100,
                     'raise_shove_exchange_TV_pp': internal*100, 'ours_visits': row['visits'],
                     'hrc_relative_EV_currency': ep, 'ours_relative_EV_currency': eq,
                     'hrc_best_historical_EV_action': max(range(3), key=ep.__getitem__),
                     'ours_best_historical_EV_action': max(range(3), key=eq.__getitem__)})
    weighted = lambda values: sum(r['combos']*v for r, v in zip(rows, values))/1326
    aggregate_p = [weighted([r['hrc_frequency'][i] for r in rows]) for i in range(3)]
    aggregate_q = [weighted([r['ours_frequency'][i] for r in rows]) for i in range(3)]
    aggregate_tv = 50*sum(abs(a-b) for a, b in zip(aggregate_p, aggregate_q))
    tv = weighted([r['TV_pp'] for r in rows])
    return {'actor': context['actor'], 'node_id': context['native_id'], 'path': context['path'],
            'action_order': ['fold', 'raise_2BB', 'shove_15BB'], 'utility_unit': 'currency',
            'reference_counts': context['reference'], 'ours_node_updates': context['strategy']['visits'],
            'ours_per_hand_visits_min_max': [min(r['ours_visits'] for r in rows), max(r['ours_visits'] for r in rows)],
            'hrc_aggregate_frequency': aggregate_p, 'ours_aggregate_frequency': aggregate_q,
            'aggregate_TV_pp': aggregate_tv, 'combo_weighted_hand_TV_pp': tv,
            'combo_weighted_action_MAE_pp': tv*2/3,
            'fold_continue_TV_pp': weighted([r['fold_continue_TV_pp'] for r in rows]),
            'raise_shove_exchange_TV_pp': weighted([r['raise_shove_exchange_TV_pp'] for r in rows]),
            'fraction_hand_TV_hidden_by_aggregation': 1-aggregate_tv/tv,
            'relative_EV_currency_MAE_nonfold': weighted([sum(abs(a-b) for a,b in zip(r['hrc_relative_EV_currency'][1:],r['ours_relative_EV_currency'][1:]))/2 for r in rows]),
            'best_historical_EV_action_flip_classes': sum(r['hrc_best_historical_EV_action'] != r['ours_best_historical_EV_action'] for r in rows),
            'top_hand_TV': sorted(rows, key=lambda r:r['TV_pp'], reverse=True)[:15], 'hands': rows}


def main():
    source = ROOT / '.runs/dda8d9d18fc8468d8ddbe82dc6cdb944.json'
    data = json.loads(source.read_text(encoding='utf-8'))
    root_context, btn_context = [plot.load_comparison(data, btn) for btn in (False, True)]
    assert btn_context['native_id'] == 5 and btn_context['path'] == ['0']*5
    root, btn = compare(root_context), compare(btn_context)
    aa = next(r for r in root['hands'] if r['hand'] == 'AA')
    assert abs(aa['hrc_relative_EV_currency'][1] - 7.8869430314) < 1e-9
    assert abs(aa['ours_relative_EV_currency'][1] - 7.8384689989) < 1e-9
    archive = Path(root_context['reference']['archive'])
    with zipfile.ZipFile(archive) as z:
        settings = json.loads(z.read('settings.json'))
    pool = sum(data['config']['payouts']) + sum(data['config']['bounty']['amounts'])
    assert pool == 180
    report = {'purpose': 'Same-configuration saved PKO profile comparison; no new training',
              'source': identity(source), 'checkpoint': identity(data['native_artifacts']['checkpoint_path']),
              'reference_archive': identity(archive), 'config': data['config'], 'reference_engine_profiles': settings['engine'],
              'tree_equality_evidence': 'reports/hrc-pko-tree-identity-validation.json',
              'counts': {'ours_iterations': 60000000, 'original_saved_root_counter': root_context['reference']['samples'],
                         'note': 'Original counter is a float32 saved snapshot, not exact per-hand visits. Native visits are uint64 update counts. No CI or convergence claim.'},
              'unit': {'raw_EV': 'payout currency units relative to action 0 (fold)', 'gui_percent': '100 * raw_currency / 180',
                       'total_prizes_plus_bounties': pool, 'root_AA_hrc_raise_gui_percent': aa['hrc_relative_EV_currency'][1]*100/pool},
              'weighting': 'Uniform 1326 hole-card combinations, 6/4/12 per class, not reach-conditioned frequencies',
              'limitation': 'Cross-profile historical EV differences are not loss, best-response gap or exploitability. One seed and finite budgets do not certify equilibrium or exclude shared implementation error.',
              'root': root, 'btn': btn}
    output = ROOT / 'reports/hrc-eight15bb-pko-60m-comparison.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    selected = [next(r for r in btn['hands'] if r['hand'] == label) for label in ('AA','A6s','A2s','QTs','55','K3s','A7s')]
    fmtp = lambda xs: ' / '.join(f'{x*100:.3f}%' for x in xs)
    fmte = lambda xs: ' / '.join(f'{x:.4f}' for x in xs)
    lines = [
        '# 八人 15BB ICM PKO：原版与独立内核 60m 对照', '',
        '**已完成同配置实际训练对照，但逐手牌策略仍有明显差异，不能宣布数值等价。** 原版保存根计数为60,000,500，独立内核seed43完成60,000,000。八人均15BB，盲注0.5/1、无ante；奖金50/30/20、每人完整赏金10、即时支付50%，无外桌。', '',
        '两份存档的物理树记录顺序不同，但4786个节点、完整行动（含强制尾行动）、重放状态、结算输入与special标记逐项一致。对应引擎/profile/treeconfig也一致；[树身份报告](../reports/hrc-pko-tree-identity-validation.json)保留两份原档SHA和规范化哈希。', '',
        '## 相同量纲与口径', '',
        f'原版raw EV是奖金金额，相对fold为0；GUI按总奖池与头上赏金180显示百分比，即100×金额/180。根AA加注EV原版{aa["hrc_relative_EV_currency"][1]:.10f}、独立{aa["ours_relative_EV_currency"][1]:.10f}，原版GUI约{report["unit"]["root_AA_hrc_raise_gui_percent"]:.4f}%。这里不把它除以BB，也不把GUI百分比当金额。', '',
        '以下频率均按169类的6/4/12组合权重汇总，不是条件于其他玩家弃牌后真实到达分布。BTN路径按合法fold边到达节点5，前五人均弃牌。', '',
        '| 节点 | 原版 fold / raise2BB / shove15BB | 独立 fold / raise2BB / shove15BB | 逐行动MAE pp | 逐手TV pp | 非fold EV MAE（金額） |',
        '|---|---|---|---:|---:|---:|',
    ]
    for r in (root,btn):
        lines.append(f'| {r["actor"]} | {fmtp(r["hrc_aggregate_frequency"])} | {fmtp(r["ours_aggregate_frequency"])} | {r["combo_weighted_action_MAE_pp"]:.4f} | {r["combo_weighted_hand_TV_pp"]:.4f} | {r["relative_EV_currency_MAE_nonfold"]:.6f} |')
    lines += ['', f'BTN总体行动频率的TV仅{btn["aggregate_TV_pp"]:.4f} pp，逐手TV为{btn["combo_weighted_hand_TV_pp"]:.4f} pp；汇总抵消了{100*btn["fraction_hand_TV_hidden_by_aggregation"]:.2f}%的逐手差异。逐手fold/continue部分为{btn["fold_continue_TV_pp"]:.4f} pp，raise/shove内部互换为{btn["raise_shove_exchange_TV_pp"]:.4f} pp。总体开池率接近不能代表每类手牌接近。', '',
              '## BTN逐手牌例子', '', '| 手牌 | 原版 fold / raise / shove | 独立 fold / raise / shove | 原版相对EV（金额） | 独立相对EV（金额） |', '|---|---|---|---|---|']
    for r in selected:
        lines.append(f'| {r["hand"]} | {fmtp(r["hrc_frequency"])} | {fmtp(r["ours_frequency"])} | {fmte(r["hrc_relative_EV_currency"])} | {fmte(r["ours_relative_EV_currency"])} |')
    lines += ['', f'原版BTN保存更新计数{btn["reference_counts"]["selected_node_counter_float32"]:,.0f}，独立BTN更新{btn["ours_node_updates"]:,}；独立每类访问范围{btn["ours_per_hand_visits_min_max"][0]:,}–{btn["ours_per_hand_visits_min_max"][1]:,}。原版保存的加权EV分母不是实际手牌访问数，不将其冒充可直接比较的样本计数。', '',
              '**解释边界：** 两份策略对应不同对手策略与历史平均轨迹，EV差或排序翻转只是描述，不能当作策略损失、最佳回应差距或可利用度。当前仅一个独立种子、有限预算，未估计置信区间，也不能排除共同实现误差。该对照不证明其他锦标赛配置、MTT、FGS或锁功能已经对齐。', '',
              '## 可复核产物', '',
              '- [完整169手JSON](../reports/hrc-eight15bb-pko-60m-comparison.json)',
              '- [BTN对照图](../reports/figures/hrc-eight15bb-pko-btn-60m-comparison.png) · [SVG](../reports/figures/hrc-eight15bb-pko-btn-60m-comparison.svg) · [CSV](../reports/figures/hrc-eight15bb-pko-btn-60m-comparison.csv)',
              '- [根节点对照图](../reports/figures/hrc-eight15bb-pko-root-60m-comparison.png)',
              '- [生成诊断脚本](../scripts/compare-hrc-pko-60m.py)；图由原绘图工具新增货币参考支持生成，旧ChipEV图未覆盖。', '']
    (ROOT / 'research/HRC-8MAX-15BB-PKO.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'output': str(output), 'root_MAE_pp': root['combo_weighted_action_MAE_pp'],
                      'BTN_MAE_pp': btn['combo_weighted_action_MAE_pp'], 'BTN_TV_pp':btn['combo_weighted_hand_TV_pp'],
                      'BTN_fold_continue_pp':btn['fold_continue_TV_pp'], 'BTN_raise_shove_pp':btn['raise_shove_exchange_TV_pp'],
                      'BTN_hidden_percent':100*btn['fraction_hand_TV_hidden_by_aggregation']}))


if __name__ == '__main__':
    main()
