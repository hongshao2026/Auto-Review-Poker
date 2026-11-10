# 独立内核：训练控制、扩展存储与检查点迁移

本文记录实际接入 `native/hrc_research_solver.cpp` 和
`preflop_lab/hrc_native.py` 的功能。训练使用独立实现和从零状态，原版类仅由隔离探针用于数值对照。
树可来自独立生成器，或显式标注的原存档拓扑；不会读取原存档策略作为训练初值。

## 运行控制

`run(tree, resource_dir, samples, seed, output_dir, ...)` 的 `samples` 是累计发牌硬上限，范围 0–1,000,000,000。
`mode='v3'|'v4'` 选择已审计的实际遍历分支，默认 v4。
`reset_regret` 和 `reset_average` 分别执行原版的 `1e-20` 缩放/计数重置，不是显示层遮罩。
原始遗憾、平均量、频率约束的 dual edges、缓存计数及随机数状态都参与真实训练。

可选停止参数不进入树 identity，因而改变下一段的预算不影响正常续跑：

| 参数 | 语义 |
|---|---|
| `stop_after_seconds` | 训练阶段的秒数目标，0.1–86400 |
| `target_ci` | 正的近期策略漂移目标，必须显式启用 `ci.enabled` |
| `hard_seconds` | 训练阶段的秒数硬上限，0.1–86400 |
| `cancel_check` | Python 回调，写入本任务目录的取消标记 |

FGS 初始化不计入训练秒数；FGS 自身有独立状态数、迭代数、计算秒数预算和递归取消检查。
正常停止分别报告 `sample_target`、`time_target`、`ci_target`、`sample_cap`、`hard_time`、`cancelled`。
有时间/CI目标但只达到样本硬上限时，`target_reached=false`；不会把预算结束当作 CI 达标。
CI 是原 `mq` 的近期策略漂移量，不是 exploitability，也不是统计置信区间。

CI 按原版规则至少间隔 15000ms 检查，按真实 bucket 显示策略和节点更新数计算。
采集会 flush 所选节点的缓存计数，属于原数值时序的一部分；未启用 CI 时不会偷偷执行该刷新。
新 worker 恢复数值检查点后建立新的 CI 历史，符合原 `mn` 新建 `mq` 的行为。

正常取消保存已完成的边界。FGS 在一次遍历内部取消或耗尽预算时，尚未完成的遍历不得当作样本保存：
保留最近完整边界检查点，报告 `rolled_back_to_checkpoint` 或 `resource_limit`，不伪装训练成功。
常规自动检查点间隔为 1m；最坏情况下回滚可能损失该段已完成但尚未保存的工作。

## 策略与存储配置

以下是 compact 输入，不是界面说明文字：

```json
{
  "stores": {"version": 1, "street_formats": [23, 27, 31, 31]},
  "policies": {
    "version": 1,
    "nodes": [
      {"node_id": 0, "locks": [[0.3, 0.3], null]},
      {"node_id": 2, "frequency": {"targets": [0.4, null], "edges": [0.0, 0.2]}}
    ]
  },
  "ci": {"enabled": true}
}
```

示例锁行的两个值仅表示一个两桶测试节点；真实锁行长度必须等于该节点 bucket 数。
每节点只能选择逐桶锁或频率约束其中之一。格式 25 不提供逐桶平均存储，不能直接加逐桶锁。
全部动作锁定时每桶之和必须为 1；特殊虚拟 fold 分支的 action0 不允许锁定。

| 格式 | raw layout（K动作，H桶） | 显示策略 | 相对 EV |
|---|---|---|---|
| 23 | `[cachedN, H×(R[K], D, A[K])]` | bucket A 归一化 | `(R[a]-R[0])/D` |
| 25 | `[N, sharedA[K], H×R[K]]` | bucket 正遗憾归一化 | 不提供 |
| 27 | `[cachedN, sharedA[K], H×(R[K], A[K])]` | bucket A 归一化 | 不提供 |
| 31 | `[cachedN, cachedSharedA[K], H×(R[K], D, A[K])]` | bucket A 归一化 | `(R[a]-R[0])/D` |
| 63 | `[cachedN, cachedSharedA[K], H×(R[K], D, A[K])]` | bucket A 归一化 | `(R[a]-R[0])/D` |

格式 63 是独立的频率约束学习器，并非普通更新后裁剪频率。
它的 R/D 更新不乘普通存储的局部 t；平均量仍累积 t×p。
具体公式见 `HRC-POLICY-CI.md`，原始扩展存储证据见
`reports/hrc-original-extended-store-validation.json`。

27/31 沿用原 `mB`/`mD` 缓存 t 更新逻辑；bucket A 不乘遍历 marker，shared A 仅在 marker>0 时累积。
31 的真实 shared adders 单独保存。原 `mD` 平均量折扣会从可能陈旧的 header 重建真实计数和 adders，
本实现保留这一行为，不暗中先 flush 来改变原数学语义。
原 `mw` 分块行边界只影响物理布局；本检查点用相同数值顺序的连续数组，未仿造 Java 对象块。

## 迁移不是普通续跑

默认 `checkpoint_migration='reject'`：树 identity、存储模式、v3/v4必须与检查点一致。
改变策略配置、开启 CI、调整存储或切换算法时，需要在**新输出目录**中明确选择
`checkpoint_migration='preserve'` 或 `'reset'`。源检查点及元数据保持不变。

迁移实现 `preflop_lab/hrc_checkpoint.py:migrate_checkpoint` 逐项验证源树身份、样本数、节点形状、
格式标签、偏移、真实计数和文件完整长度。只允许 policies/stores/ci 变化；筹码、拓扑、效用、FGS、
抽象定义或其他结构字段变化即拒绝，即使请求 reset 也不能把另一博弈的 RNG/在线回报伪装为合法续跑。

| 转换 | preserve 行为 |
|---|---|
| 同存储增加、修改、移除逐桶锁 | 保留底层 R/D/A，下一次更新使用新锁 |
| 格式 25→27 | 原 `mB.a(mA)`：复制遗憾/共享平均/计数，以当前正遗憾策略初始化每桶 A |
| 已有 63 修改 targets/edges | 原 `fi` 路径先 flush，再保留 R/D/A/极值/计数，重设 dual edges |
| 63→原始底层 23/31 | 原 `mz.a():mx`：flush 后经过 float32 序列化，23 去掉 shared header |
| 其他改变存储的转换 | 拒绝 preserve，要求显式 reset |

reset 只重置受配置变化影响的节点，其他节点仍保留。23→63 遵循原 factory 的 float32 拷贝后
`1e-20` reset：并非精确零；原 R/D/A 残量和新的 targets/edges 的 float32 量化都保留。
其他未证明可保留的转换明确使用全新零存储，并在 `migration.json` 中注明。
对同一配置执行全局 reset 应使用 `reset_regret`/`reset_average`，不是 migration reset。

迁移记录每个变更节点的前后格式、原因、float量化、计数重置、源哈希、新身份和是否切换 v3/v4。
保留累计发牌数、RNG 状态及在线 root sum；若切换模式或重置学习量，在线 root sum 因而混合了不同阶段，
仍然不能解释为最终策略的独立 EV 评估。

## 二进制协议

默认旧输入仍保持 HRTREE01/02/03 字节；启用扩展时使用 HRTREE04。
04 在原 header/初始筹码后的 flags 为：equity=1、dead_money=2、policies=4、CI=8、FGS=16、stores=32、rake=64、chance/dynamic=128、原档 float32 policy 来源=256。
256 不增加 payload，只用于有 `import_provenance.format='hrcz'` 的已验证源档，允许锁/目标的 float32 舍入容差；普通新配置仍严格校验。详见 `HRC-HRCZ-STORAGE.md`。
stores 在 flags 后、node headers 前写四个 uint32。
policy/FGS 的顺序为普通树终局、equity、policy、FGS；FGS 机会资源由 resource_dir 相对文件名找到，
绝对路径不进入树身份。FGS 的 chance hash/bytes 保留在便携 compact 元数据。

rake=64 时，每个终局在 folded mask 和可选 dead_money 后追加 `street:i32, raise_count:i32`；
FGS段之后追加 `mode:u32, fraction:f64, cap:i64`；若有 chance/dynamic 扩展，它在 rake 段之后。
rake 与 monetary/FGS 不能同时启用。详见下一节。

最新保存格式 HRSOLV03，兼容读取 HRSOLV01 和 HRSOLV02：

```
magic[8], identity:u64, samples:u64, nodes:u32, players:u32, v4:u32,
rng[4]:u64, root_sum[players]:f64
each node:
  updates:u64, format:u32, visits[buckets]:u64, raw[raw_count]:f64
  if format31: actual_shared[K]:f64
  if format63:
    minimum:f64, maximum:f64,
    cached_edges[K], actual_edges[K], actual_shared[K], runtime_targets[K]:f64
```

01 没有每节点 format 和扩展尾部。02 有 format，63 尾部不含 targets；读取02时使用原 compact targets。
03 单独保存运行时 targets，是因为原23→63 factory 将新 target 量化为 float32，而已有63的目标编辑不量化。
例如配置 0.4 的运行值可能为 0.4000000059604645；丢掉这一运行状态会让断点恢复悄悄改变轨迹。

原档导入仍用03，updates 保留加载的原始舍入时钟、visits/samples 从0计新增；
index 的 `imported_updates_baseline=updates-sum(visits)` 标记未知历史基准，原 float32 counter 位于 compact provenance。
index 新增 `utility_baseline`（ChipEV 为原生 BB、money 为金额）；FGS 尚未完成初始计算则为 null。
`index.json.targets` 始终显示真实运行值；频率额外段偏移之后 `8*(2+3K)` 就是 targets。

## 验证与范围

`tests/test_hrc_checkpoint.py` 直接使用隔离执行原版方法保留的输出，验证 enable/disable/target edit/25→27，
并实际调用生产 launcher/native 检查锁定对平均量的影响、27/31续跑逐字节一致、目标量化的恢复、
旧02兼容、源文件不覆盖和跨博弈拒绝。
`tests/test_hrc_native_features.py` 验证 v3/v4、01兼容、频率状态恢复、原 reset、实际15秒 CI目标、
秒数停止及 FGS 实际终局与资源失败。

复现：

```
.venv\Scripts\python.exe -m pytest tests/test_hrc_checkpoint.py tests/test_hrc_kernel.py tests/test_hrc_native_features.py -q
.venv\Scripts\python.exe scripts/validate-hrc-nested-traversal.py
```

原存储证据为顺序执行的独立数值比较；没有声称复刻原 Java 多线程竞争、weak-CAS 偶发失败、
原随机数流或 GUI 墙钟刷新时序。CI、FGS、赏金和存储迁移各自的有限证据不等于全应用逐行为等价证明。

本批执行结果：上述三个 pytest 文件 **68 passed，17.98s**；嵌套遍历原字节码审计
200案例、3200快照、136960个数值，最大误差0。审计记录及当前源哈希在
`reports/hrc-original-nested-traversal-validation.json`。

另外，独立复核探针直接 include 生产主文件并调用 `Node`，对27/31的201个实际 update/reset/flush 操作
逐步比较 raw SHA、计数与 shared adders，最大误差0；见
`reports/hrc-original-extended-store-native-validation.json` 和 `HRC-EXTENDED-STORES.md`。
该探针没有把尚未暴露的通用折扣或序列化操作复制一遍后冒充生产代码验证。

## 现金局抽水实际接线

`compact.rake={"mode":"nfnd"|"gg"|"full", "fraction":0..1, "cap":内部整数筹码}`。
只支持 ChipEV，各 terminal 必须显式带上 street 和 raise_count。cap 与 remaining/paid/dead_money
同单位，例如当前基准内部10000=1BB；fraction 是比例，不能把百分数5直接当作5%。
输入、构建摘要和 identity 均保存该配置；切换费率属于另一收益模型，不能借策略迁移绕过身份检查。

仅配置 rake 时启用 `hrc_settlement::settle` 分支。它按真实七牌牌力先排序赢家，再依原版贡献阈值
结算并消耗全局封顶额；不能在普通升序侧池循环中先扣费，否则封顶额可能被不同赢家的池占用。
原始 remaining/paid/folded/dead_money 和终局上下文都传入此函数，结果为
`(final_stack-initial_stack)/big_blind`。无 rake 配置仍执行原有终局路径。
抽水后的收益之和可小于0，这是移出牌桌的费用，不应被强行归一为零和收益。

NFND、GG、Full 的触发、四舍五入、整池扣费封顶及平局余数依据原 `lC→lK→lH` 方法，
由 `reports/hrc-original-rake-validation.json` 保留1240配置证据。
生产 `Engine::terminal` 另用同1240输入验证净BB接线：1148合法结果逐项完全相同，
92个原版拒绝的极端域也拒绝，见 `reports/hrc-native-rake-integration-validation.json`。
其中包含合成终局，不能称所有输入均可由正常行动序列到达。

`tests/test_hrc_native_rake.py` 另实际发牌并训练NFND/GG/Full，验证400→1000续跑与连续1000逐字节相同，
抽水产生负收益总和，零费率与旧HU路径R/D/A一致，错误费率/单位类型/缺失上下文在启动前拒绝。
这15项集成检查通过；七牌评估与原抽象桶的验证仍见既有独立卡牌报告。

## 固定公共牌与逐座位动态抽象接线

详见 [HRC-NATIVE-DYNAMIC.md](HRC-NATIVE-DYNAMIC.md)。生产 `Engine::deal/hand` 已使用独立
`hrc_chance::Sampler` 和 `hrc_dynamic::Table`。输入明确是 mode1；缺少某个决策街的动态表会拒绝，
不会改用固定全局1024/256桶。无 chance/dynamic 键的旧路径保留原发牌与查表顺序。
新运行预算 `max_memory_bytes` 为1MiB至4GiB，默认1GiB，不进入树 identity。
它是已知节点、数组、策略/CI及抽象表分配的保守估计上限；并非操作系统总RSS硬限制，
FGS递归缓存仍由FGS自己的资源控制约束。

本次专门集成检查42项通过，完整保存证据为 `reports/hrc-native-dynamic-validation.json`。
此外旧kernel/features/rake及本批初始35项合计100项通过，旧checkpoint18项通过；
原始嵌套遍历对照仍为200案例、3200快照、136960数值、最大误差0。
