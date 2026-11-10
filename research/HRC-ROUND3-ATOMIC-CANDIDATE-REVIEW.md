# 原子存储隔离候选独立审查，2026-11-08

范围：`.research-cache/throughput-round3-20261108/atomic-candidate/` 的新原子header、Engine choose/update/sample和ParallelTrainer接线。只读，没有编译或运行测试。被审文件快照和SHA256保存在 `analysis/hrc-deep/round3-storage-20261108/atomic-candidate-review/identity.json`；以下行号对应该快照。

结论：在节点配置固定、有效非负counter且维护只在worker停稳时运行的条件下，本次静态审查**未发现默认23/25训练路径遗漏的普通共享raw/updates/visits读写**。这是限定范围的审查结果，不是无数据竞争的形式化证明。一个构造失败窗口应补齐；另有原版内存语义差异必须披露。

## 可操作发现

**[P2] 构造器在异常保护之前发布main的临时指针和标志。** `hrc_parallel.hpp:107` 先设置 `main.atomic_shared=true`、`main.node_mutexes=node_locks_.get()`，随后 `main.parallel_rng.resize(count)`；只有下一行创建thread的loop在try内。如果resize发生bad_alloc，ParallelTrainer尚未构造成功，不会调用其析构函数/stop；成员node_locks_析构后，main仍有悬空指针和开启的atomic_shared。当前CLI构造失败后只保存旧边界再退出，故未发现当前成功运行受此影响；但调用方捕获异常后复用Engine时会遇到残留状态。旧NodeMutex版本已有指针发布的同类异常窗口，新分支增加了atomic标志残留。

建议在所有可抛分配和状态准备完成后再发布main指针/flag，或扩大guard以覆盖发布及之后的步骤，恢复原main状态。另核查失败时主atomic_cache和预算预留是否需要回收，避免把部分构造状态当作正常回退。应使用分配失败注入覆盖 `parallel_rng.resize`，而非只测试thread创建失败。

**[协议差异，非已证实数据竞争] 原子操作全部RELAXED，原VarHandle更新则有volatile内存语义。** `hrc_atomic_candidate.hpp:11,16,19,21–22` 使用relaxed load/RMW/CAS。它为每个cell提供原子性，但不复现原getAndAdd/weakCompareAndSet默认volatile排序；原策略读取的plain daload又弱于候选的原子load。除了exact uint64 counter代替LongAdder非快照sum，候选还改变了读取/更新内存语义。可以作为独立异步实验，不能叫逐位或完整原并发语义等价；是否改为seq_cst应由所需兼容协议与实测决定。没有静态证据表明relaxed本身使独立数值模型错误。

## 已核对的主要路径

| 项目 | 核对结果 | 行号 |
|---|---|---|
| 资格与回退 | 仅K>0、无frequency、无active BucketLocks、format23/25启用。配置在训练期间只读时，每Node所有worker选择同一路径；其他节点仍完整NodeMutex。 | header:29–31；CPP:320–329 |
| 策略读 | 先原子加载K个R到当前调用栈局部数组，再normalize；不会从原共享R做普通读取。raw0经原子load交给worker私有epsilon缓存。 | header:33–36；CPP:321 |
| 计数与visits | 两者用uint64原子fetch_add。raw0各次读取均为generic atomic load。 | header:21–22,39–45 |
| mE刷新 | 初始t=raw0+1；刷新命中后再次load作为expected，独立loadupdates作为local t，单次weakCAS且忽略成功结果。R/A按行动交错，D最后加。 | header:41–49 |
| mA更新 | 点积先计算；raw0的CAS加法返回成功的旧值，再+1；R全部更新后仅marker>0更新共享A。额外之前的raw0 load是冗余读取，不影响t结果。 | header:39–51 |
| double加法 | CAS失败后expected由builtin更新，下一轮重新计算desired；不会重复将同一delta加两次。 | header:13–16 |
| 私有缓存 | 每个Engine独立atomic_cache，主/额外worker按node数分配；节点原mutable epsilon/divisor缓存只被fallback的锁内路径使用。 | parallel:88–89,103；CPP:311–312,321–327 |
| RNG | 当前原子分支保留刷新integer、探索门、探索bound和混合策略unit。epsilon提前算出不消费RNG；多线程读取counter的时点仍可与旧锁版不同。 | header:44；CPP:412–415 |
| worker发布 | caches在启动thread前分配；thread启动后先等待generation，不会在构造器中开始训练。 | parallel:89–108,51–54 |
| 正常退出 | stop先发stopping，再join，之后清main指针/flag/cache。额外Engine与node_locks销毁时线程已结束。 | parallel:56–60 |
| 创建thread失败 | 已启动线程由catch中的stop唤醒并join；此路径清main状态。 | parallel:108–109 |
| 中途异常 | work捕获后设置abort；run/run_adaptive仍等待pending归零，之后collect并抛出；failed_阻止复用失败trainer。 | parallel:46–54,118–145 |
| 维护边界 | run/run_adaptive等待所有worker后才返回；主循环随后poll_ci/save，启动时reset/resume在构建trainer之前。等待中的worker不读写节点，因此plain flush/序列化具有停稳边界。 | CPP:600–610,632–654；parallel:125,141 |
| 预算 | count×nodes×sizeof(Cache)单独预留；原NodeMutex数组仍保留，以供fallback使用，费用未漏。 | parallel:86–89 |

`sample` 的负epsilon哨兵会回退到节点共享缓存；当前原子路径在合法非负计数下得到有限非负epsilon，不走该回退。若以后允许无效/NaN计数，必须先拒绝或使用明确分开的sample API，不能让原子路径进入未加锁的共享缓存。此项不是已复现合法场景bug。

## 成本与边界

所有节点都分配每worker缓存，包括叶子和回退节点；这是保守而显式计费，非内存遗漏。它会使全回退配置也支付额外缓存成本，可能更早触发预算拒绝。若以后推广生产，可先统计eligible节点并紧凑分配；不可在未计费时悄悄分配缓存，也不应把预算失败静默宣称为成功回退。

原始LongAdder计数、Java JIT实际原子指令、所有调度下的可见性、性能与最终CI用时均不在本次静态审查的证明范围。候选还需分配失败注入、32线程原子cell压力、混合eligible/fallback树、停稳维护与恢复、多个seed策略/CI，以及未插桩A/B。本轮没有执行这些测试或声称它们已经通过。
