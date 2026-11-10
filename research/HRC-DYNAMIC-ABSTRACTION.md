# 固定公共牌子树：动态抽象、各座位范围和机会抽样

2026-11-05。目标主 JAR：`net.holdemresources.calculator_4.1.0.202603231401.jar`，SHA-256 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。本批执行仅限 allowlist 中的牌张/映射/抽样数值类；未运行 HRC 应用、许可服务、`pg` 资源门控或原版求解器。实现输入为公共牌、用户范围与独立生成的映射；不读取存档策略作为初值。

## 已完成的证据

- 动态 key：216 个场景、240,300 个合法手牌 key，与原始字节码逐字节相同。
- 原动态 mapper：53 个场景、41,668,224 个映射元素，与独立 Python 的桶 ID、有效桶数和完整输出 SHA-256 一致。包括两种固定公共牌纹理的当前/下一街，及一个 flop 的所有 49×48 种 turn/river 序列，对 strict/balanced/relaxed 完整枚举。
- 生产 C++ `hrc_dynamic::Table`：53 个独立生成缓存，53,411,280 次查找，与上述原版审计过的完整映射相同；另外检查截断、额外尾部字节、无效 player-map index 三种拒绝控制。
- 原 `lw`、`lu` 与 Commons RNG：152 个抽样场景，对 Python/C++ 的 combo、公共牌、used mask、重抽次数、随机数调用次数及完整调用序列 hash 全部一致。包含不可能的联合范围：原版在 10,000 次尝试后响应取消、返回全 `-1`；独立实现在相同次数显式抛出资源限制。
- 16,384 桶资源子树压缩：两个固定 flop 的完整 turn/river 域共 25,469,808 个原始 mapper 元素、31,837,260 次生产 C++ 查询全部一致；turn 执行原 `oo.a` 工厂，river 的 `qa` 内联构造按静态事实在探针中复演，未执行 `qa` 本身。
- 单元测试：`tests/test_hrc_dynamic.py` 12 项、`tests/test_hrc_chance.py` 11 项、`tests/test_hrc_resource_dynamic.py` 4 项，共 27 项通过。

证据：[原动态对照](../reports/hrc-original-dynamic-validation.json)、[生产 C++ 映射](../reports/hrc-original-dynamic-native-validation.json)、[原机会抽样对照](../reports/hrc-original-chance-validation.json)、[资源子树压缩](../reports/hrc-original-resource-dynamic-validation.json)。这些是限定输入域的数值证据，不能据此宣称完整求解器或所有抽象 profile 等价。

## 原类、descriptor 与语义

以下均为静态事实，动态证据另按上面的矩阵限定。反编译文件路径相对 `analysis/hrc-deep/sources/`；方法 descriptor 已与 `bytecode-index.jsonl` 核对。

| 入口 | 源码锚点 | 已确认行为 |
| --- | --- | --- |
| `qa.a(JsonObject,pg):ok` | `0737/qa.java:111`，153/181/328 行 | 固定子树按 street 和 id 分配动态 mapper；`buckets=0` 使用 `op`。 |
| `os.<init>([J)V`、`os.a([JJ):ot` | `0877/os.java:7`、13 | 公共牌历史逐街细化花色等价组，新牌编码用此前组，而非仅最终 board。 |
| `ov.<init>([JILou;[[D)V` | `0886/ov.java:18` | 枚举剩余公共牌及 1326 手牌，排序 key，按每座位正权重支持分别压缩连续桶 ID。完整内部类型名为 `net/holdemresources/internal/ou`。 |
| `ov.a([JI)[I`、`ov.a(I)I` | `0886/ov.java:197`、206 | 每座位 1326 映射与各自有效桶数；不同座位不必相同。 |
| `or.<init>([J[[D)V` | `0887/or.java:14` | 当前街 perfect：先取正权重合法手牌的可达花色规范化 key，再允许所有具有可达 key 的物理手牌映射。 |
| `oq.<init>([J)V` | `0888/oq.java:13` | 下一街 perfect：将未来牌和 hole 联合规范化，额外保存该未来牌标签。 |
| `oo.<init>(Loi;I[[I)V`、`on.<init>([JLoo;I)V` | `0875/oo.java:12`、`0874/on.java:12` | per-player 可达桶压缩及固定前缀的下一张物理牌表。 |
| `op.a(I)I`、`op.a([JI)[I` | `0873/op.java:21`、41 | 空映射：桶数 0、映射 null；不是单桶。之前收益报告已纠正这个解释。 |

`ot.compareTo(Object)I` 调用 `Arrays.compare([J[J)I`，是 signed-long 数组字典序；独立实现按相同数值顺序排序，而非按字节序比较。`ls` 的 combo 顺序为 `high*(high-1)/2 + low`，每张牌索引 `rank*4+suit`。同名混淆字段必须按 `[I` 与 `[J` descriptor 区分。

strict 使用公共牌过程编码与完整规范化 hole mask。balanced 的 flop/turn/river 分别为 `ox/oz/oy`；relaxed 分别为 `oA/oC/oB`。源码锚点为 `0880/ox.java`、`0879/oz.java`、`0878/oy.java`、`0883/oA.java`、`0884/oC.java`、`0882/oB.java` 的 `a(J[JJ):ot`。这些函数按 hole 的低位牌先移除，再检查剩余 hole 的花色；因此第二张牌不会再满足“两张 hole 同花”的条件。独立实现保留这个实际位运算顺序，没有用理想化的牌型描述替代。

river relaxed `oB` 还具有特殊历史规则：river 之后不再细化花色组；若 river 的花色在 turn 已有至少两张，编码附加 `1L<<(suit+32)`，否则仅编码 rank。该规则在全部 flop→river runout 的原 key/桶 ID 对照中得到验证。

perfect 的零权重物理 combo 可能映射到由其他正权重 combo 产生的同一可达桶。**桶是否存在不能替代发牌范围过滤。** strict/balanced/relaxed 的 `ov` 则将该座位零权重 combo 直接置 `-1`。

## 固定范围发牌与 bunching

`lw.a([[DJ):lw`（`0707/lw.java:55`）对每个非 null 1326 范围先按 board 清零 blocker，再构建 `GuideTableDiscreteSampler.of(rng,weights,10.0)`。即使该范围原来均匀，也仍建立加权 sampler。范围为 null 的座位才在这里保留为均匀补发。

`lw.a([IJI)J`（130 行）按座位顺序独立抽样加权范围，遇到冲突立刻返回 `-1`。公开 `lw.a([IJILjava/util/function/BooleanSupplier;)J`（106 行）从最初 board mask 重试整个加权组。成功后再按座位顺序给 null sampler 或指定 skip target 发均匀合法 hole；`lu.a(LUniformRandomProvider;J)I`（`0706/lu.java:20`）用 `nextInt(1326)` 拒绝冲突 combo。

因此，忽略有限 PRNG 端点时，接受后的联合手牌分布为

`P(h_0,...,h_n | board, disjoint) ∝ ∏ range_i(h_i)`。

把某个前面座位的手牌固定，再仅让后面座位按剩余牌重新归一化，会改变这个分布。测试中枚举两个有限范围的 24 个等概率提案，其中 2 个因碰撞拒绝，另三个联合结果的质量为 4、6、12，验证了该差异。

`qa.a(JsonObject,kG):[[D`（`0737/qa.java:428`）读取 subtree 中每个座位的 range，并未用 `active` 筛除；相反，抽象构建在 135 行检查 `active`。这意味着弃牌玩家可无 bucket，但仍占用范围对应的两张死牌。`lq.a(lR,oj,[J,I):[D`（`0691/lq.java:91`）沿父路径提取该玩家的 reach range，遇到该玩家自己的行动时乘该行动策略并施加 board blockers（私有 `a([D[D[IJ)[D`，19 行）。本批发牌实现接受已经给定的每座位范围；未擅自从保存策略恢复初始训练值。

`lu.a(LUniformRandomProvider;[JJ[J)J`（`0706/lu.java:53`）保留已知 flop/turn/river，从未用牌中以 `nextInt(52)` 拒绝采样补齐余下街。所有实际座位的 hole（含 folded）先加入 used mask，随后才发未知公共牌。

`mn.b(qb,mf,lZ,BooleanSupplier,[J):mn`（`0034/mn.java:248`）使用上述 1326 范围与固定 board，并强制 worker mode 1。`mn` 的 case 1 在 120 行做一次联合发牌与 vector traversal。**mode 2 尚未因本批证据而视为完成**：其入口在 228 行，169 范围扩展后，当活跃行动玩家有非均匀范围时，148 行按每个目标玩家循环，目标手牌改为均匀抽取，标量 traversal 的初始权重为该目标的原 169 范围值。这与一次 mode-1 vector traversal 的训练计数及权重不同；本批只对 `lw` 的 skip-target 抽样原语做了 3 个场景验证，未验证完整 mode-2 worker。

Commons RNG 1.6 的 `GuideTableDiscreteSampler.sample()I`（已保存 `javap -c -p` 证据）选择首个 `CDF >= u`。累计采用顺序 double 加法、除以总和，最后一个 CDF 强制为 1。`u=0` 时若前导项权重为 0，原版可以返回 combo 0。本实现保留该有限 PRNG 端点；不能声称每个零权重手牌绝对不出现。该异常端点与普通正 u 的范围语义分别测试。

## 产品集成接口

Python 动态模块 `preflop_lab/hrc_dynamic.py`：

```python
mapping = prepare(prefix, street, mode, ranges,
                  max_seconds=120, max_map_bytes=1 << 30,
                  cancel_check=None)
mapping.effective        # 每座位有效桶数
mapping.map(history, combo_ids)
mapping.write(cache_path)
```

`prefix/history` 为累计 mask `[0,flop,turn?,river?]`，必须保留发牌历史；street 为 1/2/3。ranges 为每座位 1326 非负有限权重，**在映射 API 中 None 表示 inactive/no map**。相同正权重支持共享缓存，不以权重大小区分桶。mode 支持 strict/balanced/relaxed/perfect/none；none 输出空表，当前/下一街 perfect 支持，flop→river perfect 按原 routing 限制显式拒绝。

`native/hrc_dynamic.hpp` 提供不可变 `Table::read(path,max_bytes)`、`effective(player)`、`prefix()`、`bucket(player,combo,board_ptr,board_length=4)`。每个决策节点必须使用 **actor 对应 street 的 effective**；不能用全桌一个常量桶数。示例完整 rainbow flop→river：strict 2,542,512 桶、balanced 546,918、relaxed 189,034；需要事先估算节点存储并显式拒绝超过预算的任务，不能把这些数截断到 16,384。

缓存 `HRDYN001` 全为 little-endian：8-byte magic；5×u32 `{street,prefixLength,players,rowCount,uniqueMapCount}`；prefixLength×u64 board；players×i32 mapIndex（-1 为空）；players×u32 effective；每个 unique map 的 `rowCount×1326×i32` ID。rowCount 为 `52^(street+1-prefixLength)`，未来物理牌按 base-52 编码，无效重复牌行全 -1。资源 manifest 应记录 cache path、SHA-256、长度、前缀历史、模式、每座位支持 hash 与 effective。该文件完全从用户参数独立计算，没有 HRC proprietary bucket payload。

Python 发牌模块 `preflop_lab/hrc_chance.py`：

```python
sampler = ChanceSampler(ranges, board_history=(0,),
                        max_attempts=1_000_000,
                        max_random_calls=10_000_000)
deal = sampler.sample(rng, cancel_check=None)
# deal: combos, board_history完整4街, used_mask, attempts, random_calls
```

这里 ranges 必须包含全部实际座位，**在发牌 API 中 None 表示均匀座位，不能删除死牌**。`validated_ranges(ranges,players=None,board_mask=0)` 保留未缩放权重并清除 blockers，以免提前归一化改变 CDF 舍入。C++ 对应 `hrc_chance::Config`（空 vector row 表示均匀）、不可变 `Sampler`、`sample(next_int,next_double,cancel={},skip_player=-1)`。每个 worker 提供自己的随机回调；该模块不声称与 HRC 的 Xoshiro 随机流或多线程调度一致。

所有预算失败均为显式异常；不将不可能的范围偷偷改为均匀，也不返回部分牌局。独立取消检查比原版每 10,000 次联合失败更及时。`max_map_bytes` 限制的是输出映射载荷，NumPy key/排序临时数组会额外占用内存；不是进程 RSS 硬上限。动态构建取消为协作检查，一次 NumPy 排序期间不能立即中断。

## 正 bucket 参数的资源压缩分支

`qa.java:211` 对 turn、223 行对 river 只检查请求桶数是否为正，随后取对应街任意 `buckets>16000` 的资源。本地只有一个符合条件的 profile，即 16,384 桶；不是直接把输入的 256/1024 用作该子树的最终桶数。固定子树的 flop 正桶数则在 141 行被拒绝。

turn 路径调用原 `oo.a(Loi;J[[D):on`（`0875/oo.java:70`）：固定 flop，枚举所有 49 个合法 turn，取每座位正权重手牌可达的 base bucket，按数字从小到大压缩。river 的同样构造在 `qa.java:229` 内联，枚举固定 flop 后 49×48 个有序 runout，最终构建 `oo`。即使输入已知 turn 或 river，此资源分支仍用完整 fixed-flop 域建立编号和桶数；不能以当前较小 board 域重新压缩。零权重物理 combo 只要共享可达 base bucket，仍可能映射到合法桶，与前述 perfect 路径类似。

独立模块 `preflop_lab/hrc_resource_dynamic.py` 提供：

```python
manifest = prepare_profile_resources(plugins, output, board_cache=existing_board_index_cache)
table = ProfileTable(output, street)  # street2或3
mapping = prepare_resource(full_history, street, active_player_ranges, table,
                           max_seconds=120, max_map_bytes=1 << 30)
```

返回相同 `DynamicAbstraction` 和 `HRDYN001`，但 `mapping.prefix` 有意仅为 `[0,flop]`。实际固定 board 仍由发牌配置保留。资源读取用独立花色规范化、列压缩和 NumPy 映射；训练不加载原类。输出范围支持相同的座位共用 map。

本地 profile 原始解压数据 hash：turn `741bd150aec01478de0204b90775758d730248df0458d8d4a3a534bc90deb8a7`，37,070,592 字节；river `40624adecddaa224acf4cf2cf59e1e6f5e92d2080099d2465beac417cb6393a4`，290,700,358 字节。资源 JAR SHA `731b654ead51b5b49c91accee59f1a8bfe9471f4597d3104213cc7c8b27582ec`；通用 Brotli decoder SHA `615c0c3efef990d77831104475fba6a1f7971388691d4bad1471ad84101f6d52`。完整 manifest 存于 `.research-cache/subtree-resources/manifest.json`，包含压缩成员 hash 和独立 canonical-board 索引 hash。该缓存含用户本地专有数据；不能把它或依赖它产生的资源映射作为独立产品资产分发。

`OriginalResourceDynamicProbe` 复用已审核的 `oh/ol/lo/ls/og/lt/oD/om/oi` 数值 reader allowlist，仅增加 `oo/on`；依赖仅为固定 hash 的 Eclipse Collections。turn 执行原工厂；river 可达 ID 集合是探针按静态 `qa` 重现后传给原 `oo`，全部 base row 和最终映射仍执行原代码。这比声称完整 `qa` 流程已运行更精确。两个 flop 的所有物理 runout/1326 combo/4 个非空范围已全域比较，另一个 inactive 座位在 C++ 查询中验证 -1。bucket 有效数分别为 turn `[1360,1118,0,60,0]`、river `[1894,1767,0,234,0]`；另一单色 flop 为 turn `[1045,808,0,30,0]`、river `[2661,2412,0,244,0]`。

## 原探针执行边界与可复现性

`OriginalDynamicProbe` 只允许加载 `oi/ou/ot/os/ow/ox/oz/oy/oA/oC/oB/ov/or/oq/oo/on/op/og/lt/ls`。`og` 的真实 `<clinit>` 引用 `lt`，已经审核，不依据反编译省略的初始化表达式猜测无依赖。资源读取函数被拒绝。

`OriginalChanceProbe` 允许 HRC `lw/lu/ls/lt` 和哈希固定的 Commons RNG 1.6 jar；实际加载的 HRC 类只有 `lw/lu/ls`。`lu.<clinit>` 的 RandomSource 工厂仅创建 supplier，探针不调用随机工厂，所有输入来自显式脚本。探针直接注入原 GuideTable sampler；范围 blockers 由测试适配层显式处理，没有声称原 `lw` 两个公开 factory 或 `lq` 全方法均被执行。它们的 routing/blocker 行为依据上述静态锚点。

依赖哈希：client-api `9b9cc84858789046b03636216aff2cf8062711a1d68478746e2a8cfc202be429`；sampling `87c53aa15fd3a764a70d2253f417e0101af00679cb62c25d59a703a0f15675a8`；core `52653f3032c49a2b2b77872a9e2ad1f570127933824b84d0bb8cd8c0e18a1520`；simple `3a96ef9bc03b79ec336c685b7f59177df5996f9350e4cf95a1ebc2d926fbf06b`。报告逐项记录实际加载 class SHA、输入 TSV SHA、源码 hash、编译/执行命令及全部结果。

复现命令：

```powershell
.venv/Scripts/python.exe scripts/validate-hrc-dynamic.py --full-river
.venv/Scripts/python.exe scripts/validate-hrc-dynamic-native.py
.venv/Scripts/python.exe scripts/validate-hrc-chance.py
.venv/Scripts/python.exe scripts/validate-hrc-resource-dynamic.py
.venv/Scripts/python.exe -m pytest tests/test_hrc_dynamic.py tests/test_hrc_chance.py tests/test_hrc_resource_dynamic.py -q
```

输入均由脚本再生，删除 `analysis` 后仍可复现；需要用户已安装且 SHA 相符的原始 jar 作验证 oracle。生产映射与发牌运行不依赖这些原数值类。

## 明确未完成/未知

本批没有执行完整 `mn` worker mode 2，也没有验证动态子树训练收敛、行动树生成或整份 `.hrcz` 导入导出。资源分支的 `qa` 路由及 river 内联集合构造仍是静态依据加隔离复演，未执行原应用配置链。后续独立批次已执行原 reach-range 决策节点递归和范围文本回读，详见 [HRC-SUBTREE-REACH.md](HRC-SUBTREE-REACH.md)；该新增证据不扩大本报告的 worker 覆盖范围。HRC 新版本、其他资源 profile、多线程竞争与随机 seed 流均不在上述数值一致结论内。主应用接线由其他任务负责，不能将本报告的模块交付自动等同于 UI 已支持。
