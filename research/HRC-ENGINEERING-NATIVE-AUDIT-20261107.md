# 三人 40BB 工程差距审计（2026-11-07）

已经恢复并验证核心数学行为，但目前没有完成原版的全部并行和热路径工程复刻。真实小树测速说明：原版采样吞吐约为我们的 **2.411 倍**。此次没有修改生产代码或正式 checkpoint，也没有重跑 CI10。读代码得到的候选与实际测量分列如下。

## 可核算的速度差

| 完整观测窗口 | HRC | 独立实现 |
|---|---:|---:|
| 新增采样 | 946,599,750 | 900,230,000 |
| 观测 wall 秒 | 471.213941 | 1080.609799 |
| 进程 CPU 秒 | 3743.578125 | 6618.125000 |
| 百万次/秒 | 2.008853 | 0.833076 |
| CPU 秒/百万次 | 3.954763 | 7.351593 |
| 平均使用逻辑核 | 7.944540 | 6.124435 |

恒等分解：`吞吐比 = 每样本 CPU 成本比 × 平均用核比 = 1.858921 × 1.297187 = 2.411369`。这是记账关系，不能称为“锁导致 1.30 倍、计算导致 1.86 倍”。CPU 成本同时包含算法工作量、缓存/原子/锁开销、调度与运行时；两端随机流、初始浮点状态、异步更新次序及最终样本量不同。

真正首次 CI10 时刻分别是 HRC **469.152 秒 / 9.99262069**，独立实现 **1080.147 秒 / 9.98149012**。上表 HRC CPU 计量截至 GUI idle 471.214 秒，独立计量含加载和最终保存，故使用各自完整观测 wall 做一致的代数分解。不要把这些 CPU 秒当成同一动态指令轨迹的指令成本。机器是混合核心 i5-13600KF，未采集线程 affinity 或硬件计数器。

## 实际锁抽样

生产副本中每个 worker 的 choose 和 update 各每 4096 次抽一次，使用 try_lock、steady_clock，未改生产源。自身相同 10m 初始档，各新增 5m，8 线程，CI 关闭。baseline 5.311066 秒，instrumented 5.160833 秒；单次结果快 2.83%，属于短测波动/观察扰动，不能宣称没有开销。

choose 48,233 个样本中 busy 749（**1.553%**），busy 样本平均等待 573.8ns；update 13,500 中 busy 350（**2.593%**），busy 平均 495.4ns。根节点 busy 约 11.6%，但整体样本并不支持“大部分时间在阻塞锁”的判断。无争用锁开销、缓存行迁移、锁持有时间和 barrier 等待仍未量化。choose 的节点 284 出现累计 150.4µs busy 等待，而只有 9 个 busy 样本，可能受少量长尾影响，不能按排行榜直接判定最贵节点。完整按节点记录在 `reports/hrc-three40bb-sampled-locks-20261107.json`；严禁把样本等待乘 4096 当作已测总等待。

## 有源码依据的候选

### 1. 并发存储粒度未同原版对齐

**证据状态：** static difference; sampled contention measured, total cost not attributed。

Native locks an entire public node for strategy read/action sampling and separately for update, across every hand bucket. Original mE uses LongAdder and per-element VarHandle adds; mA uses per-element atomic adds. These are different concurrency architectures.

候选：Capture p and epsilon inside existing mutex; move worker-private RNG/scan outside. Later consider original-style atomic or bucket storage only with complete policy/format/CI correctness tests.

未量化/限制：Unsampled lock acquisition cost, cache coherence traffic, lock hold time, and actual blocked-time fraction are unknown. Low busy percentage does not rule out uncontended lock/coherence overhead.

源定位：`native/hrc_research_solver.cpp:311`; `native/hrc_research_solver.cpp:315`; `native/hrc_research_solver.cpp:92`; `analysis/hrc-deep/sources/0021/mE.java:7`; `analysis/hrc-deep/sources/0021/mE.java:65`; `analysis/hrc-deep/sources/0026/mA.java:53`。

### 2. 每批全 worker 同步

**证据状态：** static difference; time not measured。

Native synchronizes all eight workers after each 2000-deal batch, aggregates counters and copies RNG states. Original workers reserve 250-deal blocks independently; its shown barrier is conditional on a pause flag, not unconditional per block.

候选：Measure barrier/idle durations and cancellation polling; consider independent ticketed worker loops with explicit quiescent snapshots.

未量化/限制：Cannot infer the proportion lost to the barrier from average CPU use alone; changing batch scheduling changes asynchronous trajectories and checkpoint timing.

源定位：`native/hrc_research_solver.cpp:599`; `native/hrc_parallel.hpp:27`; `native/hrc_parallel.hpp:72`; `native/hrc_parallel.hpp:37`; `analysis/hrc-deep/sources/0034/mn.java:94`; `analysis/hrc-deep/sources/0034/mn.java:174`。

### 3. 终局表预计算路径尚未接入训练

**证据状态：** static difference; cache miss cost not measured。

Original mh precomputes finite leaf utility vectors and selects with a ternary rank-order code. Native training settles pots and odd chips on each uncached terminal/deal, including ChipEV, with per-deal terminal and winner-mask caches.

候选：Independently precompute outcome utility tables for eligible small-player terminals, retaining exact sidepots/oddchips/money/FGS behavior and explicit memory limits; validate against existing independent leaf exporter.

未量化/限制：terminal_calls includes cache hits; no miss counter or terminal timing was collected. Do not multiply all calls by a settlement cost or import original leaf EVs as training data.

源定位：`native/hrc_research_solver.cpp:361`; `native/hrc_research_solver.cpp:373`; `native/hrc_research_solver.cpp:344`; `analysis/hrc-deep/sources/0040/mh.java:131`; `analysis/hrc-deep/sources/0040/mh.java:96`; `analysis/hrc-deep/sources/0042/me.java:4`。

### 4. 存储布局与缓存局部性

**证据状态：** static layout; cache behavior not measured。

Node metadata is an array of structs with separate raw/visits allocations and cold policy pointers; one mutex per node is stored in a separate contiguous array. Terminal caches store MAXP=10 arrays although this case has three players.

候选：Inspect hot/cold separation, compact policy offsets and cache-line placement only after cache/coherence profiling.

未量化/限制：No cache-miss, memory-bandwidth, false-sharing or actual mutex-size measurements. Low total RSS is not evidence of low memory-latency cost.

源定位：`native/hrc_research_solver.cpp:72`; `native/hrc_research_solver.cpp:81`; `native/hrc_research_solver.cpp:138`; `native/hrc_parallel.hpp:50`。

### 5. 递归、临时数组及随机数热路径

**证据状态：** call counts measured; individual costs unmeasured。

Native recursive scalar/vector paths each use p[MAXA],q[MAXA], generic store/model dispatch, RNG calls and counters. MAXA=16, while this tree has two to four actions. Original passes offsets into a reusable worker scratch array.

候选：Profile recursion and RNG/division; consider exact-size action specializations or worker scratch offsets after generated-code inspection.

未量化/限制：Stack declarations do not prove actual emitted stack traffic; compiler inlining and register allocation have not been measured. Eliminating/changing RNG draws would change the algorithm stream.

源定位：`native/hrc_research_solver.cpp:30`; `native/hrc_research_solver.cpp:56`; `native/hrc_research_solver.cpp:398`; `native/hrc_research_solver.cpp:410`; `analysis/hrc-deep/sources/0011/ma.java:7`; `analysis/hrc-deep/sources/0013/mf.java:65`。

### 6. 发牌、抽象与牌力路径

**证据状态：** static implementation; existing correctness checks, no phase timing。

Native deals distinct cards with rejection, lazily canonicalizes each visited street, hashes canonical board rows and maps only required seats. Seven-card ranks and winner subsets are cached per deal; turn/river data is already narrowed to uint8.

候选：Measure deal, board hash, mapping and rank time separately; test any faster exact board index or evaluator independently.

未量化/限制：No present evidence that seven-card ranking is the leading cost; prior rank microbenchmarks are not whole-solver timings.

源定位：`native/hrc_research_solver.cpp:327`; `native/hrc_research_solver.cpp:351`; `native/hrc_research_solver.cpp:336`; `native/hrc_cards.hpp:99`; `native/hrc_cards.hpp:177`; `native/hrc_cards.hpp:53`。

### 7. CI 与保存

**证据状态：** I/O measured; CI cost partly unmeasured。

Formal training checkpoint time is 1.2823695 seconds, 0.1187% of native training time. Native CI duration input measures snapshot construction only; original mq includes the measurement calculation. Native CI executes at the worker batch barrier.

候选：Keep CI measurement duration/semantics correction distinct from throughput changes; this small tree has little remaining I/O opportunity.

未量化/限制：There was no direct total CI CPU timer. Entire pipeline speed difference cannot be assigned to CI or saving.

源定位：`native/hrc_research_solver.cpp:430`; `native/hrc_research_solver.cpp:608`; `analysis/hrc-deep/sources/0030/mq.java:101`。

## 已有优化及下一步验收

本次正式树 3964 节点、1786 决策、2178 叶子；动作数 2/3/4 的决策分别为 1426/329/31。翻前数组仍保留原格式语义，后街 256 桶数据已经压成 uint8；抽象、牌力、赢家集合和终局已经做每副牌缓存。原数学和有限字节码对照不能替代整个运行时的工程复刻。

900.23m 新样本中记录 vector 调用 5,635,730,637、scalar 调用 51,344,445,190、terminal 调用 18,072,298,916；terminal 内含缓存命中，不能认定进行了同样多次结算。原版对应调用计数未收集。固定 250×8 批次约 450,115 次，需要优先补 barrier 等待和 terminal cache miss 两类低扰动计数。

4→8 线程短测为 7.298172→5.641499 秒，仅 1.294 倍；这不是完美扩展，但不能单凭此确定锁瓶颈。旧/新 8 线程短测为 6.018074→5.641499 秒；新版本正式训练保存仅 1.282370 秒（0.1187%），即使全部去掉，理论上限也只有 **1.001189 倍**，不可能解释剩余约 2.4 倍吞吐差。

合理先后次序：先测 barrier 等待和 terminal cache miss；再在隔离分支测试终局预计算、缩小 choose 锁区或异步取块；每项单独 A/B，保留原字节码数值探针、所有存储格式/锁/频率/CI/reset/resume 和原有结算验收。原版使用原子元素更新不意味着可以直接删掉当前 mutex，删锁会造成数据竞争。任一并发改造都会改变异步调度轨迹，不能要求多线程 checkpoint 位相同，也不能因此免除数值/统计验收。

本机 WPR 10.0.26100 可只读列出 CPU/GeneralProfile；当前 exe 的 PDB 存在。未找到 PATH 或标准 toolkit 目录中的 WPA，未验证其他安装位置。没有启动全系统 WPR，也没有安装新软件。现有 -O3 构建并不等于做过 PGO、硬件计数器分析或完整 JIT/native 热路径对照；本轮这些均未做。

机器可读总表：`reports/hrc-three40bb-engineering-gap-20261107.json`。正式结果与抽样副本的生产源哈希及 checkpoint 哈希都未改变。
