# 桶条带锁与 worker 分片计数：设计审查

2026-11-08。本次仅审查 root 提出的设计，未看到该候选实现，未编译、训练或测性能。原版依据见 `HRC-ROUND3-ORIGINAL-STORAGE.md`；这不是对尚未提交代码的通过结论。

设计在固定节点配置、统一访问协议和停稳维护的条件下可实现：同一桶的R/A/D与visits受同一条带锁保护，跨桶共享的raw0以及mA公共平均值继续使用原子操作，计数增量由worker分片。它减少桶内CAS数量，但对热门桶/条带仍有竞争，收益未知。

## 必须固定的共享状态协议

| 状态 | 训练期间唯一允许的访问方式 |
|---|---|
| eligible节点的桶R、mE桶A/D、visits[h] | choose和update都持有该node的同一把`stripe[h & 15]`；不得解锁后再从共享R归一化。P/Q可在锁内复制后作为worker局部数据继续使用。 |
| eligible节点raw[0] | 所有训练读、加法和CAS均原子；不能调用会plain读取raw0或写共享epsilon缓存的默认sample分支。 |
| mA公共raw[1..K] | 全部训练更新均原子。不同桶的条带锁不会互相保护这些共享项。 |
| worker.delta_updates[node] | 仅所属worker写，但其他worker会读，因此owner的读取和store也必须是atomic；不能使用普通++。 |
| epsilon/divisor缓存 | 每worker私有；其他worker只扫描delta字段，不读写这些缓存值。 |
| eligible节点n.updates | 运行期间不作为热共享计数读取；只在quiescent collect后回填，供维护/保存。 |
| fallback节点 | choose/update继续使用同一整节点NodeMutex；eligibility在一次训练期间固定，不允许一个worker走条带、另一个走整节点锁。 |

条带数16要求每个节点实际有16个可访问锁；若为小桶数压缩条带数，mask也必须随之匹配且为2的幂。`h`必须是稳定的实际桶编号，不能一处用combo、一处用bucket。

## 计数与公式条件

建立每节点不可变的训练起点 `initial_count`，每worker从delta=0开始。一次有效update的顺序应为：

1. 从局部P/Q按原行动顺序算V；marker=0仍是有效regret更新。
2. 原子读取自己delta，加1后原子store。一个Engine只能由一个worker执行，不允许同owner并发/重入更新。
3. mE：t=atomic_load(raw0)+1；消费原signed integer判定刷新；命中后再次load raw0为expected，再令t=initial_count+所有worker delta原子load之和，单次weakCAS且忽略失败结果。本次local t始终使用该sum。
4. mA：t必须由atomic double add(raw0,1)返回的old+1得到，不能替换为delta求和。随后更新桶R；仅marker>0时更新全节点A。
5. mE：桶R/A/D都由该条带锁保护，A仍不乘marker；mA没有桶D/A。

worker分片之和不是原子的全局快照，这是模拟LongAdder式计数的一个性质，但不意味着复现了原LongAdder的分片选择、内存排序或具体调度。原VarHandle的RMW使用volatile语义；若新方案使用relaxed/release/acquire组合，必须将其作为明示的独立并发协议，而非声称完全原版等价。

**collect最容易出现的错误：** 若delta从trainer创建后一直累计，必须写 `n.updates=immutable_initial_count+sum(delta)`，不能把上一次已回填的n.updates再次加上同一批未清零delta。否则每个50ms控制slice都会重复计数。推荐delta保持累计且起点固定；如果选择collect清零delta，必须所有worker停稳后同步更新每节点基线，不能边跑边清。

collect只回填n.updates，不应顺便将mE raw0每slice刷新为总和。那会改变稀疏缓存、后续探索概率和regret时间权重。只有原已有的flush/CI/导出边界执行相应flush。

恢复、换线程数和重新建立trainer：基线取已保存/回填的完整n.updates，新的所有delta清零。当前CLI在建trainer前reset；若未来允许活trainer内reset，必须在quiescent状态重置基线和全部delta，不能只重置Node原存储或缓存键。

## 构造、停稳与退出

- 所有worker缓存地址、node→条带索引、worker指针列表在启动线程前固定；训练中不得扩容或更换这些容器。
- refresh求和时只做原子load，不再获取其他worker或其他node的锁，避免跨条带锁顺序死锁。
- collect、flush、save、reset、退出清理须等待当前slice所有worker完成；它们可在该happens-before边界后使用普通存储访问。
- thread创建或分配失败时，尚未成功构造的trainer不会运行析构函数。先完成所有可能抛出的分配，再发布main状态；或者使用覆盖完整发布阶段的rollback guard。
- 采样内部异常仍可能留下已完成子遍历更新。保持既有停止后回滚checkpoint协议，不将部分step保存为合法完成边界。

## 内存成本与收益边界

若锁仍为alignas(64) NodeMutex，16把即1024字节/node。对494,055个节点全量分配为505,912,320字节，约482.5MiB；这还没有包括fallback整节点锁、worker caches、起点计数及映射表。若只给eligible决策节点分配，按实际数量计费，额外索引也须计入预算。不能沿用旧64字节/node的预算估算。

每个worker私有Cache包含被其他worker读取的delta，扫描时可能与owner更新epsilon/divisor产生缓存行流量；这不构成同一字段的数据竞争，但“取消global counter RMW”不自动等于无共享缓存成本。为delta单独padding也会进一步增加内存，不宜在未测量时默认扩大。

热门桶仍被串行保护，不同桶落到同一`h&15`也会冲突；mA的全节点计数和公共A仍是全局竞争点。静态设计不足以判断16是否优于4/8/32，或该方案是否优于已验证NodeMutex。

实现后最少需要：同桶与跨桶并发更新不丢失；marker0与mA公共A；反复collect不重复计数；从非零checkpoint恢复与改变线程数；混合eligible/fallback；停稳flush/reset；32线程、慢holder与异常；预算/构造失败；随后无插桩A/B和多seed策略/CI。单线程旧路径应保持不变，但不能据此推断新的多线程轨迹逐位相同。
