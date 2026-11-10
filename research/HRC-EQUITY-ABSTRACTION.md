# HRC 收益、牌力评估与翻后抽象链研究

研究对象：本机 `net.holdemresources.calculator_4.1.0.202603231401.jar`，SHA-256 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。日期：2026-11-04。本文分析由原始 class、Vineflower 反编译、`javap -p -s -c` 和 ASM 索引交叉支持；不以混淆类名猜测算法。完整分析工件留在 `analysis/hrc-deep/`，没有进入独立研究应用的实现目录。

本分支没有启动 HRC，也没有调用应用入口、许可注册器或修改安装目录。文件解压检查只运行通用 Brotli 解码器。文中原始字节码数值探针由主代理在审计后的隔离类加载器内执行，必须与“运行完整 HRC”区分。观察到的算法、有限样本的相符和整个商业产品等价，是不同层次的结论。

## 1. 主要结论与证据级别

- **事实：**普通 ICM 是子集动态规划，返回各名次奖金贡献；不是 Monte Carlo ICM。存储规模含 `double[1 << n]`，适用于本桌较小人数。
- **事实：**MTT ICM 使用另一条路径：将本桌与其他桌筹码拼接，以一维积分求名次权益。外桌人数达到 100 时，第三名及以后启用带偏度修正的正态近似；前两名始终用显式精确公式。
- **事实：**KO/PKO 分成当前手即时击杀奖励、幸存者悬赏余额更新、未来悬赏池估值。当前默认未来悬赏估值是按筹码比例分配剩余池，不是为每次未来击杀做完整博弈求解。
- **事实：**FGS 递归下一手，缓存未来局面，并调用 `qI` 的受限 169 类手牌阈值求解；有深度、多人结果及平分底池分支限制。不能把这个 FGS 后端称作完整无限未来游戏求解。
- **事实：**抽象数据不是任意“桶号字符串”。有确定的公共牌花色规范化、排序、合法两张手牌列序、little-endian short 编码和解压后 SHA-256 校验。实际验证的 64 桶 flop 文件完全符合这套格式。
- **事实：**真实七张牌评估落到纯 Java `lv.a(J)S` 与压缩查表资源；旧式 2/3 人翻前计算另使用联合发牌/结果概率表。没有在这些数学路径中发现应用声明的 native 求解器。
- **边界：**静态依赖审计发现 Graal/Truffle 的 JNI 辅助库，不能据“主 JAR 没有 native 声明”推论整个 HRC 没有原生代码。

精确 JVM 方法签名、原 class 哈希、源码路径、调用和 ASM 文件行号汇集于 [evidence-catalog.json](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/evidence-catalog.json)，覆盖本报告 55 个主 JAR 类。ASM 的调用 ordinal 是访问器事件序号，**不是字节码 offset**；真正指令偏移见各 `equity/{ordinal}_{class}/bytecode.txt`。

## 2. 收益模型总路由

工厂 `kT.a(Lnet/holdemresources/internal/kJ;Lcom/google/gson/JsonObject;)Lnet/holdemresources/internal/kT;` 对 JSON `id` 做明确分支：[kT.java:15](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0900/kT.java:15)。

| `id` | 工厂实现 | 实际 evaluator / context |
|---|---|---|
| `chipev` | `kO` | `kD` 读取末态筹码；`kM` 承载 rake-aware `lH` 结算器 |
| `icm` | `kR` | 普通 `kE(kW,kC)`；有悬赏时 `ll(kW,kC)`；上下文 `kM`、固定 KO 的 `lj` 或 PKO 的 `lk` |
| `mtticm` | `kS` | `li` → `lg`；上下文 `lh` 保存外桌筹码和悬赏资料 |
| `fgs` | `kP` | `kX` 递归；叶层委托普通 ICM 或悬赏 evaluator |

`kT` 的 `a()L.../kG;` 与 `a()L.../kK;` 仅返回类型不同；大量混淆成员有同样情况。阅读反编译中的 `a` 时必须带 descriptor。ChipEV 不是直接返回以 BB 为单位的利润：`kD.a(kG,lE)` 返回终局筹码，`kF.a([J)[D` 将内部整数筹码乘 `0.01`。净增益及 UI 单位需要由上层另行转换。[kD.java:5](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0923/kD.java:5)、[kF.java:4](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0925/kF.java:4)。

`kO.a()L.../kG;` 有反编译构造器错误标记，因此其中 rake 路由应以 bytecode 为准，而非把生成源码当成可以直接编译的实现。其配置字段可见 `raked/rakepct/rakecap/nfnd/raketype_ggnetwork`；真正扣费发生在 `lH` 的分池结算阶段。

## 3. 普通 ICM：可以精确复原的动态规划

核心方法为 `kW.a([D)[[D`，构造器 `kW.<init>([D)V` 接受奖金向量；父类 `kU.a([D)[D` 累加每名玩家所有名次的贡献。[kW.java:9](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0896/kW.java:9)、[kU.java:16](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0898/kU.java:16)、[kW bytecode](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/0896_kW/bytecode.txt:9)。

令正筹码为 `s_i`、奖金为 `p_r`，`S` 是已占前 `r` 名的玩家子集，`W[∅]=1`。代码按 `r=1..min(n,奖金数)` 遍历所有大小为 `r` 的子集；对每个 `i∈S` 计算：

```text
outside(S) = Σ(j∉S) s_j
q(i,S) = W[S\{i}] × s_i / (s_i + outside(S))
W[S] += q(i,S)
rankContribution[r−1][i] += q(i,S) × p[r−1]
equity[i] = Σr rankContribution[r][i]
```

**解释而非额外事实：**这是按剩余筹码比例选下一名的 Malmuth–Harville / 通常所称 ICM 排名模型。与源代码不同的前向概率分布及小人数排列穷举可作为独立 oracle。`W` 长度为 `1 << n`，扫描方式有指数开销；也没有在此纯方法中看到输入域的完整防护，因此不能任意扩展到大赛全场人数或直接塞入零筹码淘汰者。

**已验证：**主代理隔离加载原 `kV/kU/kW`，1–10 人、41 个奖金/名次/尺度案例全部通过，与独立前向概率 oracle 及 ≤6 人的穷举排列比较，最大权益误差 `2.27e-13`。见 [hrc-original-icm-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-icm-validation.json)。该结果验证这条纯 ICM 方法；没有验证外层配置、KO、MTT 积分或求解均衡。

### 淘汰与同手出局顺位

`kC.a(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D` 识别终局 `stack<=0` 玩家，并发放已经确定的奖金。多人同手出局时，用**本手开始时**筹码排序，较多者取更高名次；起始筹码相等则平均相关奖金。不是按最终都为零的筹码重新跑 ICM。[kC.java:18](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0933/kC.java:18)。

`kE.a(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D` 先收集 `kC` 即时奖励，调用上下文 `a(lE)` 得到幸存者上下文及旧索引→新索引映射，再计算幸存者 ICM 并映回原玩家。这解释零筹码为何通常不进入 `kW`。[kE.java:24](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0935/kE.java:24)。

## 4. KO / PKO：即时奖励、头上悬赏与未来价值

`kI` 为悬赏上下文接口；`lj` 固定 KO，`lk` PKO。`lE.a(I)[I` 给出玩家被淘汰后对应的获奖者集合，它来自底池结算，而非用总筹码最多者推测击杀者。

`kB.a(Lnet/holdemresources/internal/kI;Lnet/holdemresources/internal/lE;[DD)[D` 的明确公式为：对于每个被淘汰者 `v`，把 `bounty[v] × fraction` 平均给 `outcome.a(v)` 中的所有玩家。固定 KO 重载的 descriptor 是 `(Lnet/holdemresources/internal/kI;Lnet/holdemresources/internal/lE;D)[D`。[kB.java:4](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0934/kB.java:4)。

PKO 传入的 `progressiveFactor = α` 在实际算式中表示**立即支付的比例**：

```text
immediate[i] = Σ(v 被 i 等人淘汰) α × bounty[v] / winnerCount[v]
newBounty[i] = oldBounty[i]
            + Σ(v 被 i 等人淘汰) (1−α) × bounty[v] / winnerCount[v]
```

`lk.a(I)D` 返回 `α*bounty[i]`，`lk.b(I)D` 返回完整 bounty；`lk.a(lE)kH` 更新幸存者悬赏向量；`lk.a(lE)[D` 产生即时奖金。[lk.java:17](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0910/lk.java:17)。不能只依据字段英文名字，把 α 反写成滚入头上的比例。

`ll.b(Lnet/holdemresources/internal/kG;)[D` 明确执行：

```text
futureEquity[i] = ordinaryICM(stacks,payouts)[i]
                + remainingBountyPool × stack[i] / Σstack
```

其中固定 KO 池为“活跃人数 × 固定 bounty”，PKO 池为当前所有 bounty 之和。一次终局的总值则为 `kC` 已实现奖励加下一上下文 `futureEquity`。[ll.java:21](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0911/ll.java:21)、[lj.java:28](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0909/lj.java:28)。**限制：**这可精确描述代码中的悬赏估值假设；不能因此宣称其未来击杀机会是精确比赛模型。

## 5. MTT ICM：积分和大场近似

`kS` 读取 `otherstacks`、`otheravgbounty` 等资料，构造 `lh`。`li.b(kG)[D` 用 `lg` 计算本桌玩家对整个剩余赛场的奖金权益，再加按全场筹码比例分配的剩余 bounty pool；`li.a(kG,lE)[D` 将外桌人数作为本桌确定出局奖级的偏移。[li.java:12](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0929/li.java:12)、[lh.java:11](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0928/lh.java:11)。

`lg.<init>([D[D)V` 保存奖金和外桌筹码，开关是 `otherStacks.length >= 100`，**不是**总剩余人数 ≥100。[lg.java:16](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0930/lg.java:16)。每名本桌 hero 都与外桌筹码拼接后求值。

对 hero `i`，全场总筹码 `S`，前两名贡献单独精确计算：

```text
first[i]  = p1 × s_i/S
second[i] = p2 × Σ(j≠i) (s_j/S) × (s_i/(S−s_j))
```

第三名及以后奖金使用区间 `[0,1]` 上的一维积分。令 `t∈(0,1)`，对手 `j` 的 `q_j(t)=exp(log(t)*s_j/s_i)`。精确 integrand `lg.a([D[DID)D` 以长度 `n` 数组从最末名概率 1 开始，对每个对手将概率 `q_j` 向更好一个名次转移；最后与奖金额逐项相乘求和。等价地，`q_j` 是条件于 hero 的指数竞赛时间时，对手排在 hero 后面的概率，构造一个 Poisson-binomial 名次分布。这一概率解释是根据算式作出的数学推导。[lg.java:122](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0930/lg.java:122)。

大场分支按 `q_j` 求：

```text
μ = Σ q_j
σ² = Σ q_j(1−q_j)
γ = Σ q_j(1−q_j)(1−2q_j) / σ³
z = (k+0.5−μ)/σ
F(k) ≈ Φ(z) + γ(1−z²)φ(z)/6
```

代码以奖金改变的位置为边界，用 `F` 的差分聚合相同奖金的名次区间；如果该次 integrand 为 NaN，回退精确 Poisson-binomial DP。CDF 帮助方法的精确 descriptor 是 `lg.a(DDDD)D`。[lg.java:149](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0930/lg.java:149)。

积分调用是 `org.jquantlib.math.integrals.GaussKronrodNonAdaptive`，构造参数 `(1e-10,0,1e-10)`。源码还含最多 20 次分段：端点 `u_next=u+0.75*(1−u)`，循环检查的是近似 integrand 在 `0.75*(1−u)` 的值和累计积分是否均为零，随后整合剩余 `[u,1]`。这里特意保留实际条件，不能把它改写成未经核实的常见自适应积分算法。

**尚未验证：**未运行原始 `lg`，没有测定 99/100 外桌玩家阈值前后的误差、极端筹码/大量相同奖金时近似是否出现负的中间概率，也没有给它声明全场精确 ICM 的保证。最适合下一步隔离的候选是 private static `a([D[DID)D`，但必须先审计 `lg.<clinit>` 中 jquantlib 正态分布初始化和依赖类闭包。

## 6. FGS：真实递归边界

`kP` 读取 `depth`、可选 `depth3way`（默认 1），可选 `nextlevel.atdepth/tolevel`。`kX` 接受终端 evaluator、立即奖励 `kC`、深度与一个 `BiPredicate<lb,lE>`。[kP.java:14](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0903/kP.java:14)。

predicate 的字节码可消除单类反编译中的 lambda 捕获歧义：`kP.a(ILnet/holdemresources/internal/lb;Lnet/holdemresources/internal/lE;)Z` 在 `outcome.a()Z` 为真时返回 false；否则返回 `context.e()<depth3way || outcome.a()I<3`。`lF.a()Z` 保存结算时出现并列获奖的标志，`lF.a()I` 返回本手参与终局的玩家数量。由此可见：平分底池结果直接落终端模型，三人结果的继续递归受单独深度限制。[kP bytecode](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/0903_kP/bytecode.txt:278)、[lF.java:37](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0702/lF.java:37)。

`kX.a(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;Lnet/holdemresources/internal/ld;)[D` 在深度允许且 predicate 允许时，先算即时奖金，再生成下一手上下文、递归求值并映回当前玩家；否则直接调用底层 ICM/KO evaluator。[kX.java:117](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0919/kX.java:117)。

每一深度有一个最多 5000 个局面的 Guava cache。未来局面调用 `qI`：默认当前递归深度 ≤1 时 200 次 sweep，其余 50 次；一次 sweep 调 `qI.a()V`，随后读取各玩家权益。负值若落在 `−max(Σ|EV|×1e−7,1e−10)` 内会归零，否则负值或 NaN 抛错。这些是固定工作量/数值防护，不能解释成已经满足统一可利用度阈值。[kX.java:24](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0919/kX.java:24)。

`qI` 可见 169 档阈值索引、双人/三人数组、局部最佳响应搜索和浮点平滑；`rK/rL` 对 2/3 人概率表构建累计和以加速这些阈值范围计算。FGS 此后端与现代全街抽象 MCCFR 主解算并非同一个算法。更细的策略更新见求解分支报告；这里已经确认调用与边界。[qI.java:155](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/1001/qI.java:155)、[rK.java:11](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0946/rK.java:11)、[rL.java:23](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0949/rL.java:23)。

## 7. 两条真实牌力计算路径

### 7.1 七张具体牌：bitmask → perfect-hash 风格索引 → short rank

`lt` 定义牌序 `2c,2d,2h,2s,...,Ac,Ad,Ah,As`；牌 ID 是 `4*rank+suit`，52 位掩码的第 ID 位代表该牌。`ls` 生成 1326 个两牌组合，按 `hi=0..51`、`low=0..hi−1` 排序，索引为 `hi*(hi−1)/2+low`；还生成具体组合→169 类映射。[lt.java:7](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0709/lt.java:7)、[ls.java:8](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0708/ls.java:8)。

`lu.a([IJ)[I` 将各玩家两牌掩码与最终五张公共牌 OR 后，逐人调用 `lv.a(J)S`。生成随机牌时使用 Commons RNG 的 `XO_SHI_RO_256_SS`；这只是发牌工具，不能仅据此认定上层范围采样无偏。[lu.java:80](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0706/lu.java:80)。

`lv` 静态加载主 JAR 资源 `/net/holdemresources/gamerules/handeval/data/lookup7card.dat.gz`。解压后读取 `262144` 个 little-endian short，共 `524288` 字节。评估方法检查各花色的 rank mask，若同花牌数≥5，折叠为 13 位 rank mask 并与常数 `111541` XOR；否则合并花色的 rank multiplicity，按三重计数掩码分支构造索引，再与一个 64 项整数偏移表 XOR，取 short 排名。[lv.java:76](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0710/lv.java:76)。

**已验证：**主代理对原始 `og/oD/lv/lt` 完成 2528 个规范化/花色映射案例、2318 个七张牌案例、32 个 signed little-endian 解码案例。七张牌以独立枚举 21 种五张牌为 oracle，检查相对排序、平局、九种牌型和全部 24 花色置换。见 [hrc-original-cards-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-cards-validation.json)。这不意味着枚举了全部 `C(52,7)` 手牌。

### 7.2 旧式 169 类 2/3 人预计算

依赖 `net.holdemresources.preflopdata.holdem_1.4.1.jar` 仅有 6 个 Java 类，没有 native 声明。确切读取方法是 `HandEval2Way.load(Ljava/lang/String;)V`、`HandEval3Way.load(Ljava/lang/String;)V`。读到的 double 是 `BitConverter.toDouble([BI)D` 按 little-endian IEEE-754 解码。默认 singleton 载入 `.../data/2wh.dat` 和 `.../data/3wh.dat`；读取器优先相同相对路径的本地文件，找不到才读 classpath resource。没有在此加载器看到生成数据的训练/枚举流程。

| 文件 | 记录顺序 | 每记录 | 记录数 | 实际字节 |
|---|---|---:|---:|---:|
| `2wh.dat` | `0<=h2<=h1<169` | 3 doubles / 24 B | 14,365 | 344,760 |
| `3wh.dat` | `0<=h3<=h2<=h1<169` | 13 doubles / 104 B | 818,805 | 85,155,720 |

2 人结果索引是 `{11,12,21}`，即平局、第一人胜、第二人胜；3 人 13 个弱序为 `{111,113,131,122,123,132,212,221,213,231,311,312,321}`，并有对应玩家位置置换表。`getResults` 先按手牌标签排序求压缩索引，再将结果顺序映回原玩家。不能只存每名玩家单一 equity 而丢掉边池所需的完整胜负/平局顺位。

**独立数据检查：**读取完整 `2wh.dat`，14,365 个记录的和逐一与“该两类手牌合法且互不冲突的有序具体组合数 / (`C(52,2)*C(50,2)`)”比较，最大误差 `1.3552527156068805e-20`；展开玩家置换后全联合概率之和 `1.0000000000000133`，所有值有限且非负。因此这张表存的是**联合手牌类别与摊牌结果的概率质量**，不只是每两类手牌内部归一化的胜率。[format-checks.json](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/format-checks.json)。

`pk` 范围 equity 对正权重范围调用 `addResults`，使用两个/三个范围权重的乘积，最后统一归一化。这与联合概率表的含义一致。**尚未验证：**没有重新穷举所有 board 验证每个摊牌概率；`3wh.dat` 只核对尺寸与读取格式，没有检查全部数据体。若独立实现需要这些表，应独立生成，不能把安装中的专有表打包进应用。

源与字节码在 [preflopdata](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/preflopdata) 下按类序号隔离：`0018_HandEval2Way/src/HandEval2Way.java:21`、`0015_HandEval3Way/src/HandEval3Way.java:21`、`0016_EvalResultHandler/src/EvalResultHandler.java:11`、`0020_BitConverter/src/BitConverter.java:47`。

## 8. 翻后桶文件：资源格式与公共牌映射

### 注册 → 解压 → 格式验证

`pg` 从资源文件名解析 `name.bucketCount.street.digest.dat.br` 六段，street 为 `1/f`、`2/t`、`3/r`；默认偏好 flop 1024 桶、turn/river 256 桶，并在注册资源中选邻近配置。资源注册存在应用可用性判断；本研究不调用、不修改这些判断。[pg.java:21](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0830/pg.java:21)。

`oe.a(Lnet/holdemresources/internal/of;)Lnet/holdemresources/internal/oi;` 以 digest 为缓存键，使用 synchronized map + SoftReference；打开资源 URL，用 `BrotliCompressorInputStream` 解压后交给 `oh`。`of` 保存名称、street、bucketCount、digest、URL。[oe.java:26](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0892/oe.java:26)。

读取器精确签名：`oh.a(Ljava/io/InputStream;ILjava/lang/String;)Lnet/holdemresources/internal/ol;`。它先把解压字节读入内存，逐个 canonical board 读取固定长度行；对 1326 个 hole combo 逐个检查与 board 是否冲突，只给合法组合消费一个 little-endian short，冲突位置保持 `−1`。每行原始字节都进入 SHA-256；行数/结束长度错误抛 IOException，指定 digest 不符返回 null。[oh.java:11](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0872/oh.java:11)。单类反编译把行内 offset 推成 `byte`，而 bytecode 实际是 `int` 局部变量 `iinc`，不能照抄该类型。

### 规范化与列序

对 52 位 board mask，`og.a(J)J` 按 `M=0x1111111111111` 抽出四个花色的 13 位 rank 向量，将四个向量数值排序后按新花色位拼回。`og.b(J)[I` 给原花色→排序后花色的置换，`og.a(J[I)J` 应用置换。`lo` 枚举可能公共牌并去重，再将 canonical mask 升序排列成行索引；不能按扑克牌文本字典序排。[og.java:6](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0895/og.java:6)、[lo.java:18](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0704/lo.java:18)。

`ol.a([I[J)[I` 取该街 board，算出置换及 canonical board 行号，把每个具体手牌也通过 `ls.a(I[I)I` 施加相同置换，再取 `shortTable[1326*boardRow+remappedHole]`。`ol` 的 bucketCount 是实际 shorts 最大值+1，而非仅信任文件名；`ol.a([JI)[I` 返回某 board 下 1326 个组合的完整桶号数组。[ol.java:24](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0889/ol.java:24)。

独立 Python 规范化枚举得到下表。后三列由行数和格式计算；只有第一行的实际资源体已经解压验证。

| street | canonical boards | 合法 hole/行 | 解压行长 B | 完整资源解压 B | 展开1326列 short 表 B |
|---|---:|---:|---:|---:|---:|
| flop | 1,755 | `C(49,2)=1176` | 2,352 | 4,127,760 | 4,654,260 |
| turn | 16,432 | `C(48,2)=1128` | 2,256 | 37,070,592 | 43,577,664 |
| river | 134,459 | `C(47,2)=1081` | 2,162 | 290,700,358 | 356,585,268 |

**实际资源验证：**`net.holdemresources.postflopabstractions.holdem_1.0.0.jar` 有 27 个 `.dat.br` 数据资源、0 个 class，即每街 9 档桶数 64–16384。选定 `Johanson13_2021-02.64.1.5c50391a2dffc81287be70955ad7a86f9f607745f6a1a8f96af159d51db2e22d.dat.br`，仅使用已安装的通用 Brotli decoder 解压到内存：

- 实际解压长 4,127,760 B，与格式完全相符；SHA-256 与文件名 digest 完全一致。
- 2,063,880 个 little-endian signed short 全部在 0..63，64 个桶均出现。
- 独立生成的 1755 个公共牌 mask 升序序列，以 little-endian uint64 串接后的 SHA-256 为 `b5f4eb663ab0657ceb31273943d2aa96c87e025804b65983358464e0c52933ac`。
- 8 个分散公共牌行 × 6 个合法手牌列 × 全部24花色置换，共 1152 个固定样本，独立读取结果全部保持对应桶号。

证据：[flop64-resource-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/flop64-resource-validation.json)、[validate_flop_resource.py](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/validate_flop_resource.py)。完整解压表没有落盘，也没有加入产品。

**原始 reader 全域对照已通过：**主代理审计并扩展 [OriginalFlopBucketProbe.java](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalFlopBucketProbe.java)，只加载 `oh/ol/lo/ls/og/lt/oD/om/oi` 与固定 SHA 的依赖。除 1152 个固定样本、原 `lo` 完整公共牌顺序、错误 digest 拒绝和截断拒绝之外，又穷举 **22,100 个物理 flop × 每个 1,176 个合法 hole，共 25,989,600 个映射**，与独立 rank-vector 花色排序及原始 short 表列序计算逐项比较，全部相符；同时检查冲突手牌的 `−1` 哨兵。结果见 [hrc-original-abstraction-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-abstraction-validation.json)。这验证了**这一个 64 桶 flop 配置**的完整映射域，不包含 turn、river、其他桶数或动态子树抽象，也不评估聚类的扑克策略质量。

### 初始化审计的重要修正

`og` 的反编译源码没有显示 static block，但原始 `<clinit>()V` 实际包含 `getstatic lt.a:[J; pop; return`，见 [og bytecode:1](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/0895_og/bytecode.txt:1)。`lt` 初始化牌名、52 张牌位掩码和 `cdhs` 字符数组，没有应用 IO。原始纯方法探针必须包含 `lt`；只加载 `og` 会 `NoClassDefFoundError`。这一实际发现说明不能以反编译器删掉的“无用表达式”来判断没有初始化依赖。

## 9. 翻后子树的 strict / balanced / relaxed / perfect

`qa.a(Lcom/google/gson/JsonObject;Lnet/holdemresources/internal/pg;)Lnet/holdemresources/internal/ok;` 读取 `engine.configuration.abstractions`。普通翻前起始树使用各街 digest 对应的预计算桶。`subtree.street!=0` 时读取固定 board、每名 active 玩家的 range，走另一组动态映射器。[qa.java:111](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0737/qa.java:111)。

| 配置/实现 | 已确定行为 |
|---|---|
| `buckets=0` / `op` | 空街映射：桶数 0，两种 mapping 方法返回 null；不是单桶或“完整不抽象”。2026-11-05 重新逐方法核对更正。 |
| `perfect` / `or` | 固定当前街 board，对正范围中的合法两牌按仍可交换的花色等价类编号；每名玩家独立压缩 |
| `perfect` / `oq` + `oo/on` | 从固定前一街枚举下一张公共牌，保留公共牌+hole 的联合花色等价关系，然后按玩家范围压缩 |
| `strict` / `ow` | key 包含规范化未来 runout 编码和完整规范化 hole mask |
| `balanced` / `ox,oz,oy` | 保留可能影响同花的手牌花色，把其他牌压成 rank 特征；flop/turn/river 使用不同规则 |
| `relaxed` / `oA,oC,oB` | 更积极合并无关花色，river 还可合并不影响同花完成的公共牌花色 |
| 正桶数的 turn/river 子树分支 | 选注册中大于16000桶的资源，再按固定 flop 和玩家范围压缩，不是直接把用户数字当随机聚类数 |

`ov.<init>([JILnet/holdemresources/internal/ou;[[D)V` 枚举固定前缀之后的必要公共牌扩展、所有合法 hole combo，通过 `ou` 构造 `ot` key，排序去重，然后仅保留每名玩家正范围能到达的 key 并密集编号。非法/不可达组合为 `−1`。`oo` 做现有桶→玩家有效桶映射；`on` 验证固定公共牌前缀。[ov.java:18](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0886/ov.java:18)、[oo.java:70](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0875/oo.java:70)。

`os.a([JJ)Lnet/holdemresources/internal/ot;` 不只是对最终 board 重新排序：它沿公共牌历史逐步细化仍可交换的花色，并以 base52 编码后续发牌，再生成 hole 特征。因此不能只保留最终 board 而丢弃到达顺序，尤其是转牌与河牌的花色历史。[os.java:13](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0877/os.java:13)。

可落实的两个具体例子：`oy` 的 river balanced key 对 hole 的每张牌，若该花色在 **turn board** 出现 >1 张就保留精确花色，否则只加该 rank 的计数。`oB` 的 river relaxed 分支先检查 river card 花色在 turn board 的计数；少于2时可将其公共牌特征折叠为 rank，否则附加花色标记。[oy.java:11](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0878/oy.java:11)、[oB.java:14](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0882/oB.java:14)。

`perfect` 不是所有起始街/未来街的无条件选项：`qa` 的 river perfect 分支在 subtree 起始 street=2 时使用 `oq`，street=3 时使用 `or`，其他情况抛 `Not implemented yet.`。加载后还对 `buckets` 和每玩家 `effective` 数量做一致性检查。**未知：**没有对这些动态 key 做完整数值对照，不能单凭“strict/perfect”标签保证与无抽象游戏完全等价，也没有恢复 Johanson13 数据的训练目标、距离函数、聚类初始种子或训练流程。

## 10. 原生边界与可隔离测试范围

主代理 ASM 对主 JAR 986 类、5847 方法检查：无 `ACC_NATIVE` 方法。此结论只限该 JAR。补充依赖静态扫描覆盖 preflopdata、postflopabstractions 和 maven 14 个 JAR，见 [dependency-inventory.json](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity/dependency-inventory.json)。

| 依赖 | 与本链的关系 | 扫描结果 |
|---|---|---|
| preflopdata 1.4.1 | 2/3人概率表读取 | 6类，0 native方法，0本地库 |
| postflopabstractions 1.0.0 | 27个桶数据资源 | 0类，0本地库 |
| Commons RNG 1.6 四个JAR | 发牌随机数 | 无 native声明/嵌入本地库 |
| Brotli dec 0.1.2 | 解压桶资源 | 19类，无 native声明/嵌入本地库 |
| jquantlib 0.2.4 | MTT积分/CDF | 1144类，无 native声明/嵌入本地库 |
| Eclipse Collections 11.1.0 | canonical board primitive set/map | 5480类，无 native声明/嵌入本地库；单独补审 |
| truffle-api 25.0.1 | Graal/JavaScript运行时辅助 | 2个 native声明，5个跨平台本地库 |

发现的两个具体声明是 `com/oracle/truffle/api/impl/Accessor$JavaLangSupport.registerJVMTIHook()V` 与 `com/oracle/truffle/polyglot/JDKSupport.addExports0(Ljava/lang/Module;Ljava/lang/String;Ljava/lang/Module;)V`。库资源包括 `META-INF/resources/engine/libtruffleattach/windows/amd64/bin/truffleattach.dll`（13,824 B），及 Linux/Darwin 的 amd64/aarch64 版本。这是 Truffle/JVM 模块与 attach 辅助边界；没有证据表明它是扑克 ICM 或牌评估数学内核。

扫描 native 声明及常见 `.dll/.so/.dylib` 后缀不能排除所有动态生成代码、JDK 本身 native、反射加载或安装中未纳入本次范围的 SWT/UI 本地库。没有对整个安装做“零 native”判断。

| 原方法候选 | 最小已知闭包 | 状态与可证明范围 |
|---|---|---|
| `kW.a([D)[[D` + `kU.a([D)[D` | `kV/kU/kW`，JDK | 原始字节码41案例通过；普通正筹码ICM |
| `oD.a([BI)S/I/J` | `oD`，JDK | 32案例通过；有符号小端读取 |
| `og.a(J)J`、`b(J)[I`、`a(J[I)J` | `og/lt`，JDK | 2528案例通过；花色规范化 |
| `lv.a(J)S` | `lv` + 固定七牌查表资源，JDK | 2318案例通过；具体7张牌排序/平局 |
| `oh.a(InputStream,int,String)` → `ol.a([I[J)[I` | `oh/ol/lo/ls/og/lt/oD/om/oi` + Eclipse Collections | 此单一64桶flop配置25,989,600合法映射全域对照通过，另核对冲突哨兵/文件校验 |
| `lg.a([D[DID)D` | `lg` + jquantlib CDF初始化及必要依赖 | 未执行；下一步可与独立Poisson-binomial递推对照 |
| `kB` 即时悬赏、`kC` 淘汰奖金 | `kI/kG/lE`接口与少量上下文/动态代理 | 静态公式已明；未执行，先审核完整初始化闭包 |

## 11. 独立实现可以采用的行为规格与尚未解决问题

独立应用应把 `发牌/合法私牌联合分布 → 真实牌排名 → 主池/边池结算 → 即时淘汰/击杀奖金 → 未来局面估值` 明确分层。具体七牌排名、ICM 奖金贡献和桶编号是不同概念，不能互换。对任意给定范围，应先处理 card removal，再对完整胜负/平局结果加权；2wh 的联合频率核验已经给出这一点的原始数据证据。

从本报告可以独立实现并单独验证：普通 ICM、同手淘汰顺位、固定 KO/PKO 即时奖与悬赏滚入、筹码比例 bounty 终端模型、MTT 精确 integrand、花色规范化、确定的抽象资源读取接口。可以用自行生成的数据或明确设计的独立抽象替代专有桶。**这些是可实现的模块规格，不是已交付应用已经全部实现的声明。**

仍未闭合的关键问题：MTT 大场近似的全域误差；FGS 限制对复杂多人局面的影响；全部 27 个桶资源的一致性；动态 perfect/strict/balanced/relaxed 与玩家范围压缩的所有数值对应；桶训练流程；3 人概率表的所有权重及摊牌概率；整局求解器的最终范围/可利用度与 HRC 的对照。原始 ICM 与牌评估探针通过，不能替代这些验证。

静态复现工件包括 `inspect_dependencies.py`（native/资源库存与6个预计算类反编译）、`format_checks.py`（公共牌轨道/2wh联合频率）及完整 JSON 结果，位于 [equity 分析目录](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/equity)。实际资源验证和样本再生已独立整理为 [validate-hrc-abstraction-resource.py](D:/Users/Shao/Documents/ChatGPT/REA/scripts/validate-hrc-abstraction-resource.py)，依赖同目录 `hrc_classfile_metadata.py` 与 `scripts/java/BrotliResourceBytes.java`；即使删除 analysis 输出，也能重新读取用户安装的资源，在内存解压并生成测试输入。执行 `python scripts/validate-hrc-abstraction-resource.py`，再执行主代理的 `python scripts/validate-hrc-abstraction.py` 可重做资源/schema及原 reader 全域映射对照。脚本本身不含专有资源数据。
