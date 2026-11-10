# HRC 4.1.0.202603231401 求解核心：实际字节码还原

本报告针对本机主 JAR 的实际实现，不以公开 MCCFR 的通用伪代码替代 HRC 行为。目标：`D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar`，SHA-256 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。调查日期 2026-11-04。

已经静态追到：UI 模式选择 → Eclipse Job → 并行 worker → 发牌 → 两种递归 → 具体存储更新 → 平均策略读取 → CI。保留 30 个类、349 个带代码的方法的 `javap -c -p -s`。所有 Sxx 事实都有类哈希、方法 descriptor、javap 行号、BCI 范围和反编译行号，见 [机器可读事实记录](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/facts.json)。2026-11-04 已经从原始 JAR 隔离执行策略数值探针与发牌/遍历 fixture，分别 **30/30 和 52/52 检查通过**。Sxx 的“已观察”仍指静态证据，独立的运行证据见第 6 节；未启动 HRC 应用，也未观察一次完整求解。

混淆器允许同名不同类型字段、相同参数但不同返回类型的方法。反编译的 `a` 不能独立标识字段/方法。例如 `lV.a:lX` 与 `lV.a:lY` 是两个不同字段，不能因为 Java 伪源码都写 `lV.a` 就认定两种算法相同。反编译文本不保证能重新编译，最终以 descriptor 和字节码为准。

## 1. v4/v3 真正在哪里分开

`ew.execute(Lorg/eclipse/core/commands/ExecutionEvent;)Ljava/lang/Object;` 的 BCI 224–265 显示：下拉框 index 0 读取 `lV.a:Lnet/holdemresources/internal/lY;`，index 1 读取 `lV.a:Lnet/holdemresources/internal/lX;`。UI 列表分别标注 v4 和 v3。**已观察 S01。**

二者 factory 方法 descriptor 都是 `(Lnet/holdemresources/internal/oj;[J[ILnet/holdemresources/internal/ma;)Lnet/holdemresources/internal/lV;`：

| 选择 | 工厂实际行为 | 标量递归的差异 |
|---|---|---|
| v3 / `lX` | 创建 `lV(..., true, scratch)`，跳过谓词保持 null | 目标玩家节点全部展开并更新 |
| v4 / `lY` | 同样创建 `lV(..., true, scratch)`，另设 `lV.b:BiPredicate` | 谓词返回 true 时只继续选中的一个行动，不更新本节点 |

v4 安装的谓词为 `nextInt(2+d)==0`，因此给定 d 的跳过概率是 `1/(d+2)`。`d` **不是通用树深度**：只有标量递归在目标玩家节点被跳过时才加 1，其他玩家节点和完整展开分支都不增加它。v3/v4 共用 `mf` 遍历和 `mx` 存储对象，不能把 `mE`/`mA` 或格式编号 23/25 当作 v3/v4 分界。**已观察 S02、S05；概率解释为静态推导 S06。**

UI 声称 v4 约两倍速度，但本调查没有进行完整原程序的对照计时；代码也不单独构成该估计器无偏或收敛速率的证明。

## 2. worker、样本和机会事件

`bM.a(WeakReference,lZ,long,Consumer)` 创建 `bN`，double 版本创建 `bO`；Job 调用 `bM` 带 `IProgressMonitor` 的重载，再创建 `mn`。固定样本停止谓词使用严格 `reservedCount > target`，不是 `>=`；CI 模式检查 `mq.a:Z` 停止标记，或 CI 非 NaN 且严格小于目标。界面刷新间隔由 Job 传入的 10000ms 控制。

`mn.a(ILnet/holdemresources/internal/mc;Lnet/holdemresources/internal/md;)V` 创建 `ForkJoinPool`，并行 worker 共用树与原子/adder 存储。每个 worker 拥有 RNG、底牌数组、4 个 board mask 和 `ma` scratch buffer。工作计数用 `AtomicLong.getAndAdd(250)` 预约，每次最多处理 250 个样本；另有 `LongAdder` 记录成功的样本，用于根收益均值。预约计数、实际成功样本、各节点更新计数是三种不同数量。**已观察 S20。**

默认随机源为 `RandomSource.XO_SHI_RO_256_SS.create()`。`lu.a(UniformRandomProvider,int[],long)` 逐人抽具体两张牌组合，拒绝与已有 mask 冲突的组合；普通完整均匀范围下这个顺序抽样是均匀无放回发牌。公共牌在相同无冲突约束下依次抽 flop 3 张、turn 1 张、river 1 张，保存累积 bit mask。`lV.a(II)I` 懒缓存每街、每玩家的抽象桶编号，翻前映射由 `ls.a:[I` 提供。**已观察 S14。**

加权/子树分支的 `lw` 把 169 类权重通过 `ls.a:[I` 扩展到具体组合，构造 `GuideTableDiscreteSampler`。有权重的玩家中任一抽牌冲突，就重新开始本轮加权玩家分配；成功后才补齐均匀范围或当前排除的目标玩家。每 10000 次失败检查取消；没有固定失败次数后切换有偏方案。**已观察 S15。**

`mn` 的内部模式如下（不是 v3/v4）：

1. 模式 0：完整均匀底牌与随机公共牌，进入返回全体玩家向量的递归。
2. 模式 1：范围/固定公共牌条件下发牌，同样进入向量递归。
3. 模式 2：循环目标玩家，排除该玩家的加权底牌采样后重新补牌，调用标量递归；传入该玩家相应根手牌权重。该模式对 postflop 根显式抛出尚未实现异常。

这里陈述的是分支和传参事实。每一种子树估计的无偏性仍需要分别证明或原字节码实验，不应直接套用我们旧原型的范围发牌与平均策略公式。

## 3. 当前策略、探索和两种递归

### 3.1 先计算策略，再加入行动探索

`mt.a(IZ[DI)V` 调用 `mv.a([DIIZ[DI)V`。普通模式把正的累计量归一化；没有正值时使用均匀策略。特殊模式把行动 0 概率设为 0：两行动时固定 `[0,1]`；更多行动且其他遗憾都非正时，选择允许行动中原始值最大的一个，三行动且两者相等则各 0.5。**已观察 S10。**

`mf` 在 child 1 的动作等于 `lz.b` 时启用特殊模式；树调查已经将 `lz.b` 与 CHECK、child 0 与特殊 fold 分支建立代码对应。因此这不是随机丢弃一个普通行动，而是与可过牌节点的特殊分支有关。`c=2` 表示 child 1 仍是 `mf`，否则 `c=1`。在 `c=2` 的向量递归中，未选中的 child 0 还有 1% 概率走完整向量更新，其他时候走标量递归。**已观察 S11；具体树构建语义参见树调查。**

得到策略 p 后，`lV.a([DIID)I` 还有一层探索：

```
epsilon = 1 / sqrt(nodeCounter + 10000)
若 exploreEnabled 且 U < epsilon：均匀抽全部 K 个行动
否则：若某个 p[a] >= 1，返回第一个这样的行动
否则：按 p 的累积概率抽行动；若没有命中，返回行动 0
```

v3/v4 工厂均启用此探索。因此 p[a]=0 并不保证该行动永不被访问，特殊模式的行动 0 仍可能经均匀探索选中。初始 counter=0 时 epsilon=0.01。**已观察 S03。**

### 3.2 `mf.a(lV,int):double[]`：沿一条实际路径，同时探索替代行动

descriptor 为 `(Lnet/holdemresources/internal/lV;I)[D`。它先获取 p 并抽行动 k，然后：

- 选中子节点走同样的向量递归，返回全部玩家收益向量 v。
- 每个未选中行动走目标为当前节点玩家 i 的标量递归，得到该行动的标量价值 Q[a]；选中行动的 Q[k]=v[i]。
- 用全部 Q 和 p 更新本节点存储。
- 返回选中子节点向量 v，**不是**各行动向量的 p 加权和。

这与“每轮分别对每位玩家进行标准 external-sampling 遍历，随后单独采样平均策略”的旧 Python 原型不同。**已观察 S04。**

### 3.3 `mf.a(lV,int,int,double,int):double`：替代路径中的目标玩家更新

descriptor 为 `(Lnet/holdemresources/internal/lV;IIDI)D`。节点不属于目标玩家时只沿抽到的一个行动递归；属于目标玩家时，若 v4 谓词决定跳过，同样只走一个行动并增加前述 d。

未跳过的目标玩家节点枚举全部行动：选中行动继承传入 marker，其余行动 marker=0；调用 `mx.a(ma,buffer,offset,bucket,w,marker*w)` 更新；返回选中行动的 Q。这个 marker 在预翻前 `mE` 中被忽略，但在 `mA` 的共享动作平均中有实际作用。`w=lV.a:D` 默认初始化为 1.0；对主 JAR 全部含 lV 引用的类做有界检索，未找到构造器以外改变这个 double 字段的代码；不能把该静态负结果扩展为所有插件/反射路径的证明。**已观察 S05、S07、S09。**

## 4. 更新公式与真实数据布局

### 4.1 默认翻前存储 `mE`，格式编号 23

`mf.<init>(mf,List,mj[],int[],int,int,int)` 在街编号为 0 且桶数量正数时创建 `mE`，非零街创建 `mA`。`mE.a(ma,double[],int,int,double,double)` 的 descriptor 是 `(Lnet/holdemresources/internal/ma;[DIIDD)V`。

令 K 为行动数、h 为手牌桶、r=1+(2K+1)h。`mt.a:[D` 布局：

| 位置 | 字节码中的用途 |
|---|---|
| 0 | 缓存的本节点更新计数 |
| r…r+K−1 | 累计遗憾/价值差更新量 R |
| r+K | 加权更新分母 D |
| r+K+1…r+2K | 平均策略累计量 A |

输入 scratch 的前 K 项是 p，后 K 项是 Q。w≤0 时不更新，否则：

```
V = Σ_{a:p[a]>0} p[a] Q[a]
R[a] += t × w × (Q[a] − V)
A[a] += t × p[a]
D    += t × w
```

注意 A 不乘 w，也不使用最后一个 double 参数 z。它不是我们旧原型独立平均遍历中的 `ownReach / sampledPublicReach` 更新。源码未把存储的负遗憾截为 0；只有取策略时对正部分归一化。**已观察 S07。**

t 也不是全局迭代编号：先递增 `LongAdder`，暂取 `t=1+array[0]`；若 `ma.a(t)` 返回 true，则用当前 LongAdder 快照作为局部 t，并尝试 `weakCompareAndSet` 刷新 array[0]。该谓词精确代码是 `nextInt() % floor(sqrt(t)) == 0`；不能把有符号随机整数取模不加说明地描述成数学上严格 `1/floor(sqrt(t))` 的概率。CAS 失败不撤回局部 t 快照。计数读取/序列化/CI 刷新还会直接把 LongAdder 值写回缓存。**已观察 S08。**

显示平均策略的 `mt.a(I)[D` 归一化 A 段；`mt.b(I)[D` 返回 `(R[a]−R[0])/D`，分母非正时返回 NaN。因此后者是相对行动 0 的差值，不是保存了所有行动绝对 EV 的数组。**已观察 S12。**

### 4.2 `mA` 与其他存储

`mA` 格式 25 保存每桶 R，但动作平均在所有桶之间共用一个 K 项向量。t 使用对 array[0] 的原子加 1 返回值再加 1。R 更新仍为 `t*w*(Q−V)`；仅 z>0 时向共享平均加 `t*z*p`。所以其显示每桶策略和聚合平均不能与 `mE` 当作相同数据布局处理。**已观察 S09。**

`mB` 格式 27 额外保存每桶 A 与共享平均；`mD` 格式 31 使用 `mw` 分段存储和 DoubleAdder 共享平均。它们的出现不代表 v3/v4 更换了 regret 公式。静态报告已保存更新方法，全部创建/转换组合是否在某具体会话被采用仍取决于树与保存文件。**已观察 S21，运行时选择未知。**

`my` 是范围锁定包装器：取概率时调用 `mx.a` 将锁定频率与其余量合成；更新则原样委托底层存储。编辑时如果锁定频率总和超过 1，按剩余空间同比缩放其他锁定行动。**已观察 S22。**

Reset Strategies 实际把 A 乘 `1e−20`；Reset Regret 还把 R/分母乘 `1e−20` 并清零计数。它不是逐元素精确写零。**已观察 S13。**

## 5. CI 的完整实际公式

CI 来自 `mq.a(J)Z`，它读取 `mf.c(bucket)` 的归一化展示策略，并先调用 `mx.c()` 刷新节点计数。翻前根只收集街编号 0 的相关 `mf`；后街根另有同街/格式能力筛选。

设选中的节点数为 N，节点 j 新旧计数差为 Δn_j，新旧策略矩阵为 P_j 和 P′_j。每个矩阵包括该节点全部手牌桶和行动；代码没有先按手牌组合权重乘一遍：

```
d_j = (1/2) Σ_bucket Σ_action |P_j − P′_j|
L   = [Σ_j sqrt(Δn_j) × d_j] / [Σ_j sqrt(Δn_j)]
CI_raw = sqrt(1e8 × N × L / Σ_j Δn_j)
```

首次有效测量直接采用 raw；以后 `alpha=min(previousSnapshotOrdinal*0.05,0.75)`，`CI=alpha*oldCI+(1−alpha)*CI_raw`。首次快照 ordinal=0，所以第二次测量仍完全采用 raw。**已观察 S16、S17，BCI 28–313 为差值与原始 CI，315–570 为平滑/节流。**

更新最短间隔为 `max(15000ms,50×上次测量耗时)`；历史保留至少 3 条，并以 `min(总经过时间×0.75,7200000ms)` 滚动时间窗清理。该指标既依赖节点更新次数也依赖墙钟测量节奏、多线程快照，因此不能仅用样本数复现完全相同的 CI 曲线。

`mq.a(DLnet/holdemresources/internal/mr;)D` 的目标进度估计使用指数 −1.7：

```
progress = max(0, 1 − (target^-1.7 − current^-1.7)
                      / (target^-1.7 − reference^-1.7))
```

有参考缺失、当前比参考更差、已达目标的提前返回。bM 再使用该进度及历史样本速率计算 ETA。**已观察 S18。**

从所读取操作可推导：CI 衡量近期策略变化；它不是统计置信区间，也没有在这条链路中计算最佳响应、NashConv 或 exploitability。UI 的“CI≈1”建议不能转写成有界误差保证。**静态推导 S19。**

## 6. 原字节码数值探针与运行证据

测试从原 JAR 加载未经修改的 class bytes，使用 platform parent 的独立 ClassLoader 和严格类白名单；没有重新编译反编译源码。反射/MethodHandle 查找同时核对方法名、参数和返回 descriptor。

1. `mv.a([DIIZ[DI)V`：验证普通正遗憾、全非正均匀、check-special 两行动 `[0,1]`、三行动负值择优/平局。
2. `mE.<init>(II)V` 和更新：1 桶 2 行动，RNG 的 `nextInt()` 固定 0，使节点计数每次刷新。第一次 p=(.25,.75)、Q=(4,−2)、w=1、z=0，预期 R=(4.5,−1.5)、A=(.25,.75)、D=1；第二次 p=(.5,.5)、Q=(2,6)，预期 R=(.5,2.5)、A=(1.25,1.75)、D=3，平均为 (5/12,7/12)。改 z 不应改变 mE 结果。
3. 同样输入 `mA`：z=0 应不增加共享 A，z=1 增加共享 A；检查返回的 per-bucket 概率和共享平均的差异。
4. `lV.a([DIID)I`：脚本化 RNG 控制探索分支、累计抽样和兜底；counter=0 的探索阈值应为 0.01。此项需额外审计 lV/ls/工厂初始化，未列入最小存储探针。

### 6.1 已执行的存储/策略探针

[OriginalStrategyProbe.java](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalStrategyProbe.java) 经主调查代理审阅后执行。源码 SHA-256 为 `dd14572b00fa6ec2edb6545b7b250374474537276f91145d1763b8365d852c0e`。运行返回码 0、stderr 为空，30/30 检查通过，覆盖 8 个 `mv` 归一化案例、`mE` 两步更新/平均/相对 EV 与 z=0/1/100 对照、w=0/.5 边界，以及 `mA` 的 z=0/1 和逐桶策略/共享平均差异。详细输入、数组中间态、预期、实际与误差均保存在 [原始 JSONL](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/probes/strategy-original-output.jsonl) 和 [验证报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-strategy-validation.json)。

探针首先核对主 JAR 的完整 SHA-256；每次加载 class 时额外记录原始 ZIP member、字节数和 SHA-256。已实际核对全部 8 个加载的 HRC 类，哈希均与 `source-index.json` 的原始字节码身份一致；当前探针源码哈希也与执行报告一致。RNG JAR 是 `commons-rng-client-api-1.6.jar`，SHA-256 `9b9cc84858789046b03636216aff2cf8062711a1d68478746e2a8cfc202be429`。只加载它的接口，数值测试由脚本 RNG 提供随机值。白名单限定 `mE/mA/mt/mx/my/ma/mu/mv` 与该接口，未加载应用入口、GUI、OSGi、许可组件或网络代码。此执行证据支持 S07–S10、S12 的具体数值案例，不构成并发行为或全程序收敛的验证。

### 6.2 已执行的原始发牌与遍历 fixture

[OriginalTraversalProbe.java](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalTraversalProbe.java) 经主调查代理审读、补充审计一个纯接口依赖后执行，**52/52 检查通过**，返回码 0、stderr 为空，所有数值检查误差为 0。执行版本源码 SHA-256 为 `3d2d684cf84ce8638b330f0262fa01447e932468cd900d591c17144a2d44755e`。它构建二玩家、二行动的一个 `mf` 节点和两个真实 `mh` 叶子，然后调用原始 `lu` 发牌、`ls` 组合映射、`lX/lY` 工厂、`lV` 上下文、`mf` 向量/标量递归、`lv` 七张牌评估、`me` 结果索引与 `mE` 存储。覆盖 4 副确定种子牌、每副的 v3/v4 向量遍历，以及脚本 RNG 强制 v4 跳过/不跳过与 v3 对照。结果见 [验证报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-traversal-validation.json)。

实测观察：v3 标量节点展开后写入遗憾与平均；v4 的 `nextInt(2)=0` 仅递归并返回选中叶子收益，整个节点存储保持 0；v4 的 `nextInt(2)=1` 执行更新。每副牌的向量返回、原始七张牌力缓存、当前手牌桶的具体遗憾/平均数组，以及其他 168 个桶没有写入均通过。这验证 S04–S07 的这些具体分支，不等于验证所有深度、玩家数与策略锁定组合。

**收益表为合成输入**：弃牌叶子 `[-1,1]`，摊牌叶子三个可能结果对应 `[10,-10]`、`[20,-20]`、`[30,-30]`。原始 `mh/me/lv` 选择表项，但这张表不是 HRC 真实结算/ICM 生成器计算的。这一设计单独检验原始发牌到原始遍历和存储的连接，不能声称覆盖完整结算、原始全树构建或后街策略。

加载审计：白名单只有 `mE,mA,mt,mx,my,ma,mu,mv,mf,mj,lU,lR,lA,ly,lz,mh,lS,lK,lC,lE,mi,kG,kM,ky,lH,mk,me,lV,lW,lX,lY,lZ,oj,lu,ls,lv` 和 Commons RNG 接口。首次执行在 `mh` 构造器类型验证处遇到白名单外的 `lE`；静态审计确认它为无静态初始化器的纯接口后才加入，未扩大完整 classpath。`kM` 只调用保存四个字段的构造器；`mi/mh` 仅通过其正常接口读取玩家数。`lC` 的私有纯数据构造器用于建立满足正常“所有玩家已行动”条件的状态，再经原始 `lK.a(lC)` 转换。没有修改状态门控。

唯一允许的资源是原 JAR 的 `net/holdemresources/gamerules/handeval/data/lookup7card.dat.gz`，实测 88,390 字节，SHA-256 `49507e2d64794cc3957152d933260162fb505e8003529e9bab8f5cca87ab9f03`。加载的 33 个 HRC 类哈希全部与 `source-index.json` 一致；当前探针源码哈希与报告一致。`lu` 的默认 RNG factory 未调用；发牌采用脚本代理的 `java.util.Random` 有界整数，原始默认 Xoshiro 随机源不在本测试覆盖范围内。日志中没有应用入口、GUI、OSGi 或许可类。

以下命令可复现已审读版本，JSONL 需要单独保存；成功摘要应含 `checks=52`：

```powershell
& 'D:\Tools\REA-Research\jdk-21.0.13+9\bin\javac.exe' -encoding UTF-8 -d 'analysis/hrc-deep/solver/probe-classes' 'scripts/java/OriginalTraversalProbe.java'
& 'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe' -cp 'analysis/hrc-deep/solver/probe-classes' OriginalTraversalProbe 'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar' 'D:\Program Files\HRC\plugins\net.holdemresources.calculator.mavendependencies_0.2.0\org.apache.commons\commons-rng-client-api-1.6.jar'
```

## 7. 已回答与仍未回答

已回答：UI 模式到实际 factory 的映射；worker 批处理与机会采样分支；v4 标量递归跳过机制；普通/特殊策略提取；探索阈值；翻前与后街存储更新公式；平均读取；重置；CI 全公式及节流。原始字节码数值探针补充验证了两种存储更新、归一化、最小原始发牌→遍历→牌力评估→合成叶子收益返回→对应桶更新链，以及 v3/v4 的跳过对照。

仍未回答：真实多线程会话的随机种子/执行序列；所有插件、反射和存储格式组合；v4 估计器的形式无偏/收敛证明；完整 HRC 对照求解的逐节点结果；原型与原程序全功能数值等价。82 项隔离检查仅验证所列方法与合成收益 fixture，不能证明整个 HRC 已复现。

完整方法定位、源文件哈希、BCI 与事实/推导分类以 [facts.json](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/facts.json) 为准。主要源码定位：[遍历 mf](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/0013/decompiled/mf.java:61)、[翻前更新 mE](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/0021/decompiled/mE.java:42)、[后街更新 mA](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/0026/decompiled/mA.java:34)、[CI mq](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/0030/decompiled/mq.java:49)。
