# 原版默认存储与遍历复核，2026-11-08

本轮最有价值的结论是：**原版默认存储按单个 double 做原子加法，却不提供整节点一致读；我们当前 NodeMutex 提供更强的节点级保护。二者不能通过删锁、裸读写 double 来互换，也不能只凭原版没有节点锁就判断它更快。** 较小且可单独验收的候选是两/三行动专门化，以及每 worker 的递归临时缓冲区。收益均未在本轮测量。

本轮只读取安装 JAR、同身份既有反编译/字节码及生产源文件，没有执行原程序、训练或修改生产代码，也未切换共享 REA target。按 reverse-engineer-anything v49 的证据范围复用原分析。证据固定在 `analysis/hrc-deep/round3-storage-20261108/`；其中 `identity.json` 保存原 JAR SHA256、来源文件及生产快照哈希。原 JAR SHA256 为 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。类按 ordinal 分目录，避免 Windows 将 `ma` 与 `mA` 混为一条路径。

下文相对证据锚点均位于上述新目录。observed 指字节码或现有源快照直接支持；inferred 指有明确条件的工程判断；unknown 指尚无该层观测。

## 1. 默认布局与真实更新公式（observed）

`mf.<init>(Lmf;Ljava/util/List;[Lmj;[IIII)V` 在 street==0 创建 `mE`，其他街创建 `mA`：`0013/mf.java:24–29`。这不覆盖手动切换的27/31、范围锁或频率存储。

令 B 为桶数、K 为行动数、h 为当前桶，P 为策略，Q 为每行动标量收益，w 为 regret 权重，z 为平均策略 marker；`V=sum(P[a]*Q[a] for P[a]>0)`，严格按行动升序累加。

| 默认存储 | double 布局 | 更新 |
|---|---|---|
| `mE`, format23 | `raw[0]` 缓存计数；每桶 `[R(K), D(1), A(K)]`，总长 `1+B*(2K+1)` | 每个行动 `R+=w*t*(Q−V)`、`A+=t*P`；随后 `D+=w*t`。**A 不乘 z，也不受 z==0 抑制。** |
| `mA`, format25 | `raw[0]` 计数；全节点共享 `A(K)`；每桶 `R(K)`，总长 `1+(B+1)*K` | 每行动 `R+=w*t*(Q−V)`；仅 z>0 时共享 `A+=z*t*P`。没有逐桶 D 或逐桶 A。 |

两个更新方法 descriptor 都是 `(Lnet/holdemresources/internal/ma;[DIIDD)V`。源码：`0021/mE.java:48–75`、`0026/mA.java:40–65`。字节码：mE `0021/bytecode.txt:119–257`；mA `0026/bytecode.txt:71–189`。形式参数 double[] 中 P 与 Q 相邻，并非两个新数组。

当 w<=0 时直接返回；不要把它误写成 z<=0 就跳过整个更新。当前生产快照 `hrc_research_solver.cpp:125–136` 的默认23/25路径保持这一差别。普通模式直接调用时 w=1（`:320–322`）。原 `lV.a:D` 初始化为1；全主 JAR 静态字段写索引只发现其构造器这一个直接写点，不据此排除反射或未分析依赖。

## 2. mE 的计数不是每次同步求和（observed）

`mE` 有 `LongAdder`，每个有效更新执行以下顺序：

1. `LongAdder.increment()`。
2. plain 读取 raw[0]，令本次 local `t=1+raw[0]`。
3. `ma.a(D)Z` 消耗一个 signed `nextInt()`；条件为 `nextInt() % floor(sqrt(t)) == 0`。
4. 命中时先再次 plain 读取 raw[0] 作为 CAS expected，再取 `LongAdder.doubleValue()`，**把它赋给本次 local t**，再对 raw[0] 做一次 `weakCompareAndSet`。
5. 丢弃 CAS 布尔结果，没有重试。即使 CAS 失败，本次更新也继续用步骤4取得的 local t。

精确锚点：`0021/bytecode.txt:180–208`，BCI98 increment；107 daload；114刷新判定；133再次daload；138 doubleValue；142 dstore local；144 weakCAS；147 pop。`0011/ma.java:22–23`、`0011/bytecode.txt:44–59` 明确 signed remainder，不是 bounded random。

因此不能把缓存刷新等同于 `raw[0]=++updates`，不能每次算 LongAdder sum，也不能只在 CAS 成功时更新 local t。原版以稀疏刷新减少 sum 的成本；缓存计数也用于探索概率，不能用真实 updates 替代其键。

`mA` 没有这层稀疏刷新，也不消耗 ma 的刷新随机数；它令 `t=1+getAndAdd(raw[0],1)`，拿到该计数原子更新之前的值（`0026/bytecode.txt:121–130`，BCI85）。不要将23的逻辑泛化到25。

flush/恢复：mE `a()V` 用 `VarHandle.set(raw,0,adder.doubleValue())`；`b()V` reset adder 后加入 `Math.round(raw[0])`，见 `0021/bytecode.txt:90–117`。`mt.a()[B` 导出前 flush，将每个内存 double 转 float 写档；`mt.a([B)V` 将 float 升为 double，再调用恢复计数钩子，见 `0027/mt.java:105–131`。运行中是 double，不能因档案float32就改成float32训练。

## 3. 原子性与读取语义（observed + 限定推断）

`mt` 的静态 VarHandle 来自 `MethodHandles.arrayElementVarHandle(double[].class)`，`0027/mt.java:8–21`。mE/mA 的 R/A/D 更新是 `VarHandle.getAndAdd`，并非普通 `+=`：

- mE：每行动2次，D再1次，总计 `2K+1` 次 double RMW，另加 LongAdder increment 和偶发缓存CAS；`0021/bytecode.txt:231,245,256`。
- mA：计数1次、R共K次、z>0时共享A再K次；`0026/bytecode.txt:128,153,183`。
- `getAndAdd` 的调用点返回 descriptor 有 `([DID)D` 和 `([DID)V`；后者只是调用者弃用返回值，**不是降低为非原子写**。

Java 21 的这两个未带 Plain/Acquire/Release 后缀的原子方法使用 volatile 访问语义；weakCAS允许虚假失败。普通 `set` 则是 plain 语义。[Java 21 VarHandle](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/invoke/VarHandle.html)

策略读取链为 `mf → mt.a(IZ[DI)V → mv.a([DIIZ[DI)V`，mt直接把共享double数组交给mv，后者用 `daload` 读 R；未用 `getVolatile/getAcquire`、未有 monitor。`0027/bytecode.txt:80–94`，`0016/bytecode.txt:105–169`。计数getter也是plain `daload`（mE `0021/bytecode.txt:335–342`；mA `0026/bytecode.txt:248–255`）。因此读者可能看到跨更新组合的不同R；没有证据支持一个策略读取获得全K项的原子快照。

LongAdder sum 本身也不是并发原子快照；无并发更新时准确。[Java 21 LongAdder](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/atomic/LongAdder.html#sum()) Java语言规范甚至不要求plain double读写在所有实现中均为不可撕裂64位访问；本轮未观察原运行JVM的JIT汇编，不能将该字节码读法宣称为所有硬件上的原子快照。[JLS 21 §17.7](https://docs.oracle.com/javase/specs/jls/se21/html/jls-17.html#jls-17.7)

**对我们的约束（inferred）：** 当前 `choose` 与 `update` 各自持有完整 NodeMutex；递归之间不持有它。它保证各次策略读取或更新自身一致，但整个 choose→递归→update 并不是一个事务。见生产快照 `hrc_research_solver.cpp:316–322`。保留锁时普通double安全；删除锁则每个共享读写、updates/visits、探索/除数缓存都必须重新设计同步，不能仿照Java `daload` 写C++数据竞争。

若以后做单元格原子候选，C++17可使用真实atomic存储与CAS加法，必须避免同一地址混合atomic与普通读写；同时定义counter/flush/reset/序列化的停稳边界。它会改变多线程交错和可见性，不能承诺与当前checkpoint逐位相同。每节点LongAdder式分片也有内存成本，不应无条件分配nodes×workers个缓存行。

**尚未证实性能（unknown）：** 多次double原子RMW是否胜过一把TTAS锁；同bucket、不同bucket竞争比例；JVM是否把每个RMW编译为CAS循环；是否存在缓存行迁移瓶颈。本轮没有JIT/硬件counter或竞争profile。原子路线是待测架构选项，不是已证明的下一步提速。

## 4. special 与两/三行动策略（observed）

`mf` 首次推导special：第二条边的类型为 `lz.b` 时设1或2，2表示该边的child仍是mf decision；否则0。`0013/mf.java:51–60`；`0013/bytecode.txt:110–155`。**special==2不表示行动数为2。** 当前拓扑已预先保存这个静态属性，没必要重新引入原版的lazy检查。

`mv` 对K=2、K=3有单独展开的方法，其余K走loop：`0016/mv.java:12–42`。

| 条件 | 原版行为与精确锚点 |
|---|---|
| 普通 K=2 | max(R,0)，求和后两次除法；sum<=0时各0.5。没有“只有一个正R便跳过除法”的显式分支。`:45–55`；bytecode `:105–169` |
| 普通 K=3 | 顺序加三个max；sum>0三次除法，否则各1/3。`:58–70` |
| special && K=2 | 不读R，直接[0,1]。`:28–36`；bytecode `:61–103` |
| special && K=3 | action0为0；仅对后两项归一化。若均非正，按原R选择较大项，原R相等时两项各0.5。`:93–110` |
| special && K>3 | action0为0；其余归一化；均非正时选最大原R中的第一个，**不是所有并列最大者均分**。`:113–139` |

这些行为适用于普通存储策略读取。`BucketLocks`、frequency wrapper需保持自己的语义；例如只锁action1=.3可能组合为[.7,.3]，不能以special+K2绕开wrapper。当前 `Node::strategy` 先判frequency、再active locks、再普通normalize（生产快照`:101–105`）。

**直接可做候选：** 在普通normalize中把special+K2前移到读取R之前；分别写K2/K3路径。保留加法顺序、`P>0`点积筛选与逐项除法，不用乘reciprocal或fast-math冒充逐位等价。当前默认普通loop先读取部分R才判断specialK2（生产快照`:65–71`）。单positive简化虽可能另做，但并非“原版已经这样实现”；需单独处理非有限数与signed zero。Java Math.max和C++ std::max的NaN/-0细节也不能用普通随机有限正值测试掩盖。

## 5. 遍历返回值、marker与RNG顺序（observed）

scalar方法：`mf.a(LlV;IIDI)D`，`0013/mf.java:64–85`、bytecode`:158–290`。

- 先取策略、先抽行动，再判断当前actor是否target及target-skip。
- 需要更新时枚举所有child；仅被抽中的child携带原marker，其余marker=0；递归传同一个depth。
- 更新使用w=ctx.weight、z=marker×ctx.weight；**返回被抽行动的Q，不能改为V**。
- 跳过时只走被抽child，只有当前actor==target才depth+1。

vector方法：`mf.a(LlV;I)[D`，`0013/mf.java:89–117`、bytecode`:291–423`。

- 按行动序号遍历。被抽中的child走vector，其返回向量就是本节点返回向量。
- 其他child走target=当前actor、depth=0、marker=0的scalar。
- 只有未抽中action0且special==2，才先抽一个unit；小于.01时临时走vector取得当前actor收益。该支不替代最终返回向量。
- 最后更新用w=z=ctx.weight。不能把循环重排为“先走chosen再走其他”，那会改共享更新与随机序列。

`lV.a([DIID)I` 先探索门 `nextDouble < 1/sqrt(counter+10000)`，命中再nextInt(K)；未命中后先找P>=1，确定策略可免第二个unit；混合策略才再抽unit累计减法。见 `0029/lV.java:30–49`。因此specialK2固定策略仍不能删除探索门；nonchosen策略为0也不能据此剪除target遍历。

目前生产scalar/vector `:411–430` 保留这些主分支。constant-scalar剪枝另有证明和明确的随机轨迹改变，不能把它当作本轮发现原版也做的优化。此前固定嵌套数值证据位于 `reports/hrc-original-nested-traversal-validation.json`；本轮未重跑，也未据此扩大为所有配置/并发等价。

## 6. 缓冲区与已经存在的优化（observed）

`ma` 初始化1024个double并按需要扩容，`a(I)[D` 返回可复用数组：`0011/ma.java:7,14–19`。`mf` 每层只占当前K的P和Q，共2K槽，下一层offset+=2K。`mn` 每worker在采样loop之前创建一次ma（`0034/mn.java:87–96`；mn反编译有finally标记，不能用它替代完整异常路径字节码）。这说明“原Java每节点new两个数组”是错误判断。

我们当前p[MAXA]/q[MAXA]是栈数组，也**不是每节点heap分配**。可能的差异是每帧固定32double与动态2K缓冲区、栈帧/寄存器溢出。候选可以是每worker预先分配按最大根到叶路径sum(2K)计算的arena。父层P/Q必须跨child递归保持有效；C++vector中途扩容会使指针失效，不能照搬Java旧数组仍被父层引用的生命周期。预算计入worker私有内存，并测试深树、非ID顺序树、特殊vector分支和异常退出。

已经存在、不要重复当成新收益的项目：

- 原mE稀疏读取LongAdder sum；原mv的K2/K3展开；原specialK2免R读；原确定策略免第二unit。
- 原ma每worker复用；原mf缓存static special；原lV按deal惰性计算street buckets/ranks（`0029/lV.java:63–75`）。
- 我方已缓存exploration和refresh divisor，键跟存储counter，而非updates（生产快照`:79–97`）；这些mutable缓存仍须在节点锁内或改为worker私有。
- 原double训练、float档案已经分开；改float训练不能叫等价内存优化。

## 7. 建议实施顺序与验收

1. **最窄：普通specialK2前置和K2/K3专门化。** 原数值探针覆盖全负/零/正/混合、special各类、锁与频率wrapper，再做单线程旧/新checkpoint及RNG尾逐位一致。计数增加和53行自测不足以独立覆盖这一分支。
2. **独立候选：固定K更新展开。** 原mE/mA更新仍是loop；保留点积筛选、累加顺序、计数刷新随机调用及marker0差异。在现有NodeMutex内分组写入不会暴露中间状态，但若后续改cell atomic，原mE的R[a]/A[a]交错顺序也需要重新评估。
3. **单独候选：worker scratch。** 先验证深度与指针生命周期，不同时改遍历顺序；检查内存预算、异常退出与nested原探针。
4. **架构实验而非默认替换：单cell atomic与分片counter。** 保留当前锁版作为对照；要求无C++数据竞争、停稳读档/reset、32线程慢holder/异常测试、多seed策略与CI轨迹，且最终使用未插桩版本实测。不得只凭去锁后快便宣称收敛等价。

本轮没有声称已完成原版全部工程恢复，也没有发现足以证明现有生产没有bug的证据。接下来应把每一项候选的语义、性能和达到相同CI的用时分开验证。
