"""Seal completed independent runs and produce the user-facing comparison."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_research import HRCResearchSolver, Reference


def module(name, filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('application_result',type=Path)
    args=p.parse_args()
    app=json.loads(args.application_result.read_text(encoding='utf-8'))
    assert app['summary']['status']=='completed' and app['summary']['iterations_completed']==60_000_000
    folder43=Path(app['native_artifacts']['checkpoint_path']).parent
    folder42=ROOT/'.research-cache/benchmarks/nine20bb-seed42'
    run42=json.loads((folder42/'benchmark.json').read_text(encoding='utf-8'))
    assert run42['checkpoints'][-1]['samples']==60_000_000
    benchmark=module('native_benchmark_report','benchmark-hrc-native.py')
    reach=module('native_reference_reach','compare-hrc-reach.py')
    solver=HRCResearchSolver(app['config']);solver.output=folder43
    solver.index=json.loads((folder43/'index.json').read_text())
    solver.reference=Reference(solver.archive)
    comparison43=benchmark.evaluate(solver,True)
    reach42=reach.evaluate(folder42);reach43=reach.evaluate(folder43)
    for folder,result in ((folder42,reach42),(folder43,reach43)):
        (folder/'reference-reach-comparison.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    hu=json.loads((ROOT/'.research-cache/benchmarks/hu10bb-seed42/best-response.json').read_text())
    hashes={str(folder.relative_to(ROOT)):{name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
             for name in ('checkpoint.bin','index.json','manifest.json')} for folder in (folder42,folder43)}
    result={'schema':'native-20bb-final-comparison-v1','generated_utc':datetime.now(timezone.utc).isoformat(),
            'benchmark':'nine20bb','reference_samples':60_000_500,
            'seed42':run42,'seed43':{'samples':60_000_000,'summary':app['summary'],**comparison43},
            'reference_reach':{'seed42':reach42,'seed43':reach43},'hu_best_response':hu,
            'artifact_hashes':hashes,'limitations':run42['limitations']}
    path=ROOT/'reports/hrc-native-20bb-comparison.json'
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    c42=run42['checkpoints'][-1]['root'];c43=comparison43['root']
    lines=['# 九人 20BB：独立原生内核修改与实测','',
           '2026-11-05。两组独立随机种子均从零累计训练 60,000,000 次，对照原版已保存的 60,000,500 次结果。行动树和抽象桶相同；没有把原版策略作为训练初值。','',
           '## 6000 万次的实际结果','',
           '| 根节点 UTG | HRC 原版 | 独立 seed 42 | 独立 seed 43 |','|---|---:|---:|---:|']
    for i,name in enumerate(('弃牌','加注到 2BB','全下')):
        lines.append(f"| {name} | {100*c42['reference_frequency'][i]:.6f}% | {100*c42['ours_frequency'][i]:.6f}% | {100*c43['ours_frequency'][i]:.6f}% |")
    lines += ['', '| 根节点误差 | seed 42 | seed 43 |','|---|---:|---:|',
              f"| 组合加权逐手牌／行动频率 MAE | {c42['frequency_mae_pp']:.6f} 个百分点 | {c43['frequency_mae_pp']:.6f} 个百分点 |",
              f"| 单手牌／行动最大频率差 | {c42['maximum_frequency_error_pp']:.6f} 个百分点 | {c43['maximum_frequency_error_pp']:.6f} 个百分点 |",
              f"| 相对首行动 EV MAE | {c42['relative_ev_mae_bb']:.6f} BB | {c43['relative_ev_mae_bb']:.6f} BB |",'',
              '频率 MAE 是 169 类手牌按 6/4/12 组合数、再对行动取平均的绝对差；不能只用整体开池率之差代替。EV 比较逐手牌相对首行动的历史加权值，不是最终策略的独立自博弈收益。根节点覆盖均为 1326/1326 组合。','',
              '## 同一路径训练的预算变化','',
              '| seed 42 累计样本 | 频率 MAE，百分点 | 相对 EV MAE，BB | 开池率 |',
              '|---:|---:|---:|---:|']
    for c in run42['checkpoints']:
        r=c['root'];lines.append(f"| {c['samples']:,} | {r['frequency_mae_pp']:.6f} | {r['relative_ev_mae_bb']:.6f} | {100*r['ours_frequency'][1]:.6f}% |")
    lines += ['', '## 下游节点与机会到达权重','',
              '全部 1,586 个翻前决策节点逐一对照。节点等权误差会强调极少到达的分支，另以原版平均策略抽样 100,000 手牌，按九人无放回发牌保留弃牌者阻断牌，观察常见路径上的策略分布距离。TV 为同手牌各行动概率绝对差之和的一半。','',
              '| 指标 | seed 42 | seed 43 |','|---|---:|---:|',
              f"| 全部 169 类均有更新的节点 | {run42['checkpoints'][-1]['preflop']['fully_covered_nodes']} / 1586 | {comparison43['preflop']['fully_covered_nodes']} / 1586 |",
              f"| 节点等权平均频率 MAE，百分点 | {run42['checkpoints'][-1]['preflop']['unweighted_mean_node_frequency_mae_pp']:.6f} | {comparison43['preflop']['unweighted_mean_node_frequency_mae_pp']:.6f} |",
              f"| 原版到达分布下，逐决策平均 TV | {100*reach42['reference_reach_mean_total_variation']:.6f}% | {100*reach43['reference_reach_mean_total_variation']:.6f}% |",
              f"| 抽到但独立内核未更新的决策 | {reach42['untrained_decisions']} / {reach42['preflop_decisions']} | {reach43['untrained_decisions']} / {reach43['preflop_decisions']} |",'',
              '这些是条件策略误差和抽样诊断，不是九人可利用度，也不含逐翻后桶的原版误差认证。多人有限样本没有据此获得纳什均衡保证。','',
              '## 修改与验证','',
              '- 新增 v4 向量／标量遍历、探索、跳过更新、局部计数加权、翻后分支及整数筹码终局的独立 C++ 实现。',
              '- 九人 20BB 全 12,193 个节点独立重放守恒；默认格式 23/25 从零训练。',
              '- 116 项 pytest 通过；原始数值探针、30,008 七牌评估、5,400 三街桶样本对照通过。',
              '- 嵌套原始字节码对照：200 案例、3200 逐步快照、136,960 数值完全相同，覆盖多街、target/depth/marker 与 CHECK 特殊分支。',
              '- 网页实际验证九人预览、四街导航、1024 桶、6000 万上限、真实训练、取消保留、刷新恢复及断线自动恢复；严格 UI 审计无错误。',
              f"- 单挑 10BB 原生 6000 万次，独立最佳回应 NashConv 为 {hu['native_profile']['nashconv_bb_per_deal']:.12f} BB/手；仅适用于该单挑模型，机会概率使用本机 2wh 数据。",'',
              '## 尚未证明的范围','',
              '相同预算不能保证整棵树与 HRC 一致。当前导入原版行动树、读取本机桶定义，尚未独立重建全部树生成与抽象训练过程。随机序列、并行交错、界面／保存触发的计数缓存刷新不同；未覆盖所有锁定、格式、收益模型、动态子树和产品功能。','',
              '[完整数值报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-native-20bb-comparison.json) · [内核方法](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-NATIVE-KERNEL.md) · [应用验证](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-native-application-validation.json)','',
              '网页端 seed 43 的完整检查点：`'+str(folder43.relative_to(ROOT))+'`。网页 JSON 导出为根节点与摘要；全节点结果保留在本机检查点。']
    (ROOT/'research/HRC-NATIVE-COMPARISON.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(path),'seed42_root':c42,'seed43_root':c43,
                      'reference_reach_tv':[reach42['reference_reach_mean_total_variation'],reach43['reference_reach_mean_total_variation']]}))


if __name__=='__main__':main()
