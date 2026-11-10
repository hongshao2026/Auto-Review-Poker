# ETW CSwitch v5 前缀与统计边界审查

结论：可将本次 v5 事件的 **offset 0/4/12/14** 按现有字段解析，但应标为经运行一致性校验的兼容前缀，而不是“完整 v5 schema 已证实”。本机 WMI 只有 CSwitch V1–V4；Microsoft TraceEvent 当前解析器允许版本大于 2 且数据长度至少 24。多个非目标字段已有版本变化，不能整体照抄旧版名称。

本审查只读生产源码、原始报告和小量 XML，查询本机 WMI schema，查阅 Microsoft 一手资料。没有修改生产、重跑训练或重复全量解析 1GB XML。root 负责实际流式汇总；下面的解析器问题均已及时发送给 root。

## 1. 来源与可确认字段

本机 `root/wmi` 的 `CSwitch_V1`、`CSwitch_V2`、`CSwitch_V3`、`CSwitch_V4` 查询结果保存在：

`.research-cache/architecture-review-20261108/etw-cpu/cswitch-local-schema.json`

查询可用 `Get-CimClass -Namespace root/wmi -ClassName 'CSwitch*'`，只保留类名以 `CSwitch` 开头，并按属性 `WmiDataId` 排序。继承的 `Flags` 没有 WmiDataId，不是每个 payload 的额外前置字段。

| 字段 | 字节偏移 | 类型 | 证据范围 |
|---|---:|---|---|
| NewThreadId | 0 | little-endian uint32 | V1–V4 本机 schema；PerfView FixupData 从 0 读取 |
| OldThreadId | 4 | little-endian uint32 | V1–V4；PerfView `GetInt32At(4)` |
| New/Old priority | 8/9 | 8-bit | 排序后不受 pointer size 影响；本批不需要解释 |
| 两个历史/保留字节 | 10/11 | 8-bit | V1 名为 New/OldQuantum；V2+ 本机名为 PreviousCState/SpareByte，勿用旧名解释 |
| OldThreadWaitReason | 12 | 8-bit | V1–V4 与 PerfView 一致 |
| flags / 旧 wait mode | 13 | 8-bit | V2 为 OldThreadWaitMode；**V3/V4 改名 ThreadFlags** |
| OldThreadState | 14 | 8-bit | V1–V4 与 PerfView 一致 |
| 历史 ideal processor 字节 | 15 | 8-bit | 不作为实际执行 CPU；本批不解释 |
| 新线程旧式 wait 字段 | 16 | uint32 | 不据此推算本次 off-CPU 时间；计量单位/版本语义未独立验证 |
| 旧 reserved | 20 | uint32 | 不能强制为零；不解释 |
| v5 扩展 | 24 起 | 未确定 | 本批保留原字节，不猜测 |

Microsoft 的 [CSwitch 文档](https://learn.microsoft.com/en-us/windows/win32/etw/cswitch) 描述 V2；不是 v5 特定承诺。当前 [PerfView KernelTraceEventParser.cs](https://github.com/microsoft/perfview/blob/main/src/TraceEvent/Parsers/KernelTraceEventParser.cs) 本地副本行号：`CSwitchTraceData` 4310，字段 4324–4340，长度检查 4358–4359，修复 header 新线程 ID 4444–4454。其 `Version>2` 检查支持继续读该前缀，但第 10/11 字节源码仍有 TODO、且第 13 字节名称落后于本机 V3/V4 schema，说明“源码有字段”不能代替新版本字段语义验证。

只扫描 XML 开头 56,927 个字符取得 5 条 v5 样本，全部长 28 字节；第 13 字节分别为 96、108、96、12、109，明显不是只含 0/1 的 V2 wait mode。样本保存在 `etw-cpu/cswitch-v5-prefix-samples.json`。其 TID/state/reason 前缀看起来合理，但仅凭 5 条合理值不能证明所有事件均正确。

## 2. 状态与等待原因：不得误标 yield

Microsoft CSwitch 文档给出的状态为 0 Initialized、1 Ready、2 Running、3 Standby、4 Terminated、5 Waiting、6 Transition、7 DeferredReady。**7 不是 Unknown。** 更高值保留数字为未知，不因旧枚举缺项就判 trace 损坏。

本批关心的等待原因数值为：

| 数值 | 名称 |
|---:|---|
| 30 | WrQuantumEnd |
| 31 | WrDispatchInt |
| 32 | WrPreempted |
| 33 | WrYieldExecution |
| 34 | WrFastMutex |
| 35 | WrGuardedMutex |
| 36 | WrRundown |

其中 31/32 不能算主动 yield；33 才能标为该枚举名。枚举名称本身也不能证明调用者就是本内核的 `NodeMutex::backoff`：需要同一次 switch-out 的栈或其他独立证据。对于 Ready/Standby/DeferredReady，应归为尚可运行/待调度一类，而不是因为字段名叫 WaitReason 就把全部间隔算成阻塞。文档旧表的 37=MaximumWaitReason 不能用于拒绝新版出现的 37+ 数值；当前批次只对已确认枚举命名。

Microsoft [PIX 对 context switch 的分析说明](https://devblogs.microsoft.com/pix/analyzing-stalls-and-context-switches-in-timing-captures/)强调需要事件和调用栈结合分析；OS 调度、时间片和同步等待都可能产生切换。样本 CPU 栈与 switch-out 栈是不同证据，不可互相冒充。

## 3. 必须执行的运行一致性校验

1. **事件身份和长度。** 只收 Thread task GUID `{3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c}`、opcode 36，保留 version/length 分布，v5 长度应与本文件观察一致；短于 24 直接拒绝。extra bytes 留原始数据，不能吞掉后声称完整解析。非 v5 事件走明确版本规则或单列。
2. **按 payload 归属线程。** old/new TID 来自 4/0；event header 的 PID/TID 不是 old 线程归属凭据。使用 Thread Start/Stop/DCStart/DCEnd 的 PID 与 TID 生命周期。Idle TID 0 是每 CPU 的特殊情况，不当作唯一线程跨核运行。
3. **每 CPU 连续性。** 上一个 CSwitch 的 new TID 应等于下一个的 old TID，边界/丢失/压缩事件另列。相同时间戳按原事件顺序稳定保序，不能用整条 tuple 的 TID 字段重新排序；报告时间戳 ties。
4. **每线程状态交替。** 核对 in/out 交替、无重叠运行区间、无双重 off 配对。若有缺失/censored 区间，不把全部时间静默分给“等待”。不能只检查全局 per-CPU mismatch。
5. **区间守恒。** 每线程有效生命周期内 running + 已分类 off + unknown/censored 应等于该区间。全线程 running 和进程 CPU 时间比较须同窗；若窗口不一致或包含 DPC/ISR/启动收尾，不能要求严格相等，也不能不解释大差额。
6. **线程集合明确。** 主线程加 19 个 worker 必须由 StartAddr/生命周期/已知原生线程名单确认。若目标进程额外有 runtime/helper 线程，不能简单取“最后启动的 19 个”；全程统计 all-target threads 就应使用该集合对应的生命周期分母并分别输出额外线程。
7. **样本与栈匹配覆盖。** 同 TID、同时间、同 sampled IP 校验 QPC→wall 映射，记录总数、匹配数、多个 offset 候选与分段一致性。SampleProf 与 StackWalk 不是一一可盲配的日志；同事件可能分用户/内核栈，合并要保留来源。版本和样本权重字段若存在也要核验。

## 4. 本次 root 解析器审查中发现的具体边界

审查对象为 `scripts/summarize-hrc-etw.py` 读取当时的工作副本。root 可能已根据消息修正，下述是发现记录，不表示当前文件仍有问题。

### 4.1 明确精度错误：只保留六位小数

原 `tick()` 的 `value[11:26]` 只包含 `HH:mm:ss.ffffff`；再 `ljust(7,'0')` 会补零，而不是保留第七位 100ns。应至少截到 27，或者显式解析完整小数前七位。否则原始 QPC 与 wall 的精确 offset 会随低位 0–9 漂移，降低栈匹配覆盖率。这不是事件 schema 问题。

此外，直接 `qpc + offset` 的单位相等只在本 trace `PerfFreq=10000000` 时成立，应断言 header；其他频率需整数比例换算，不能只拟合 offset。精确 same-IP 投票应验证全时间段，而不是只靠一个高票候选。

### 4.2 XML 时间偏移异常

本文件打印时间形如 `2026-11-08T17:30:56.515451500+07:59`，而 header 有 `StartTime=134386038565154515` FILETIME。不要直接依这个异常偏移与 Python 外部 UTC 截同一训练窗口。root 选择同日内部时钟的 100ns ticks 是合理的相对时间方法，应确认所有事件同日/同打印偏移；如跨日则需加日期。精确训练开始应靠同一 ETW 时间轴标记；“全 worker 同时存活”是近似运行窗口，会包含部分 setup/control/final save。

### 4.3 ReadyThread 只能用目标 TThreadId，且需保留 Flag

root 使用 payload `TThreadId` 而非 header TID，方向正确。Microsoft [ReadyThread 文档](https://learn.microsoft.com/en-us/windows/win32/etw/readythread) 明确 Flag 的 0x2/0x4 表示 stack/process swapped；交换回来后会再有 ReadyThread。将第一个 ReadyThread 无条件作为真正 ready 起点可能提前归类，应统计 flags/重复 ready，必要时将这些区间保留 unknown 或按已验证规则处理。状态 Waiting 却无 ReadyThread 的区间应继续显示 `waiting_without_ready_event`，不能当已精确分离的资源等待。

### 4.4 排序与线程集合

原 `switches.sort()` 会在同 CPU 同 timestamp 时用 new/old TID 改写顺序；建议稳定按 `(time,cpu)` 排序并报告 ties。原 latest-19 线程推断与 `threads` 全集参与 CPU/off 统计的集合不一致：必须输出确认依据及其他线程；否则 interval 说 20worker，numerator 却可能含 21+ 线程。

以上修正都只是离线统计边界，不涉及求解器数值/生产代码。只有通过一致性与覆盖率检验后，才能据该短诊断提出具体优化假设；不能将三秒 trace 直接外推为长时间 CI10 的完整成本模型。

## 5. 最终汇总复核与 incoming stack 解释

收到修正后的 `reports/hrc-etw-cpu-diagnostic-20261108.json` 后再次只读检查了解析脚本及统计：

- 时间已保留七位小数，并断言 QPC 10MHz；相同 timestamp 用稳定排序。
- 主线程 56360 加一簇共享起始地址的 19 个 worker，额外线程 58080 排除。19 个创建事件跨度约 0.298ms，符合一次 ParallelTrainer 构造。系统模块目前没有完整私有符号，`worker_start_symbol` 打印的 `ucrtbase!wcsrchr` 不应当成已确认的 worker 函数名称；共同原始地址、创建簇及工作栈才是本次身份佐证。
- 公共生命周期窗口 2.6842835 秒，明确包含控制与最终保存，不冒称精确训练开始/结束窗口。
- 47,389 个 CPU 样本，47,347 个精确时间+TID 栈匹配，覆盖率 99.9114%。所有 CPU 的 CSwitch 连续性错配为 0。
- `old==new` 的 CSwitch 不再建立虚假 off 区间。报告记录的排除数量 71 是全 trace 数量，不等于目标进程个数。
- 20 个线程 running 总 47.3013643 秒，off 总 6.3843004 秒，对照 20×窗口=53.6856700 秒；剩余 5.3μs，仅一个线程有该残差，其他 19 个逐线程为零。此边界已经足以支持本次区间分类，不需要假装无穷精度。
- Ready flags 已保留并排除 0x2/0x4 交换状态。全 trace 仍有 flag8 数值，保持原值；不能声称所有新 flags 含义都已解码。

### 5.1 为什么可关联同一线程的恢复栈

Microsoft 的 [CPU Analysis 字段定义与 wait 分析](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/cpu-analysis)明确将 `NewThreadStack` 关联到切入线程，并以 `TimeSinceLast` 表示该线程上次切出到这次切入的间隔；它还区分被唤醒线程的栈与 `ReadyThreadStack` 的唤醒者栈。该文档的分析流程也将先前等待时间与 NewThreadStack 联合查看。

因此，对于线程 T 的 `[out(T), next_in(T)]`，用 `next_in` 的时间及 **T 自己的 TID** 查询 incoming 栈，方向正确。它可以称为“该 off 区间关联的恢复调用链”。这不等于把切换事件的新线程栈错误地赋给同时切出的另一个旧线程，也不等于拿任意后来的 sampled 栈猜原因。

本文件已观察到 incoming 事件与 newTID 栈精确匹配，而 oldTID 几乎不匹配，进一步支持该解释。它仍不是切出瞬间的独立现场重建，不能从第一 own-module frame 直接证明锁所有者、唤醒者或所有等待的根因。恢复链中包含 `Engine::update`，只能先归类为 update 路径关联；要断言特定锁导致整段延迟，还需要更细的符号/机器地址范围、明确的等待/唤醒链或受控候选验证。

### 5.2 当前可支持的热点优先级

本次采样 exclusive 占比：`Node::strategy_atomic` 24.68%、`Engine::update` 14.71%、`Engine::scalar` 10.90%、`Engine::choose` 9.13%、`bucket_from_row` 8.39%、`Node::update_atomic` 6.05%。这些是 sampled-IP 归属，不是 cache miss、纯锁时间或单条指令的精确成本；内联及一行多个操作还会影响行号归属。

off 区间按恢复链关联：`Engine::update` 3.62248 worker 秒，condvar 2.12948 worker 秒。state=Ready/reason=WrYieldExecution 为 3.55609 worker 秒，占共同 worker 墙钟约 6.624%。这与共享写同步值得优先检查相容，但不得把它换算成一定可获得的 6.624% 墙钟加速，也不能把 update 的全部 sampled CPU 14.71% 都称为锁开销。

建议当前优先级为：共享策略读取及写同步，其次桶映射和默认执行路径，再考虑更改控制调度。此次内部窗口的 on-CPU 平均约 17.62 个逻辑 CPU，进程全窗约 15.33；两者分母不同，不能混写。本次比此前 scheduler on/off 测量更忙，也不能用这三秒 trace 解释此前平均 9.5 CPU 的全部原因。

### 5.3 可复用解析器尚应加固的地方

审查时 `parsed-solver-events.json` 只通过文件存在判断复用，没有绑定 XML/ETL 摘要或 parser schema。**root 已根据反馈改为 schema2 + ETL SHA256 + XML SHA256，并安排从原始 XML 重建复核**；这是已处理的缓存身份问题，不再列为当前未修复缺陷。后续解析语义改变仍应升级 schema。系统库缺私有 PDB 时的最近导出符号应继续标为低置信度，不影响本地 own EXE/PDB 热点统计，却不能用于解释系统内部调用链。

root 另加了本次诊断验收门槛：无丢事件、CSwitch 连续性错配为零、CPU 栈覆盖超过 99%、线程总账残差不超过 100μs、内窗 on-CPU 不超过外部进程总 CPU。本次已审输出满足这些界限。新的 HRC20 正式对照尚未开始，仍受原版启动前的外部软件检测阻挡；本次调度计量和 ETW 都不是那项匹配对照的替代品。

本轮没有执行新的采样或修改生产。数值证据与审查源 hash 已附到 `reports/hrc-etw-cswitch-prefix-review-20261108.json`。
