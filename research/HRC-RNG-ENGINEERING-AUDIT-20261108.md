# HRC RNG 与策略读取工程审计（2026-11-08）

结论：原版 Commons RNG 的 bounded-int 工程路线与我们的不同，但不能直接替换后声称保持现有随机轨迹。**我们冻结版本发牌 `bound(52)` 已经被优化为乘法/移位，真正仍保留动态除法的是 scalar 的 `depth+2` 和探索分支的 `k`。** 原版 special 且两行动时直接写固定策略，无 regret 读取；普通两行动仅一个正 regret 时，原字节码仍执行两次浮点除法。

本轮仅静态读取原安装依赖/JAR、生成 javap 和冻结独立内核的汇编；未运行训练、未操作 GUI、未修改生产 CPP/header。观察值、推断和未知分别标明。证据目录：`analysis/hrc-deep/rng-engineering-20261108/`；文件身份及代码生成命令见其中 `identity.json`。

## 原版实际调用链（observed）

安装中的依赖位于 `D:/Program Files/HRC/plugins/net.holdemresources.calculator.mavendependencies_0.2.0/org.apache.commons/`，`commons-rng-client-api-1.6.jar`、`commons-rng-core-1.6.jar`、`commons-rng-simple-1.6.jar`。插件 MANIFEST 的 Bundle-ClassPath 与导出均明确为1.6。SHA256已记录于 identity.json。

1. HRC `lu.b()Lorg/apache/commons/rng/UniformRandomProvider;` 调 `RandomSource.XO_SHI_RO_256_SS.create()`；`analysis/hrc-deep/solver/0706/bytecode.txt:349–354`。
2. `ProviderBuilder$RandomSourceInternal` 该枚举指定 `XoShiRo256StarStar`，本轮 `ProviderBuilder-RandomSourceInternal.txt:840–850`。
3. 该类继承 `AbstractXoShiRo256 → LongProvider → BaseProvider`。`XoShiRo256StarStar.txt:2`，`AbstractXoShiRo256.txt:2`，`LongProvider.txt:2`。`BaseProvider.txt` 没有 override `nextInt`/`nextLong`/`nextDouble`。
4. bounded `nextInt(I)I` 使用 `UniformRandomProvider` 默认实现，先验证 n>0，再调用 `UniformRandomProviderSupport.nextInt(provider,n)`；`UniformRandomProvider.txt:39–47`。

**精确 bounded 算法**，`UniformRandomProviderSupport.txt:375–423`：

```
x = unsigned32(provider.nextInt())
m = x*n                         # 64位乘积
low = m & 0xffffffff
if low < n:
    threshold = 2^32 % n
    while low < threshold:
        x = unsigned32(provider.nextInt())
        m = x*n
        low = m & 0xffffffff
return m >>> 32
```

BCI13 是 `lmul`，仅 BCI35 是 `lrem`，BCI74 是右移32。不能把它描述为“每次取模”。小 n 下门槛分支很少进入；确切概率受 n 与2^32的公因子影响，不能对所有 n 简写成 n/2^32。它仍有拒绝重抽，不可删除以换速度。

**容易漏掉的32位缓存**：`LongProvider.nextInt()I` 在 `LongProvider.txt:121–150`，初始 `intSource=-1`。缓存空时推进一次64位 `next()`，返回低32位，并缓存高32位；下次返回缓存高32位、标为空，不推进64位状态。`nextLong()J` :114–119 直接 `next()`；`UniformRandomProvider.nextDouble()D` :133–143 取 `nextLong()>>>11 * 2^-53`，不清除上述 intSource。因此混合 int/double 调用仍可能消费此前64位输出留下的半字。

我们的 `Random::integer()` 每次推进一次64位并取高32位，`bound(n)` 也每次至少推进一次64位。虽然核心输出家族都是 xoshiro256**，两者的 bounded映射、32位复用、种子生成、混合调用后的状态进度不一致。实现原路径需要扩展 RNG 状态/检查点协议，不能只替换一次 `%`。

## 原 HRC 哪些位置用整数随机数

| 调用点 | n/语义 | 证据 |
|---|---|---|
| `lu.a(provider,int[],long)` | 洞牌按1326个combo抽样，冲突则重抽 | `sources/0706/lu.java:30–42`；bytecode:59–99 |
| `lu.a(provider,int,long)` | 公共牌按52张抽样，冲突则重抽 | source:75–91；bytecode:259–291 |
| `lV.a(double[],int,int,double)` | 每次先 nextDouble 探索门；探索成功再 nextInt(actionCount)；否则确定策略无需第二个double，混合策略再抽double | `sources/0029/lV.java:30–49`；`solver/0029/bytecode.txt:69–135` |
| `lV` 的默认 skip predicate | `nextInt(2+d)==0`，d是被跳过的target决策数 | source:9；bytecode:236–249 |
| `ma.a(D)Z` | 无界signed `nextInt() % floor(sqrt(t))==0`，用于计数缓存刷新 | `sources/0011/ma.java:22–23`；`solver/0011/bytecode.txt:43–59` |

`lu` 的两个同名 `ls.a` 字段不要混淆：字节码 `<clinit>` 明确 `a:I` 取 `ls.a:[I` 长度1326，`b:I` 取 `ls.a:[J` 长度52（`solver/0706/bytecode.txt:8–22`，数组构造 `sources/0708/ls.java:8–21`）。

原洞牌每座位直接抽一个combo，我们当前逐张抽两个card再编码combo。这在排除冲突后的均匀分布可以一致，但调用数量和单次流当然不一致。ma刷新是signed整数余数判零，不是 bounded均匀抽样；不能将它不加分析地换成 `bound(divisor)==0`。

## 独立内核的实际汇编（observed）

完整冻结翻译单元：`.research-cache/throughput-architecture-20261107/baseline/hrc_research_solver.cpp`，包含该目录冻结headers，使用本地 Zig/Clang：`-O3 -std=c++17 -ffp-contract=off -g0 -S -masm=intel`。输出 `frozen-engine-O3.s`，不是仅靠孤立表达式推测。SHA与flags已存 identity.json。

源 `Random::bound` 有阈值 `(uint64_t(0)-n)%n` 和返回 `v%n` 两个余数表达式；**不能据此声称所有调用都有两条硬件64位除法**。

| 实际调用 | 冻结汇编锚点 | 结论 |
|---|---|---|
| `Engine::deal()` 中 `bound(52)` | 函数:88690；magic常数:88790；`cmp rdx,16` :88818；`mulx/shr/imul/sub` :88825–88828 | 阈值已折叠16，`%52` 为常量乘法/移位。该函数没有整数div。保留随机数低于16的拒绝分支。 |
| `Engine::scalar()` 中 `bound(depth+2)` | :7803–7816 计算阈值；:7843–7853 返回余数 | 动态n保留两组div。每组有64/32位分支；通常走64位，不应把同组两条备选div加成四次执行。 |
| `Engine::sample()` 探索时 `bound(k)` | :39521–39529 与 :39602–39613 | 同样两组动态div；仅探索分支使用，不是每个sample都执行。 |

另保留了最小表达式代码生成 `bounded-remainder-codegen.cpp/.s`，用于解释常量2直接AND、常量52乘法的原因。正式结论以上述完整冻结CPP为依据；后续代码/flags/编译器变化需重新检查。

**inferred 优先级**：若 scalar skip 大量集中在 d=0/1/2，可对 n=2/3/4 做保留原映射的专门化，收益可能比继续“优化52取模”更实际。**unknown**：没有本轮热调用n直方图、CPU cycles/profile，不能给出这个瓶颈的耗时百分比或加速倍数。

## 保持现有流的优化与改变流的优化

可在数值/RNG序列上保持当前内核：

- n为2的幂时，阈值为0，`next() & (n-1)` 与原映射一致；**n=1也必须消耗一次 next()**，不能直接返回0。scripted路径保持原计数与分支。
- 对测得常见的 n，使用模板/常量 switch，使编译器生成精确常量除法；或预计算精确拒绝阈值。必须保留接受条件、原raw draw数量、输出余数与所有调用顺序。
- signed `integer()%divisor` 的优化要保留signed32值与判零语义；其 divisor不同于bounded n，不要合并统计或替换。

会改变流、必须另标算法/RNG协议而非声称checkpoint等价：

- 将64位取余映射换成乘高位映射，即使两者均匀；
- 仿原版复用32位半字、改combo级发牌、换种子扩展器；
- 删除“很少发生”的拒绝分支、探索门或1% special分支；
- 仅因策略确定就省掉探索门的 nextDouble；探索仍可能选择不同动作。

验收应包括边界raw draw（阈值前/等于阈值、0、2^64-1）、每个实际n、脚本路径、连续混合 `unit/integer/bound` 的输出和最终4字状态一致，以及旧/新单线程完整checkpoint逐位对照。若采用原32位缓存，额外状态也要进入恢复协议。

## 最小侵入的 n 分布测量方案（未在本轮执行）

只在独立 profiling build 插桩，不改正常生产路径：

1. 每个 worker 的 Random 添加固定 `uint64_t bounded_hist[256]` 与大n溢出计数，入口按n累加；不要每次做 map 分配或全局atomic。
2. 分开记录 callsite：deck、exploration、scalar_skip、chance/range。可在调用端记录后调用原bound；不用额外抽样来选择要记录的调用。
3. 对内部拒绝循环额外记录 raw draw/rejection 次数；物理牌冲突的重抽是外部loop，另计，避免误认为bounded拒绝。
4. 单独记录 `integer()`刷新divisor分布、Node epsilon缓存命中/未命中、normalization的k/special/锁/单positive分布。
5. 只在worker停稳后归并，输出计数；同时确认相同seed单线程原checkpoint仍逐位一致。采样序列改变的多线程调度波动不能用来做严格轨迹对照。性能评估须使用未插桩版本，计数版不能直接当吞吐结果。

## Node 探索缓存与 fixed-policy 条件

**observed：当前 Node 已有epsilon缓存**，主CPP `Node::exploration_probability` :93–94。键是 `storage()[0]` 的缓存counter，不是真实 `updates`。原版 `lV` 每次按传入counter计算 `1/sqrt(counter+10000)`；mE真实LongAdder和缓存counter不同。把cache键改成updates会改变探索概率。

当前缓存一般在choose的node mutex内使用；若为了少锁而搬出去，两个mutable double缓存字段也需要遵守C++并发内存模型，不能裸并发写。mA计数每更新改变，缓存命中模式会与mE不同；尚未测比例。把比较改成平方不等式或近似sqrt可能改变边界舍入，不应叫逐位等价。

**原版两行动归一化：**

- 普通 `mv.a([DI[DI)V` 先max(regret,0)，和>0后两次除法。即使仅一个为正也没有显式跳转到[0,1]；`sources/0016/mv.java:45–55`，`solver/0016/bytecode.txt:105–169`，BCI47/57为 `ddiv`。
- special 分派 `mv.b([DII[DI)V` 的k==2在读regret之前直接输出[0,1]；源码 :28–36，字节码 :61–103，BCI43/50分别0/1常量。
- 当前 `normalize` 先通用循环读regret，再判断special/k2；可将这个分支提前且保留其余调用。**不是 `n.special==2` 即可**：special2仅表示第二子节点仍是decision，仍可能k>2；真正条件是 `special>0 && k==2`。

不带active锁的普通存储，该固定策略可避免regret读取；frequency存储在special+k2时best从1开始且仅剩一个候选，也必为[0,1]（`native/hrc_policy.hpp:120–124`），但应独立验证该路径。

**active BucketLocks不能套用这条捷径**。只锁action1=.3时 compose可返回[.7,.3]；`native/hrc_policy.hpp:41–50` 对 `n==actions-1` 分配剩余质量，未承诺fold固定0。不能因special+k2绕过锁。父层仍需策略P来更新regret/平均，即使探索动作是均匀选的，也不能一般性地省掉P计算。

普通单positive可以做独立优化，但与“原版已这样写”不同：仅在总和为有限正数且恰一正值时将该项置1、其余保留已计算零值。不要将负零强制改正零而声称逐位相同；NaN/Inf要保持原分支（Inf/Inf并不是1）。应覆盖这些边界，并保留：探索门unit、探索命中后的bound(k)、非确定策略的第二次unit、target skip的bound(depth+2)、special2对应1%分支unit、mE刷新integer，原有先后顺序全部不动。

目前未发现这批建议必须改变求解公式，但这不构成无bug证明，也未证明全部原工程已恢复。可以先做**保留当前流**的窄优化，用checkpoint等价证明语义，再以无插桩构建做短吞吐测量；原Commons RNG兼容应作为独立协议工作。
