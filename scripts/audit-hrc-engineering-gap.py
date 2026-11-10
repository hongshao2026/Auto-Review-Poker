"""Read-only derivation from the completed three-player run and source audit."""
from pathlib import Path
import hashlib
import json
import math

ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))
def line(path,needle):
    return {'file':path,'line':next(i for i,s in enumerate((ROOT/path).read_text(encoding='utf-8').splitlines(),1) if needle in s)}
def digest(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()

original=read('reports/hrc-three40bb-ci10-original-20261107.json')['formal']
independent=read('reports/hrc-three40bb-ci10-independent-20261107.json')
native=independent['phases']['formal']; summary=native['summary']
short=read('reports/hrc-three40bb-throughput-diagnostic-20261107.json')
locks=read('reports/hrc-three40bb-sampled-locks-20261107.json')
compact=read('.research-cache/three40bb-ci10-independent-20261107/input/tree.json')
kernel='native/hrc_research_solver.cpp'; parallel='native/hrc_parallel.hpp'; cards='native/hrc_cards.hpp'
def metric(n,w,c):return {'new_samples':n,'observed_wall_seconds':w,'process_cpu_seconds':c,
    'samples_per_second':n/w,'cpu_seconds_per_million_samples':c/n*1e6,'average_logical_cores':c/w}
h=metric(original['last_ci_run_samples'],original['last_observed_elapsed_seconds'],original['process_cpu_seconds_delta'])
n=metric(summary['iteration']-10_000_000,native['wall_seconds'],native['process_cpu_seconds'])
decomposition={'throughput_hrc_over_native':h['samples_per_second']/n['samples_per_second'],
    'cpu_cost_native_over_hrc':n['cpu_seconds_per_million_samples']/h['cpu_seconds_per_million_samples'],
    'average_core_hrc_over_native':h['average_logical_cores']/n['average_logical_cores']}
assert math.isclose(decomposition['throughput_hrc_over_native'],decomposition['cpu_cost_native_over_hrc']*decomposition['average_core_hrc_over_native'])
paths={compact['root']:[]}; pending=[compact['root']]
while pending:
    parent=pending.pop()
    for edge,child in enumerate(compact['nodes'][parent]['children']):paths[child]=paths[parent]+[str(edge)];pending.append(child)
node_meta=lambda i:{'node':i,'path':paths[i],'actor':compact['nodes'][i]['actor'],'street':compact['nodes'][i]['street']}
for op in locks['operations']:
    for row in op['top_nodes_by_observed_busy_wait_ns']:row['topology']=node_meta(row['node'])
decisions=[x for x in compact['nodes'] if x['children']]
raw_doubles=sum(1+(2*len(x['children'])+1)*x['buckets'] if x['street']==0 else 1+(x['buckets']+1)*len(x['children']) for x in decisions)
visits=sum(x['buckets'] for x in decisions)
facts=[
 {'id':'node_mutex','status':'static difference; sampled contention measured, total cost not attributed',
  'evidence':[line(kernel,'int choose('),line(kernel,'void update(int id'),line(kernel,'double exploration_probability()'),line('analysis/hrc-deep/sources/0021/mE.java','private final LongAdder'),line('analysis/hrc-deep/sources/0021/mE.java','a.weakCompareAndSet'),line('analysis/hrc-deep/sources/0026/mA.java','a.getAndAdd')],
  'fact':'Native locks an entire public node for strategy read/action sampling and separately for update, across every hand bucket. Original mE uses LongAdder and per-element VarHandle adds; mA uses per-element atomic adds. These are different concurrency architectures.',
  'candidate':'Capture p and epsilon inside existing mutex; move worker-private RNG/scan outside. Later consider original-style atomic or bucket storage only with complete policy/format/CI correctness tests.',
  'unknown':'Unsampled lock acquisition cost, cache coherence traffic, lock hold time, and actual blocked-time fraction are unknown. Low busy percentage does not rule out uncontended lock/coherence overhead.'},
 {'id':'batch_barrier','status':'static difference; time not measured',
  'evidence':[line(kernel,'while(e.samples<goal){uint64_t limit='),line(parallel,'void worker(size_t id)'),line(parallel,'void run(uint64_t samples)'),line(parallel,'void capture()'),line('analysis/hrc-deep/sources/0034/mn.java','while (!var25.isFinished'),line('analysis/hrc-deep/sources/0034/mn.java','if (var24.a.a.get())')],
  'fact':'Native synchronizes all eight workers after each 2000-deal batch, aggregates counters and copies RNG states. Original workers reserve 250-deal blocks independently; its shown barrier is conditional on a pause flag, not unconditional per block.',
  'candidate':'Measure barrier/idle durations and cancellation polling; consider independent ticketed worker loops with explicit quiescent snapshots.',
  'unknown':'Cannot infer the proportion lost to the barrier from average CPU use alone; changing batch scheduling changes asynchronous trajectories and checkpoint timing.'},
 {'id':'terminal_lookup','status':'static difference; cache miss cost not measured',
  'evidence':[line(kernel,'const double* terminal(int id)'),line(kernel,'auto award='),line(kernel,'uint32_t pot_winners('),line('analysis/hrc-deep/sources/0040/mh.java','public final double a(lV'),line('analysis/hrc-deep/sources/0040/mh.java','public final void a(Map'),line('analysis/hrc-deep/sources/0042/me.java','public static int a(int[]')],
  'fact':'Original mh precomputes finite leaf utility vectors and selects with a ternary rank-order code. Native training settles pots and odd chips on each uncached terminal/deal, including ChipEV, with per-deal terminal and winner-mask caches.',
  'candidate':'Independently precompute outcome utility tables for eligible small-player terminals, retaining exact sidepots/oddchips/money/FGS behavior and explicit memory limits; validate against existing independent leaf exporter.',
  'unknown':'terminal_calls includes cache hits; no miss counter or terminal timing was collected. Do not multiply all calls by a settlement cost or import original leaf EVs as training data.'},
 {'id':'layout','status':'static layout; cache behavior not measured',
  'evidence':[line(kernel,'struct Node {'),line(kernel,'std::vector<double> raw;'),line(kernel,'struct Terminal {'),line(parallel,'node_locks_=std::make_unique')],
  'fact':'Node metadata is an array of structs with separate raw/visits allocations and cold policy pointers; one mutex per node is stored in a separate contiguous array. Terminal caches store MAXP=10 arrays although this case has three players.',
  'candidate':'Inspect hot/cold separation, compact policy offsets and cache-line placement only after cache/coherence profiling.',
  'unknown':'No cache-miss, memory-bandwidth, false-sharing or actual mutex-size measurements. Low total RSS is not evidence of low memory-latency cost.'},
 {'id':'recursion_rng','status':'call counts measured; individual costs unmeasured',
  'evidence':[line(kernel,'constexpr int MAXP'),line(kernel,'uint32_t bound('),line(kernel,'double scalar(int id'),line(kernel,'const double* vector(int id)'),line('analysis/hrc-deep/sources/0011/ma.java','private double[]'),line('analysis/hrc-deep/sources/0013/mf.java','int var7 = var6 + 2 * this.a.length')],
  'fact':'Native recursive scalar/vector paths each use p[MAXA],q[MAXA], generic store/model dispatch, RNG calls and counters. MAXA=16, while this tree has two to four actions. Original passes offsets into a reusable worker scratch array.',
  'candidate':'Profile recursion and RNG/division; consider exact-size action specializations or worker scratch offsets after generated-code inspection.',
  'unknown':'Stack declarations do not prove actual emitted stack traffic; compiler inlining and register allocation have not been measured. Eliminating/changing RNG draws would change the algorithm stream.'},
 {'id':'cards_abstraction','status':'static implementation; existing correctness checks, no phase timing',
  'evidence':[line(kernel,'void deal(){'),line(kernel,'int hand(const Node& n)'),line(kernel,'void ensure_ranks('),line(cards,'inline CanonicalBoard canonical_board'),line(cards,'inline BucketRow prepare_bucket_row'),line(cards,'inline int rank7(')],
  'fact':'Native deals distinct cards with rejection, lazily canonicalizes each visited street, hashes canonical board rows and maps only required seats. Seven-card ranks and winner subsets are cached per deal; turn/river data is already narrowed to uint8.',
  'candidate':'Measure deal, board hash, mapping and rank time separately; test any faster exact board index or evaluator independently.',
  'unknown':'No present evidence that seven-card ranking is the leading cost; prior rank microbenchmarks are not whole-solver timings.'},
 {'id':'ci_and_io','status':'I/O measured; CI cost partly unmeasured',
  'evidence':[line(kernel,'void poll_ci('),line(kernel,'if(e.samples<goal&&checkpoint_schedule.due'),line('analysis/hrc-deep/sources/0030/mq.java','this.c = Math.max')],
  'fact':'Formal training checkpoint time is 1.2823695 seconds, 0.1187% of native training time. Native CI duration input measures snapshot construction only; original mq includes the measurement calculation. Native CI executes at the worker batch barrier.',
  'candidate':'Keep CI measurement duration/semantics correction distinct from throughput changes; this small tree has little remaining I/O opportunity.',
  'unknown':'There was no direct total CI CPU timer. Entire pipeline speed difference cannot be assigned to CI or saving.'}
]
report={'schema':'hrc-three40bb-engineering-gap-v1','scope':'read-only production audit plus isolated sampled-lock executable',
 'sources':{'original':'reports/hrc-three40bb-ci10-original-20261107.json','native':'reports/hrc-three40bb-ci10-independent-20261107.json','short':'reports/hrc-three40bb-throughput-diagnostic-20261107.json','sampled_locks':'reports/hrc-three40bb-sampled-locks-20261107.json'},
 'production_source_sha256':digest(kernel),'native_build':independent['build'],'original_jar_sha256':read('analysis/hrc-deep/source-index.json')['jar_sha256'],
 'formal_observation_metrics':{'hrc':h,'native':n},'accounting_decomposition':decomposition,
 'first_ci_target':{'hrc_seconds':original['ci_target_reached_elapsed_seconds'],'hrc_ci':original['last_ci'],'native_seconds':summary['ci']['history'][-1]['timestamp_ms']/1000,'native_ci':summary['ci']['value']},
 'measurement_limits':['CPU counters cover each process observation window, not identical engine boundaries. HRC observer ends about 2.06 seconds after first CI crossing; native wall includes setup/final save.',
 'CPU time includes HRC JVM/GUI/GC/observer work and native runtime work. These are process CPU costs, not instruction counts.',
 'Accounting factorization is an identity, not causal attribution. Different seeds, saved float32 versus double initial states, async interleavings and sample counts produce different traversals.',
 'No core affinity or hardware-performance counters were collected on the hybrid i5-13600KF; a logical core-second is not a fixed instruction capacity.',
 'CI10 measures policy drift, not exploitability or a confidence bound. Functional formula probes do not establish identical parallel engineering.'],
 'native_tree_layout':{'nodes':len(compact['nodes']),'decisions':len(decisions),'terminals':len(compact['terminals']),'max_edge_depth':max(map(len,paths.values())),'policy_double_bytes':raw_doubles*8,'visits_bytes':visits*8,'actions_histogram':{str(k):sum(len(x['children'])==k for x in decisions) for k in range(2,5)}},
 'native_formal_counters':{k:summary[k] for k in ['vector_calls','scalar_calls','terminal_calls','constant_scalar_calls']},
 'derived_native_batch_count':(summary['iteration']-10_000_000)//2000,
 'checkpoint':{'training_seconds':summary['training_checkpoint_seconds'],'fraction':native['training_checkpoint_fraction'],'ideal_speedup_if_removed_entirely':1/(1-native['training_checkpoint_fraction'])},
 'short_diagnostics':[{k:r[k] for k in ['phase','wall_seconds','average_logical_cpus','new_samples_per_native_second']}|{'native_seconds':r['summary']['elapsed_seconds']} for r in short['measurements']],
 'sampled_mutex':{'operations':locks['operations'],'baseline_native_seconds':locks['phases']['baseline']['summary']['elapsed_seconds'],'instrumented_native_seconds':locks['phases']['instrumented']['summary']['elapsed_seconds'],'observed_elapsed_ratio':locks['native_elapsed_ratio_instrumented_over_baseline'],'sample_description':locks['sampling'],'limits':[locks['observer_effect'],'Only one short observation each. Instrumented run was 2.83% faster; this does not demonstrate negative instrumentation overhead.','Sampled busy waiting is not an estimate of total waiting; rare preemptions and deterministic sampling can skew node rankings.'],'production_source_unchanged':locks['production_source_unchanged'],'formal_checkpoint_unchanged':locks['formal_checkpoint_unchanged']},
 'candidates':facts,'available_tools':{'wpr':'C:/WINDOWS/system32/wpr.exe','version':'10.0.26100','profiles_read_only_confirmed':['CPU','GeneralProfile','DiskIO','FileIO'],'system_recording_started':False,'wpa_found_on_path_or_standard_toolkit_path':False,'current_pdb':str(Path(independent['build']['executable_path']).with_suffix('.pdb')),'pdb_exists':Path(independent['build']['executable_path']).with_suffix('.pdb').exists(),'profiler_next_step':'If later authorized, use a bounded isolated process sample or targeted counters; do not start whole-system WPR recording during other work.'}}
(ROOT/'reports/hrc-three40bb-engineering-gap-20261107.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')

def refs(f):return '; '.join(f"`{e['file']}:{e['line']}`" for e in f['evidence'])
md=f'''# 三人 40BB 工程差距审计（2026-11-07）

已经恢复并验证核心数学行为，但目前没有完成原版的全部并行和热路径工程复刻。真实小树测速说明：原版采样吞吐约为我们的 **{decomposition['throughput_hrc_over_native']:.3f} 倍**。此次没有修改生产代码或正式 checkpoint，也没有重跑 CI10。读代码得到的候选与实际测量分列如下。

## 可核算的速度差

| 完整观测窗口 | HRC | 独立实现 |
|---|---:|---:|
| 新增采样 | {h['new_samples']:,} | {n['new_samples']:,} |
| 观测 wall 秒 | {h['observed_wall_seconds']:.6f} | {n['observed_wall_seconds']:.6f} |
| 进程 CPU 秒 | {h['process_cpu_seconds']:.6f} | {n['process_cpu_seconds']:.6f} |
| 百万次/秒 | {h['samples_per_second']/1e6:.6f} | {n['samples_per_second']/1e6:.6f} |
| CPU 秒/百万次 | {h['cpu_seconds_per_million_samples']:.6f} | {n['cpu_seconds_per_million_samples']:.6f} |
| 平均使用逻辑核 | {h['average_logical_cores']:.6f} | {n['average_logical_cores']:.6f} |

恒等分解：`吞吐比 = 每样本 CPU 成本比 × 平均用核比 = {decomposition['cpu_cost_native_over_hrc']:.6f} × {decomposition['average_core_hrc_over_native']:.6f} = {decomposition['throughput_hrc_over_native']:.6f}`。这是记账关系，不能称为“锁导致 1.30 倍、计算导致 1.86 倍”。CPU 成本同时包含算法工作量、缓存/原子/锁开销、调度与运行时；两端随机流、初始浮点状态、异步更新次序及最终样本量不同。

真正首次 CI10 时刻分别是 HRC **469.152 秒 / 9.99262069**，独立实现 **1080.147 秒 / 9.98149012**。上表 HRC CPU 计量截至 GUI idle 471.214 秒，独立计量含加载和最终保存，故使用各自完整观测 wall 做一致的代数分解。不要把这些 CPU 秒当成同一动态指令轨迹的指令成本。机器是混合核心 i5-13600KF，未采集线程 affinity 或硬件计数器。

## 实际锁抽样

生产副本中每个 worker 的 choose 和 update 各每 4096 次抽一次，使用 try_lock、steady_clock，未改生产源。自身相同 10m 初始档，各新增 5m，8 线程，CI 关闭。baseline 5.311066 秒，instrumented 5.160833 秒；单次结果快 2.83%，属于短测波动/观察扰动，不能宣称没有开销。

choose 48,233 个样本中 busy 749（**1.553%**），busy 样本平均等待 573.8ns；update 13,500 中 busy 350（**2.593%**），busy 平均 495.4ns。根节点 busy 约 11.6%，但整体样本并不支持“大部分时间在阻塞锁”的判断。无争用锁开销、缓存行迁移、锁持有时间和 barrier 等待仍未量化。choose 的节点 284 出现累计 150.4µs busy 等待，而只有 9 个 busy 样本，可能受少量长尾影响，不能按排行榜直接判定最贵节点。完整按节点记录在 `reports/hrc-three40bb-sampled-locks-20261107.json`；严禁把样本等待乘 4096 当作已测总等待。

## 有源码依据的候选

'''
titles={'node_mutex':'1. 并发存储粒度未同原版对齐','batch_barrier':'2. 每批全 worker 同步','terminal_lookup':'3. 终局表预计算路径尚未接入训练','layout':'4. 存储布局与缓存局部性','recursion_rng':'5. 递归、临时数组及随机数热路径','cards_abstraction':'6. 发牌、抽象与牌力路径','ci_and_io':'7. CI 与保存'}
for f in facts:
    md+=f"### {titles[f['id']]}\n\n**证据状态：** {f['status']}。\n\n{f['fact']}\n\n候选：{f['candidate']}\n\n未量化/限制：{f['unknown']}\n\n源定位：{refs(f)}。\n\n"
md+=f'''## 已有优化及下一步验收

本次正式树 3964 节点、1786 决策、2178 叶子；动作数 2/3/4 的决策分别为 1426/329/31。翻前数组仍保留原格式语义，后街 256 桶数据已经压成 uint8；抽象、牌力、赢家集合和终局已经做每副牌缓存。原数学和有限字节码对照不能替代整个运行时的工程复刻。

900.23m 新样本中记录 vector 调用 5,635,730,637、scalar 调用 51,344,445,190、terminal 调用 18,072,298,916；terminal 内含缓存命中，不能认定进行了同样多次结算。原版对应调用计数未收集。固定 250×8 批次约 450,115 次，需要优先补 barrier 等待和 terminal cache miss 两类低扰动计数。

4→8 线程短测为 7.298172→5.641499 秒，仅 1.294 倍；这不是完美扩展，但不能单凭此确定锁瓶颈。旧/新 8 线程短测为 6.018074→5.641499 秒；新版本正式训练保存仅 1.282370 秒（0.1187%），即使全部去掉，理论上限也只有 **{report['checkpoint']['ideal_speedup_if_removed_entirely']:.6f} 倍**，不可能解释剩余约 2.4 倍吞吐差。

合理先后次序：先测 barrier 等待和 terminal cache miss；再在隔离分支测试终局预计算、缩小 choose 锁区或异步取块；每项单独 A/B，保留原字节码数值探针、所有存储格式/锁/频率/CI/reset/resume 和原有结算验收。原版使用原子元素更新不意味着可以直接删掉当前 mutex，删锁会造成数据竞争。任一并发改造都会改变异步调度轨迹，不能要求多线程 checkpoint 位相同，也不能因此免除数值/统计验收。

本机 WPR 10.0.26100 可只读列出 CPU/GeneralProfile；当前 exe 的 PDB 存在。未找到 PATH 或标准 toolkit 目录中的 WPA，未验证其他安装位置。没有启动全系统 WPR，也没有安装新软件。现有 -O3 构建并不等于做过 PGO、硬件计数器分析或完整 JIT/native 热路径对照；本轮这些均未做。

机器可读总表：`reports/hrc-three40bb-engineering-gap-20261107.json`。正式结果与抽样副本的生产源哈希及 checkpoint 哈希都未改变。
'''
(ROOT/'research/HRC-ENGINEERING-NATIVE-AUDIT-20261107.md').write_text(md,encoding='utf-8')
print(json.dumps({'report':'reports/hrc-three40bb-engineering-gap-20261107.json','audit':'research/HRC-ENGINEERING-NATIVE-AUDIT-20261107.md','decomposition':decomposition}))
