"""Collect measured shared-policy scaling and completed compatibility checks."""
import hashlib
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]
EXPERIMENT=ROOT/'.research-cache/parallel-optimization-20261106'


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    benchmark=load(EXPERIMENT/'benchmark/report.json')
    serial=load(EXPERIMENT/'serial-parity/report.json')
    audit=load(ROOT/'reports/hrc-workbench-audit.json')
    for name,digest in benchmark['source_sha256'].items():
        if sha(ROOT/name)!=digest:raise ValueError('Source differs from benchmark: '+name)
    if sha(benchmark['executable'])!=benchmark['executable_sha256'] or not all(r['identical'] for r in serial):
        raise ValueError('Changed binary or serial regression')
    if audit['findings']:raise ValueError('UI audit findings')
    comparisons=[]
    for scene,nodes in benchmark['strategy_comparisons'].items():
        for label,node in nodes.items():
            comparisons.append({'scene':scene,'node':label,'node_id':node['node_id'],
                'serial_seed43_vs44':node['serial_seed43_vs44'],
                'median_parallel_hand_mae_pp':{str(t):statistics.median(r['combo_weighted_hand_action_mae_pp'] for r in node['parallel_vs_serial'] if r['threads']==t) for t in (2,4,8)}})
    result={'schema':'hrc-parallel-delivery-v1','date':'2026-11-06','benchmark':benchmark,
        'serial_parity':serial,'regular_tests':{'distinct_cases':190,'batches_passed':[82,127],
            'targeted_followup_passed':7,'overlap_excluded':True},'strict_ui_audit':audit,
        'browser':{'job_id':'80147d93a48d44338701b5603b188722','source_samples':20000,
            'target_samples':30000,'added_samples':10000,'actual_threads':4,'completed':True,
            'invalid_thread_value_rejected':True,'invalid_field_focus':'resume-threads',
            'resume_input_rows_aligned':True,'viewport':[1280,720],
            'screenshot':'reports/ui/parallel-workbench.png'},
        'implementation':{'algorithm':'asynchronous shared-policy traversal, synchronized node reads/updates',
            'shared':['regret/average/visit stores','topology','static/dynamic card abstractions','immutable chance tables'],
            'private':['RNG state','deal/rank/bucket state','terminal values','ICM/MTT/PKO and FGS caches'],
            'checkpoint':'v3 layout plus validated optional HRPAR001 RNG trailer; saves at completed batch boundaries',
            'api_default_threads':1,'ui_default_threads':4,'max_threads':32},
        'strategy_comparison_summary':comparisons,
        'limits':['Parallel scheduling changes sampling and update order; repeated parallel runs are not bitwise reproducible.',
            'Two million total samples per run, three repetitions and two fixed eight-player15BB scenes. No convergence or exploitability certificate.',
            'Root and BTN conditional hand/action differences are comparable in scale to one serial seed43/44 comparison; deeper rare nodes and longer budgets need further evaluation.',
            'No CPU affinity/clock control; FGS statistics are labeled worker0 and FGS work limits are per worker.',
            'Private caches consume more memory with more workers; the estimated process memory budget rejects allocations before worker setup.',
            'Browser checks used the desktop viewport; no separate mobile emulation was run for this numerical-field addition.'],
        'further_candidates':[
            {'item':'Avoid terminal validation on cache hits','source':'native/hrc_equity.hpp:compute_terminal',
             'evidence':'validate_terminal runs before exact cached-key comparison; an existing identical validated key could return directly. Invalid cache misses must still be validated.', 'measured':False},
            {'item':'Avoid duplicate final checkpoint writes','source':'native/hrc_research_solver.cpp:main',
             'evidence':'When the sample target lands on a periodic checkpoint, the same boundary is saved again after the loop. Zero-sample, CI and failure boundaries need explicit handling.','measured':False},
            {'item':'Load only static abstraction streets used by decision nodes','source':'native/hrc_cards.hpp:AbstractionTables::load',
             'evidence':'All three street tables load whenever any static postflop decision exists; flop-only trees could omit turn/river bucket tables. Full four-street scenes still need all tables.','measured':False}]}
    target=ROOT/'reports/hrc-parallel-optimization.json'
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    rows=[]
    for scene,values in benchmark['results'].items():
        for count,data in values.items():
            rows.append(f"| {'ChipEV' if scene.endswith('chip') else 'ICM/PKO'} | {count} | {data['median_seconds']:.3f} | {data['speedup']:.2f}× | {data['median_peak_mib']:.1f} |")
    text='''# 共享策略多线程落地

2026-11-06。原生内核已支持 1–32 线程；现有 Engine 和续跑区域增加线程数字段。API 默认一线程以兼容原有调用，新的网页线程字段默认四线程。当前 8769 服务已更新，实际存档续跑任务 `80147d93a48d44338701b5603b188722` 完成了从 20,000 到 30,000 样本的四线程续跑。

## 本机测量

i5-13600KF，14 物理核 / 20 逻辑处理器，约 32GB RAM。八人 15BB，**每次是 200 万总样本**，不是每线程 200 万。1/2/4/8 线程各重复三轮，轮换执行顺序，固定 seed43。训练耗时包含保存检查点，排除启动加载。以下为三轮中位数。

| 场景 | 线程 | 耗时（秒） | 相对一线程 | 原生峰值内存（MiB） |
|---|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

8 线程的完整原生进程平均约使用 5.4–5.5 个逻辑处理器，包括串行加载和检查点阶段；不是“线程创建了但训练仍然只用一核”。没有固定 CPU 亲和性或时钟，不承诺其他树、预算和机器得到相同比例。

## 并行语义与兼容性

多个线程更新同一份遗憾、平均策略和访问计数。节点策略读取/采样和更新分别持有该节点的互斥锁，递归子节点时释放锁。每线程持有独立发牌、RNG、终局与权益缓存；不可变的树、桶表和 chance 数据共享。训练停止在完整批次之间，保存时所有工作线程都已结束当前批次，因此没有后台写入正在导出的节点存储。

异步更新顺序不同于一线程，不能承诺相同种子或样本数得到相同策略、检查点或收敛行为。检查点扩展保存所有线程随机状态；恢复相同线程数时保留每条流，改变线程数时保留主流并初始化其他流。原有单线程检查点不增加尾部；多线程使用可校验 `HRPAR001` 尾部。`.plabz`、我们的 `.hrcz` 原生扩展和策略迁移均保留并验证它。标准 HRC 核心文件格式不变。

额外私有缓存与线程栈在启动前纳入内存预算。FGS 的状态/扫掠/工作时间预算按线程生效；FGS 的汇总字段明确标记当前报告的是 worker0，不能当作所有线程之和。

## 验证

- 190 项不同的相关测试在两批运行中通过；追加的 7 项针对性复测通过，覆盖新增的原样 RNG 恢复、并行 `.hrcz`/`.plabz` 往返与策略迁移断言。
- 两个场景各训练 200 万次时，新内核的一线程检查点与上一版单线程程序逐字节一致。
- 并行根节点总更新数和逐手访问数等于全局样本数；没有把线程数乘进显示计数。测试覆盖 v3/v4、线程数变化、KO/PKO、ICM/MTT、锁定与频率、抽水、固定牌面动态表、FGS、取消及内存上限。
- 对照根节点与 folded-to BTN：2/4/8 线程与一线程的逐手差异，与一线程 seed43/44 的差异在同一量级。200 万次时 BTN 逐手平均误差本来就约 9–10 个百分点，不能由整体行动频率接近推出已收敛。
- 桌面页面真实启动四线程续跑；验证错误线程数就地提示、错误焦点、输入行对齐、完成线程数和无横向页面溢出。静态严格审查为零问题，复用项目已有的审查器兼容包装器，未改动或禁用任何规则。未另做手机模拟。

## 下一批明确候选

1. **缓存命中前重复校验。** `Calculator::compute_terminal` 当前先校验终局，再检查精确缓存键。已存在的合法相同键可以直接返回；缓存未命中和非法输入仍需完整校验。
2. **终点检查点重复保存。** 当样本目标刚好落在周期保存点时，退出循环后又保存同一检查点。可去掉重复写盘，但需区分零样本、CI 和异常边界。
3. **按需要的街道加载桶表。** 当前只要有一个静态翻后决策，就读入全部三街；只有 flop 决策的树可以省掉 turn/river。完整四街树不适用这项节省。

这三项尚未合入或量化收益。主要加速已在本轮多线程中实测，未把候选收益叠加到倍率上。

## 复现

```powershell
.venv/Scripts/python.exe scripts/benchmark-hrc-parallel.py --output .research-cache/parallel-benchmark-repeat --samples 2000000 --repeats 3
```

原始命令、源文件/程序哈希、逐轮耗时、内存、CPU、根/BTN 策略差异保存在 `reports/hrc-parallel-optimization.json`。保留的一线程对照程序与源码在 `.research-cache/parallel-optimization-20261106/baseline/`。
'''
    (ROOT/'research/HRC-PARALLEL-OPTIMIZATION.md').write_text(text,encoding='utf-8')
    print(json.dumps({'report':str(target),'tests':190,'scaling':benchmark['results']}))


if __name__=='__main__':main()
