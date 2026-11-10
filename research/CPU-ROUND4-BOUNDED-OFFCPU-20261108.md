# 九人场景保留尾窗的独立 off-CPU 分析

结论只适用于原 ETW 循环缓冲保留的 **4.3949025 秒共同训练尾窗**，不能替代整次运行、初始化或完整线程生命周期的统计。脚本没有补造 Thread Start，没有启动求解或重新录制 trace。分析已结束，CPU 已交还根代理的性能矩阵。

数据与脚本：

- `reports/hrc-round4-nine-bounded-offcpu-20261108.json`：完整结果、验证、边界、逐线程守恒、状态与原因分解、严格 CPU 热点。
- `scripts/summarize-hrc-bounded-offcpu.py`：独立分析器；必须显式传 `--cpu-window` 才解析缓存。
- `.research-cache/cpu-round4-20261108/nine-etw/parsed-solver-events.json`：已存在 schema-2 缓存，SHA-256 `5bdedf82ad058b65dcf56ec9215409fa4aa98167065c741cef27947b9d4d0669`。
- 旧 `reports/hrc-round4-nine-cpu-stacks-20261108.json` 保持原样，新报告保存其 hash 并复现其结果作为来源校验。

## 窗口与验证

主线程 TID 55880 来自进程首个 monitor 快照中唯一的线程。19 个 worker 来自最早的 19 个 Thread End 短簇，并逐一要求出现训练调用栈；主线程和 I/O helper 52036 均不在该短簇。恢复的模块来自同 PID 的 Image UnLoad 记录，使用现有可执行文件/PDB，未用随机地址猜测基址。

下界严格取所有 CPU 的首个保留 CSwitch、每个参与线程的首个 own-out/own-in、首个严格训练 CPU 样本之最大值，结果为 `692995200392` ticks；上界为最后严格训练样本 `693039149417` ticks。每 tick 为 100 ns。

验证结果：

- 缓存、原 CPU-only 报告、可执行文件身份匹配；ETW EventsLost 与 BuffersLost 都为零。循环缓冲截掉左侧事件仍单独承认，不等同于完整记录。
- 全部保留 CPU 流的 CSwitch 连续性错误为零，线程同时占据两个 CPU 的正长度区间为零。
- 每个 CPU 的保留右端均覆盖上界；上界早于全部参与线程 End。
- 20 个线程各自 `on + off = window`，全部残差 **0 ticks**。
- 原 exact-stack 覆盖率 **99.8460%** 复现；同时间戳迁移、左边界已有 off 状态、错误断链和重复 out 的合成测试通过。

各 CPU 循环缓冲起点不同，左侧残缺区间内确实存在缺少前一个 in 的 out。因此只在共同下界按已知 CPU occupancy 初始化线程状态；下界之前的残缺线程转换不冒充完整历史。下界时已 off 的 0.0901776 线程秒标为未知 wait state/reason，不从不完整前缀推断原因。这不是放宽窗内连续性或守恒门槛。

## 主要观测

| 指标 | 结果 |
| --- | ---: |
| 墙钟窗口 | 4.3949025 秒 |
| 20 线程总线程墙钟时间 | 87.8980500 线程秒 |
| on-CPU | 27.3940229 线程秒 |
| off-CPU | 60.5040271 线程秒 |
| 窗口平均同时运行的目标线程数 | 6.2331 |
| ready/deferred-ready 状态 off 时间 | 49.8230000 线程秒 |
| waiting 到合格 ReadyThread 事件 | 9.0756042 线程秒 |
| 等待结束后、实际获得 CPU 前 | 1.3498063 线程秒 |

目标线程平均运行数不是整机利用率，也不能单凭它确定调度、其他进程、CPU 拓扑、优先级或锁竞争的因果份额。此 trace 没有提供可独立量化所有这些因素的证据。

`WrYieldExecution`（原因 33）关联 **16.9006995 线程秒**，占 off 时间 **27.93%**，占总线程墙钟 **19.23%**。其中 **16.8941178 线程秒**的首个本模块 incoming resume frame 是 `Engine::update`，其余 0.0065817 线程秒没有精确本模块 frame。这是更新路径中的让出 CPU/重新调度与等待的强关联证据；它不等于 `yield()` 函数执行了 16.9 CPU 秒，也不等于可以回收相同比例的端到端速度。

worker 控制 condition-variable resume 链关联 **10.1500046 线程秒**，共 1,287 个 off 区间，最长 32.9854 ms。主线程 coordinator condition-variable resume 链关联 **0.3680703 秒**，共 64 段，最长 16.7378 ms，约为窗口墙钟的 **8.37%**。

worker 已停在控制等待且主线程同时关联 coordinator 等待的重合时间，总计 **4.5394896 worker 线程秒**，约为总线程墙钟的 **5.16%**。这支持“批次尾部存在可测等待”的判断，但 trace 未记录内部 generation、250-deal 块边界或 deadline 事件，不能把所有控制 condvar off 时间精确归因于块大小/50 ms slice，也不能把这 5.16% 当作保证可回收的吞吐。

## CPU 热点分类修正

旧 CPU-only 脚本的 substring `ParallelTrainer::work` 同时匹配 `ParallelTrainer::worker`，因此把少量只含 worker 控制链的样本收入了“训练”。新脚本仍复现旧 **30,355** 以验证来源，但用标识符边界排除 `worker` 对 `work` 的误匹配，严格训练样本为 **30,340**。旧报告没有被覆盖。

共同窗口中有 **26,879** 个严格训练样本，exclusive 热点为：

| 函数 | 样本比例 |
| --- | ---: |
| `Node::strategy_atomic` | 46.48% |
| `Engine::scalar` | 15.80% |
| `Engine::choose` | 6.36% |
| `Node::update_atomic` | 6.31% |
| `Engine::terminal` | 5.85% |

这是被保留且具有严格训练栈的 CPU 采样分布，既不是全生命周期墙钟比例，也不是缓存未命中或可以直接恢复的性能份额。分类修正未改变热点排序。

## 关联边界

本记录的 CSwitch StackWalk 属于 incoming 线程。新脚本只以同一 TID 的精确 switch-in timestamp 关联该线程之前的 off 区间，绝不把 outgoing 线程的等待归给另一个 incoming 线程。恢复链指向的是 resume 位置及保存的调用链，仍不能单独证明致因锁、锁持有者或每个批次的尾部阶段。

ReadyThread 分解继承已审计的 `flags & 6` 排除约定；缺少合格 Ready 事件的等待单列，未知左边界单列。没有把未知项分配给期望的原因。脚本保留严格拒绝路径，任何窗内断链、重叠或逐线程守恒失败都会写 `status=rejected` 而非输出通过结论。
