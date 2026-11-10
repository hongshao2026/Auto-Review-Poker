# bucket16 实装只读审查

2026-11-08，范围为 `.research-cache/throughput-round3-20261108/bucket16-candidate/` 的主CPP、原子/桶更新header、parallel接线。没有编译或运行CPU测试。被审快照/哈希位于 `analysis/hrc-deep/round3-storage-20261108/bucket16-review/identity.json`，下文行号均对应这批快照。root报告的14,400项语义及16组adaptive结果未由本轮重复执行。

**结论：正常CLI的固定节点配置、构造前reset、停稳维护路径中，本次静态审查未发现新增遗漏的数据竞争。此前指针发布后的分配异常窗口已修。活trainer中的regret reset仍不受支持，生产化应显式拒绝或实现重置基线。** 这不是任意调用顺序或全部调度下无bug的证明。

## API边界与动作项

**[P2，活trainer调用条件] `Engine::reset(r=true)` 未重置分片计数基线。** CPP:462只调用Node.reset；parallel:95–97的initial_updates_保持原值，各worker Cache.local_updates也保留。即便先停稳，reset后的下一次collect仍按旧baseline+delta回填updates（parallel:79–80），使旧计数恢复；mE下次刷新还会使用旧累计计数，影响更新权重。

实际CLI在CPP:615执行reset，然后才构建trainer，因此本轮真实测速不受此条件影响。建议最小生产约束为：attached trainer存在时，Engine拒绝reset/resume或改变节点策略结构，要求先销毁trainer，再reset/恢复并重建。另一种实现是公开quiescent rebase操作，同步更新相关节点的initial基线和所有worker delta。不能只清Node原计数。23/25的仅平均策略reset不改变计数，但也只能在停稳状态执行；若API不区分，可统一拒绝attached trainer reset以保持明确边界。

## 核对通过的接线条件

| 条件 | 源码证据 |
|---|---|
| 仅eligible节点分配16把锁；其余SIZE_MAX回退，选择/更新使用同一静态offset和同一`h&15` | parallel:94–99；CPP:327–339 |
| 普通策略R读取与桶R/A/D/visits写入均在该条带锁内；递归不持有条带锁 | CPP:329–330,336–337；header:62,68–73 |
| raw0读取与CAS/加法均原子；mA共享A全部原子，未错误依赖不同桶的条带锁 | header:63–67,73；CPP:330 |
| 每worker delta仅owner原子load/store；peer只做原子load；无热全局updates RMW | header:60–61；CPP:316–317 |
| mE刷新保留第二次expected读取，随后求sum作local t，单次weakCAS；marker0仍增加计数/桶平均 | header:59–71 |
| mA t来自raw0 atomic add返回的old+1；公共平均只在marker>0更新 | header:67,72–73 |
| epsilon/divisor属于worker私有Cache；同缓存的delta虽被其他worker读取，其他普通字段不被跨worker访问 | header:23–28；CPP:319,330,337 |
| collect用固定initial+所有delta回填eligible updates，不清delta、不flush raw0、不复制raw/visits | CPP:316–317；parallel:79–80 |
| initial、offset、锁、所有worker缓存和parallel_rng均先分配，之后才发布main/peer指针；发布后capture与赋值不分配 | parallel:92–123 |
| thread构造失败catch会stop并join；stop之后清main的flags/锁/offset/peer/initial指针 | parallel:59–64,124–125 |
| run/adaptive返回之前等待所有worker，并在停稳状态collect；维护随后进行 | parallel:141–143,157–161 |
| 预算包含fallback节点锁、offset/initial数组、实际eligible锁数量和count×nodes×sizeof(Cache) | parallel:92–101 |

上表依赖eligibility、桶编号映射和各vector地址在trainer生命期不变。活trainer中切换frequency/locks/store_format会使已固定offset和实际Node路径不一致，应与reset/resume一起禁止或重建。

header仍保留此前全cell atomic候选的strategy/update模板（:34–53），当前Engine条带路径没有调用它们。如果未来将两套函数作用到同一Node，可能把原子读写和条带保护的plain读写混在一起；生产整理时宜删除未用候选入口或用明确模式类型隔离。这不是本次实际调用路径已发生的竞争。

## 不阻断当前测量的性能与协议边界

- collect每个slice扫描所有节点，并对每个eligible节点读取全部worker的64B缓存中的delta（parallel:79–80、CPP:316–317）。大树上这是O(eligible_nodes×workers)的串行维护，3人小树结果不能证明它在9人大树同样便宜。以后可独立评估仅在CI/保存/显式快照前同步计数，但必须先明确run返回时updates是否完整，不能悄悄改变API契约。
- Cache按64字节对齐，隔离了相邻node的cache line，但peer扫描某worker的delta仍与该worker更新同一Cache的epsilon/divisor共享缓存行。这是可能的缓存流量，不是同字段数据竞争。
- raw0/mA共享A的RMW现在为seq_cst，delta仍为relaxed load/store；桶数据通过锁提供较强的一致快照。它不是原Java默认VarHandle单cell原子写、plain读的完整并发语义重现。分片计数也不是原LongAdder内部布局/调度的逐位复刻。
- 只读检查不能证明吞吐收益、收敛稳定性或CI达标时间，需使用root正在进行的独立无插桩测试和后续策略/CI验证。
