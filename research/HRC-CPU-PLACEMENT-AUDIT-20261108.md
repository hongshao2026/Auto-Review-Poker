# Windows CPU 拓扑与短测公平性：2026-11-08

本机是 **i5-13600KF：6 个 P 核、8 个 E 核、20 个逻辑 CPU**。8 个求解 worker 不可能都独占一个 P 物理核，因此默认调度可能混入 E 核或 P 核的 SMT sibling。**目前没有记录旧短测的线程实际落核，不能将 3.828–4.766 秒的波动全部归因于大小核。**

本次只读调用 `GetSystemCpuSetInformation`、`GetLogicalProcessorInformationEx`、`GetProcessDefaultCpuSets`、`GetProcessAffinityMask`、`GetPriorityClass`，读取 CIM CPU/OS 信息及 `powercfg /getactivescheme`。没有调用 Set* 调度接口，没有改优先级、电源计划、亲和性，也没有 native 编译或训练。

复现：`.venv\Scripts\python.exe scripts/inspect-hrc-cpu-topology.py`；可加 `--pid <正在运行的进程>` 只读检查该进程。完整产物为 `reports/hrc-cpu-topology-20261108.json`。CPU-set 与 processor-core 两个 API 的逻辑 CPU/物理核心分组及 EfficiencyClass 完全一致，脚本会对不一致显式报错。

## 实测映射

| 类型 | 逻辑 CPU（processor group 0） | 共享关系 |
|---|---|---|
| P 核，EfficiencyClass=1 | (0,1)、(2,3)、(4,5)、(6,7)、(8,9)、(10,11) | 每一对是一个物理核的 SMT；各核2 MiB L2 |
| E 核，EfficiencyClass=0 | 12、13、14、15 | 四个独立物理核共享4 MiB L2 |
| E 核，EfficiencyClass=0 | 16、17、18、19 | 四个独立物理核共享另一块4 MiB L2 |
| 整个 CPU | 0–19 | 单NUMA节点、单processor group，共享24 MiB L3，cache line 64 B |

Intel 官方列出该型号为6P+8E、20线程。[Intel 产品规格](https://www.intel.com/content/www/us/en/products/sku/230494/intel-core-i513600kf-processor-24m-cache-up-to-5-10-ghz/specifications.html)。Windows 定义较高 EfficiencyClass 为性能较高、能效较低的核心；CoreIndex 相同代表共享核心执行资源。[Microsoft CPU-set 结构说明](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-system_cpu_set_information)。具体编号来自本机 API，不是按型号猜测。

快照中检查器进程的 affinity 为 `0xfffff`、default CPU sets 为空、priority class 为 normal；说明该**检查器**允许系统调度全部20个逻辑 CPU，不能代替过去 solver 的实际放置证据。正在使用 Windows“高性能”电源计划，但这不能证明固定频率或关闭核心停车。空闲时读到 parked logical CPU 为 1、3、5、7、9、11、15、16、17；停车状态会变化，该快照不是先前短测状态，更不是过热证据。

## 已有短测能说明什么

`reports/hrc-throughput-round3-screen-20261108.json` 的3个 baseline：

| 次序 | native elapsed | process CPU秒（含setup） | process CPU/wall | scalar calls |
|---|---:|---:|---:|---:|
| r0 | 4.15723 s | 32.03125 | 6.8722 | 264,757,652 |
| r1 | 4.76555 s | 34.89063 | 6.5154 | 263,325,544 |
| r2 | 3.82815 s | 28.53125 | 6.5402 | 262,851,045 |

native elapsed 的 max/min 相差约24.49%；CPU秒也明显变动，不能只解释为“进程完全没分到时间”。scalar 访问数的 max/min 只相差约0.73%，但这不是完整指令计数；节点/动作分布、原子竞争、缓存、忙等、频率以及后台任务仍可能不同。CPU秒是被调度的线程时间，P/E/SMT 不同位置每CPU秒完成的工作也可不同，不能把平均6.5逻辑CPU直接称为6.5个同质物理核。

合理但未证实的影响包括：P/E不同执行速度；两个worker共享一个P核；worker迁移引起缓存变化；E集群共享L2；核心停车唤醒；Turbo/温度或后台任务变化。当前没有 worker residency、迁移数、实际频率/温度、硬件cache-miss或ETW上下文切换证据，因此不能选定唯一原因。原版HRC历史469秒也没有同一份落核记录。

## 建议的公平测量顺序（尚未执行）

1. **先保留默认调度做主要比较。** 相同不可变自身10m checkpoint、树/资源、线程数、输入/输出设置，各候选使用交叉 ABBA 或随机区组顺序，至少5个配对；把5m筛选延长到约15–30秒的固定新增样本验证。加载/初始化保存、native采样、最终写盘分别报告。固定每轮前的轻量预热/间隔，避免仅首个程序承担冷启动。全程不并发编译或训练。
2. **补低频、每worker自己的CPU放置采样。** 可在领取250任务块的路径每64块读取一次当前 processor group/number，按worker输出CPU/class计数，私有计数器避免共享原子。它是抽样落点而非精确驻留时间；不能当作全程迁移轨迹或时间占比。需对比有无观测的开销，避免以监控改变被测行为。现成thread CPU秒可保留，另报告本轮各类实际访问计数，以区分工作量变化。
3. **若默认调度噪声仍大，再加独立亲和诊断组，不能混入默认结果。** 后续若实施，所有候选用完全相同逻辑CPU集合及同样绑定方式/优先级；本轮未设置。可以先用6worker一核一线程P集合 `{0,2,4,6,8,10}` 验证算法工作量，再以8worker固定6P+2E集合 `{0,2,4,6,8,10,12,16}` 检查混合核心敏感性。后者两E来自不同L2集群。另可用8worker P-only SMT组 `{0,1,2,3,4,6,8,10}` 独立观察SMT影响。三组硬件资源不同，不能互相当同条件加速比。
4. **仅限制进程到8个逻辑CPU，并不保证worker一人一CPU。** Controller/监控等线程也可能共享集合，Windows仍可在允许集合迁移；要消除worker相对放置差异须逐worker固定，但会改变默认产品调度。HRC GUI、JVM、GC及其8worker还有额外线程；若拿亲和组比较HRC，双方需同等明确配置并重测，不能直接沿用过去未固定的469秒。
5. **选择优化须同时过质量验收。** 单线程逐字节一致支持语义；异步atomic/条带锁会改变并发可见状态和访问路径。候选筛选中的+7.6%或+9.1%仍是有限短测，保留全部原始数据。选中候选后，再看多个种子的策略/EV质量及完整CI目标耗时，而不是把短测样本吞吐自动当作达到CI10的提升。

Windows查询接口及结构依据：[CPU-set查询](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemcpusetinformation)、[核心关系](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-processor_relationship)、[缓存关系](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-cache_relationship)。本次没有进行全系统WPR/ETW采样。
