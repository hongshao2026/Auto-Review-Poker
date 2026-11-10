"""Collect completed production optimization measurements and parity evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',type=Path,required=True)
    args=parser.parse_args();folder=args.experiment.resolve()
    load=lambda path:json.loads(path.read_text(encoding='utf-8'))
    baseline=load(folder/'baseline/manifest.json')
    benchmark=load(folder/'long/report.json')
    differential=load(folder/'differential/report.json')
    legacy=load(folder/'legacy-resume/report.json')
    policy=load(ROOT/'reports/hrc-original-policy-validation.json')
    for rel,digest in benchmark['source_sha256'].items():
        if sha(ROOT/rel)!=digest:raise ValueError('Source changed after benchmark: '+rel)
    for report in (benchmark,differential):
        for info in report['executables'].values():
            if sha(info['path'])!=info['sha256']:raise ValueError('Executable changed')
    if benchmark['executables']!=differential['executables']:raise ValueError('Different tested kernels')
    if benchmark['executables']['baseline']['sha256']!=baseline['executable_sha256']:raise ValueError('Different baseline')
    if not benchmark['all_checkpoints_identical'] or not differential['passed'] or not policy['passed'] or not legacy['passed']:
        raise ValueError('Failed validation')
    if policy['header_sha256']!=sha(ROOT/'native/hrc_policy.hpp'):raise ValueError('Stale policy evidence')
    result={'schema':'hrc-production-optimization-validation-v1','date':'2026-11-06',
        'production_optimized':True,'training_threads':1,'compiler_flags_changed':False,
        'baseline':baseline,'benchmark':benchmark,'differential':differential,'legacy_resume':legacy,
        'regular_tests':{'initial_passed':165,'initial_failed':1,
            'resolved_failure':'test_retained_original_policy_validation: stale header hash; refreshed by rechecking retained original snapshots, then passed targeted rerun.',
            'followup_passed':1,'verified_cases':166,
            'command':'.venv/Scripts/python.exe -m pytest tests/test_hrc_kernel.py tests/test_hrc_policy.py tests/test_hrc_cards_abstraction.py tests/test_hrc_native_features.py tests/test_hrc_tournament_native.py tests/test_hrc_native_rake.py tests/test_hrc_checkpoint.py tests/test_hrc_native_dynamic.py tests/test_hrc_hrcz_leaves.py tests/test_hrc_hrcz_interchange.py -q --tb=short'},
        'retained_original_policy_validation':policy,
        'changes':['Cross-deal reuse of card-independent terminal values, excluding rake and FGS.',
            'Evaluate hand ranks only for needed seats; reset rank mask on both deal paths.',
            'Stream u16 turn/river bucket files into checked uint8 tables with a 32KiB conversion buffer.',
            'Cache exploration probability and regular-store refresh divisor by the actual stored counter.',
            'Use caller-owned buffers in locked/frequency training strategies; keep vector display APIs.'],
        'compatibility':['Checkpoint layout, RNG call order, resource file bytes and solver compile flags unchanged.',
            'Both traversal modes and bidirectional baseline/optimized checkpoint restore verified.',
            'Current local web service uses the rebuilt content-addressed executable on subsequent solves.'],
        'limits':['Performance measurements cover two eight-player15BB scenes and one seed, with three rotated-order repetitions at five million samples per run.',
            'No claim of a universal speedup, identical wall-clock stopping/CI histories, or a convergence certificate.',
            'Memory saving applies when the static postflop abstraction tables are loaded; fixed-board dynamic tables use a separate representation.',
            'FGS, MTT, rake and constrained policies have numerical parity evidence here, not measured speedup claims.']}
    target=ROOT/'reports/hrc-performance-optimization.json'
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    rows=[]
    for scene,r in benchmark['results'].items():
        old,new=r['baseline'],r['optimized']
        rows.append(f"| {'ChipEV' if scene.endswith('chip') else 'ICM/PKO'} | {old['median_native_seconds']:.3f} | {new['median_native_seconds']:.3f} | {(r['speedup']-1)*100:+.1f}% | {old['median_peak_working_set_bytes']/1048576:.1f} → {new['median_peak_working_set_bytes']/1048576:.1f} |")
    document='''# 本地内核优化落地

2026-11-06。以下优化已进入正式原生内核并完成本地构建，页面随后启动或续跑的解算会使用新程序。训练仍为单线程；编译参数未改动。

## 实测结果

本机 i5-13600KF，14 物理核 / 20 逻辑处理器，约 32GB RAM。八人 15BB，固定 seed43，每次从零训练 **5,000,000 样本**，两个场景、新旧两个版本各重复三轮，轮换执行顺序。共 12 次运行 / 6000 万样本；不是单个场景的新版本已经训练了 6000 万次。

| 场景 | 原版中位耗时（秒） | 优化后中位耗时（秒） | 吞吐变化 | 原生进程峰值内存（MiB，中位数） |
|---|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

耗时包含周期和最终检查点保存，不含原生进程启动前的资源加载。原始报告另有包含启动的墙钟时间。没有固定 CPU 亲和性/时钟；这是特定树、种子和预算上的结果，不承诺所有场景同样提速，也不等同于收敛证明。

## 已合入的改动

1. **固定终局跨发牌复用。** 所有奖池都只有一个合资格赢家时，派奖和淘汰赢家掩码不依赖牌面，首次求值后复用。明确绕开抽水和 FGS 模式，保留其原有缓存行为。
2. **按需牌力计算。** 只评估当前争夺池需要的座位，同一次发牌内用掩码复用结果。普通发牌和固定牌面范围发牌都会重置掩码；叶子导出和结算探针显式传入牌力的入口继续有效。
3. **turn/river 桶表压缩。** 编号 0..255 使用 uint8，flop 的 1024 桶继续使用 uint16。磁盘文件不改动，按 32KiB 块读取原始 u16 文件，校验后转换，避免同时保留整张 u16 副本。两张表本身减少 163,885,475 字节，约 156.29MiB；新缓存字段等会略微抵消进程级节省。原生内存预算计入新表示及转换缓冲区。
4. **复用计数相关数学量。** 按实际存储计数缓存探索概率和普通策略存储的刷新除数；计数键变化时重算，覆盖 flush、reset、restore。维持原有 sqrt/floor 公式、精度和随机数调用。
5. **消除约束节点的临时分配。** 锁定和频率约束训练使用调用方缓冲区与最多 16 行动的栈数组；用于显示和其他调用方的 vector 接口保留。

## 数值与兼容性验证

- 12 次较长基准的同场景检查点全部逐字节一致，覆盖存储数组、根累计收益、访问次数和 RNG 状态。内置 46 条数值探针与旧程序一致。
- 160 项新旧程序对照通过：v3/v4、ChipEV、ICM、MTT、KO、PKO、三类抽水、FGS 深度 0/1、静态与动态翻后存储、锁定和频率约束。覆盖双向检查点续跑及三类重置。
- 实际历史 ChipEV、PKO 的 6000 万次检查点，各用新旧程序继续 1000 次，两个场景的新检查点逐字节一致；原始结果只读保留。
- 166 项常规测试验证通过，包括 5400 个原始桶映射/花色置换案例、跨读取块边界、255/256 范围边界、截断输入，以及 `.hrcz` 叶子导出和互通回归。初次测试有一项因保留证据绑定旧头文件哈希失败；重新对照原始保留快照后刷新报告，单项复测通过。
- 原始策略保留快照重新对照：121 个锁定场景、864 个频率快照，174,814 次数值比较。未重新调用原版程序；保留数据和输入哈希记录在策略报告中。

检查点布局、随机数调用顺序和磁盘资源格式不变。墙钟停止条件和 CI 的采样时刻可能因运行速度变化而落在不同样本边界，不声称其历史逐字节相同。FGS、MTT、抽水和约束模式在本轮有数值回归证据，尚无各自的提速测量；动态翻后表使用独立表示，不适用上述静态表内存节省量。

## 复现与记录

保留的旧程序、源码及构建信息位于 `.research-cache/performance-optimization-20261106/baseline/`。所有对照使用新输出目录，不覆盖已有解算。

```powershell
.venv/Scripts/python.exe scripts/benchmark-hrc-optimization.py --baseline .research-cache/performance-optimization-20261106/baseline/solver.exe --samples 5000000 --repeats 3 --output .research-cache/performance-optimization-repeat
.venv/Scripts/python.exe scripts/validate-hrc-optimization.py --baseline .research-cache/performance-optimization-20261106/baseline/solver.exe --output .research-cache/performance-differential-repeat
```

逐轮耗时、内存、命令、文件哈希和检查点对照保留在 `reports/hrc-performance-optimization.json`。合入前的 50 万次短测记录保留在 `research/HRC-PERFORMANCE-REVIEW.md`，不替换为本轮数据。
'''
    (ROOT/'research/HRC-PERFORMANCE-OPTIMIZATION.md').write_text(document,encoding='utf-8')
    print(json.dumps({'report':str(target),'results':benchmark['results'],
        'differential_checks':differential['checks_count'],'regular_tests':166},ensure_ascii=False))


if __name__=='__main__':main()
