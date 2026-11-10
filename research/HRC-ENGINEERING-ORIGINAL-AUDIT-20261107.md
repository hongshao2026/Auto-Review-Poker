# HRC 原版采样工程实现：限定只读审计，2026-11-07

结论：已经恢复并验证的遍历、策略更新和收益公式，并不表示工程实现已与 HRC 对齐。本次静态复核发现三个具体差异：**原版终局收益预计算并查表、按数组单元做原子更新、worker 自主领取 250 样本批次**。当前独立内核仍有每个 deal 的终局结算、整节点互斥、每 250 样本/worker 的全员汇合。它们是有代码证据的优化候选；本次没有运行 profiler，不能给出各自耗时占比或保证优化倍数。

## 证据身份和范围

- 原 JAR：`D:/Program Files/HRC/plugins/net.holdemresources.calculator_4.1.0.202603231401.jar`，SHA256 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。
- 复用全量 ASM 索引 `analysis/hrc-deep/bytecode-index.jsonl`、既有 `solver/*/bytecode.txt` 与 `sources/*/*.java`。本轮额外只读 `javap -p -c -s mh me kL` 输出：`analysis/hrc-deep/engineering-audit-20261107/terminal-bytecode.txt`，SHA256 `73adcd76ff1febb3d7e7aa71a8af72a1730130b2d8ada98b32c7ca8e3c27721f`。
- 当前独立源码快照，2026-11-07 01:19:48 UTC：`native/hrc_research_solver.cpp` SHA256 `c6c522239c86c56d5b64ffa977287114f6cf4d4c09430ae98000776d1412eccc`；`native/hrc_parallel.hpp` SHA256 `0e717557fac02a0bcb78bea1a42fdb2d126f2ee3e6ca4f72e73f00eb08c42ae8`。后续编辑会使行号/结论适用快照改变。
- **observed** 表示直接静态证据或明确列出的既有探针结果；**inferred** 表示从这些事实推断的影响；**unknown** 表示本轮没有量化或没有覆盖。未操作 GUI、未启动原版采样、未修改 JAR/产品代码、未使用共享 REA 会话。
- 反编译存在同名不同 descriptor 字段和类型简化，精确签名以 ASM/javap 为准。例如 `lH.a(...)` 字节码返回 `lF`，部分反编译显示父类型 `lE`。

## 1. 终局：原版在训练前计算收益表

**observed：当前被审计 `mh` 训练路径确实是查表，不是在每次终局重新运行 sidepot/ICM。**

| 原类/方法（省略公共包 `net/holdemresources/internal/`） | 精确事实与锚点 |
|---|---|
| `mh.a(I)I` | 结果数 `N = round(3^max(0,L-1))`。`sources/0040/mh.java:19`；新 terminal-bytecode:26。 |
| `mh.<init>(Lmf;Ljava/util/List;LlK;Lmi;)V` | `L = lK.a:[I.length` 是仍在终局争夺筹码的 live 座位数；`P = mi.a:LkG;.a()I` 是输出权益向量宽度。分配 `double[N*P]`。源码 :28–55；字节码 :168–183。`kG.a()I` 默认返回筹码数组长度，`sources/0908/kG.java:14`。 |
| `mh.a(LlV;IIDI)D` | 单目标直接读取 `table[index*P+target]`；`N=1` 直接读取 target。源码 :131–137；字节码 :383–413，`daload` 位于 BCI 46。 |
| `mh.a(LlV;I)[D` | 同样 index，复制该 P 元素区间；`N=1` 直接返回表。源码 :74–82；字节码 :220–256。它仍有 vector 路径数组复制，不能称原版完全无分配。 |
| `me.a([I[I[I)I` | 三进制 key，见下。源码 `0042/me.java:4`；字节码 :480–528。 |
| `mh.a(Ljava/util/Map;)V` | 每个 index 解出代表 ranks，经原结算器得到 `lE` key，读取已计算 Map，再复制 P 项到表。源码 :96–101；字节码 :273–312，BCI36 为 `lH.a(LlK;[ILjava/util/List;)LlF;`，BCI39 为 `Map.get`。 |

### 编码不是所有手牌排名全排列

先按 live 玩家累计投入 `lK.b:[J + lK.c:[J` 降序排列，相等按 live 序号升序；存为 `order`。**这里不是 remaining+paid**。`mh.java:28–52`；`lH.java:98–117` 同样用 b+c 并处理 uncalled return。

取 `best = rank[live[order[0]]]`，从下一位开始：

```
digit = 1 + compare(rank[live[order[i]]], best)   # 0=更弱，1=相等，2=更强
index = 3*index + digit
best = max(best, rank[live[order[i]]])
```

该 key 只保留相对先前最佳牌力的关系。`me.a(I[I)[I` 以倒序读取三进制位并生成代表 ranks：初始标号9，弱者设0；相等/更强设当前标号，更强时递减标号；最后设置首位。源码 `me.java:16–31`，字节码 :530–585。它不是将所有不同严格次序/平局全排列一一编号；投入排序与 sidepot eligibility 是这个压缩的关键前提。

内存的 double payload 为 `8*P*3^(L-1)` 字节/leaf，另加对象/数组等开销。例如 P=3,L=3 是216字节；P=9,L=4 是1944字节；P=10,L=10 是1,574,640字节。大 live 数和大量叶子可能导致巨大内存，不能无限制预计算；应先统计实际各叶 L，设预算并使用共享、去重或显式拒绝。不可用座位总数 P 误代 L。

### 构建/填表调用链

1. `ml.a(Lmf;ILrD;Lmi;Lld;Z)Lmj;` 在零孩子状态建立 `mh`，`sources/0015/ml.java:21–30`；ASM 索引 :464。
2. 正常新手牌 `jN.run(IProgressMonitor):IStatus` 收集叶子、准备权益、计算、赋值，之后才运行初始10m采样。`sources/0110/jN.java:40–53`、:81–84；ASM 索引 :10114。
3. `kL.a(List,ph):Set` 并行收集叶子的 `b()`，`Collectors.toSet()` 去重 outcome keys；源码 `0931/kL.java:10–11`，字节码 :587–604。
4. `kL.a(kG,kK,Collection,ld):Map` 并行调用具体权益模型 `kK.a(kG,lE,ld):double[]`；源码 :24–32，字节码 :620–639 与 lambda :670–685。
5. `kL.a(List,Map,ph):void` 并行分发，调用 `mh.a(Map)` 完成表；源码 :14–20，字节码 :605–618。

**observed：模型入口是通用 `kK`，不是写死 ChipEV。** 但本次没有枚举每个 UI 模式到 `mh` 的完整构造链，不能据此声称所有可选模型、FGS 深度、动态子树都已完成等价验证。既有 `reports/hrc-original-hrcz-leaves-validation.json` 有 HU ChipEV、八人 ChipEV、八人 ICM+PKO 的原保存1024向量与独立生产结算/权益生成逐项对照；它证明那些存档，不是任意配置。

### sidepot / 平局 / odd chip 不能跳过

`lH.a(LlK;[ILjava/util/List;)LlF;` 调四参数实现。`sources/0699/lH.java:86–220` 明确包含 uncalled return(:113–117)、按牌力和投入构组(:120–126)、逐层筹码/死人投入(:158–169)、rake(:172–176)、平分与整数余数(:179–185)、退回剩余投入(:190–193)、淘汰获奖者(:165–166)、守恒(:202–211)。FGS/KO/PKO 的结果还可能依赖 `lF` 的 participants/tied/winner 信息，不只是最终筹码。

**inferred：** 在合法原树/当前独立结算已支持域内，可用独立结算器提前生成这种表，不读取原档的终局 utility 作训练输入。应首先以现有 `native/hrc_hrcz_leaves.cpp` 和独立导出生成路线为基础。**unknown：** 所有合成代表状态是否在每个新模型/特殊 ante/rake/FGS 配置下都保持相同语义，仍需逐模型 oracle 与全叶对照。原保存表 float32 也不能替代原 live double 表的精度证明。

### 当前 native 差异

`Engine::terminal()`，`native/hrc_research_solver.cpp:361–390`：按 epoch 缓存每个终局，但新 deal 的首次该叶仍执行 pot winners、整除余数以及可选 monetary/FGS/rake 计算。`card_independent` 终局跨 deal 缓存；不能称所有叶每次都重算。每 worker 复制 `terms`/pots 和权益缓存，见 `native/hrc_parallel.hpp:43–60`。原 `mh` 表在共享树中，各 worker 共用，只把 deal/ranks/scratch 分开。**inferred：** 预计算能减少采样热路径工作和私有终局内存，但应计入预计算时间及 payload/去重内存，不保证净收益或固定加速倍数。

## 2. 原子单元更新与整节点互斥的差别

**observed：默认原 preflop `mE`(23)、postflop `mA`(25) 没有整节点 monitor/锁。**

- `mf.<init>` 按 street0/nonzero 选择 mE/mA，`sources/0013/mf.java:24–29`。
- `mt` 持有 `double[]` 和 `MethodHandles.arrayElementVarHandle(double[].class)`，`sources/0027/mt.java:9–19`。
- 策略读取 `mt.a(IZ[DI)V → mv.a([DIIZ[DI)V`：普通数组读、正 regret 归一化，2/3动作有专门分支。`mt.java:43–44`、`sources/0016/mv.java:12–25`、:45–88。本路径没有形成一整行原子快照的额外锁。
- `mE.a(Lma;[DIIDD)V` 用 LongAdder.increment()，稀疏 weakCAS 更新缓存计数，然后逐 R/A/D 单元 `VarHandle.getAndAdd`。`mE.java:48–75`；`solver/0021/bytecode.txt:181–207`、:216–256。`ma.a(D)Z` 的刷新判定为 `nextInt()%floor(sqrt(t))==0`，`sources/0011/ma.java:22`。
- `mA.a(Lma;[DIIDD)V` 的计数也为 array VarHandle.getAndAdd，R与共享 A 逐单元更新；`mA.java:40–65`，`solver/0026/bytecode.txt:123–183`。
- ASM 方法 access：mE更新 :938=17、mA更新 :1431=17（public final，无 ACC_SYNCHRONIZED）；整采样任务 `mn.a(ILmc;Lmd;)V` :1948=49（public final synchronized）。**后者锁住调度入口并不表示所有内部 worker 的每次遍历被串行化。**

当前 `Engine::choose()` 与 `update()` 分别整节点锁，`native/hrc_research_solver.cpp:311–317`。choose 锁覆盖策略读取归一化与 RNG抽样；update 锁覆盖期望值求和、计数刷新、所有动作 R/A/D 更新（Node.update :123–134）。递归不在这把锁内，不能说整个树只有一个锁；但同一节点不同 bucket 仍相互排斥。所有路径频繁访问的浅层节点更容易产生争用，这是**inferred**，尚未采集等待时间。

原版训练在多个单元写之间允许其他线程读到混合进度；独立版把一次节点更新作为临界区。数值单线程 probes 相等并不能证明并发轨迹相等。若改 C++ 原子路线，必须保证所有并发读/写均遵守 C++ 内存模型；不能简单删除 mutex 后读写普通 double，造成 data race/未定义行为。还需要研究 atomic double CAS/LongAdder 等价计数器、缓存一致性、相应回归与吞吐实验。

## 3. 任务调度：250 是抢领粒度，不是原版固定全员栅栏

原 `mn.a(ILmc;Lmd;)V` 建 ForkJoinPool，并启动指定数量长驻 worker；每个持有自己的 hole数组、4街board数组、RNG、range sampler 与 `ma` scratch。`sources/0034/mn.java:73–98`。循环 `AtomicLong.getAndAdd(250)` 自主领下一批，成功样本另有 LongAdder、root值 DoubleAdder，:98–118；字节码 `solver/0034/bytecode.txt:853` 是原子领取。

批末只有 `mo.a:AtomicBoolean.get()` 为 true 才两次 `CyclicBarrier.await()`，`mn.java:172–180`；`mo` 构造 `workers+1` parties，`sources/0008/mo.java:10–14`。该结构用于协同暂停/观测。**不是每批无条件全线程汇合。**

独立主循环 `native/hrc_research_solver.cpp:599` 每次提交最多 `250*threads`；`ParallelTrainer.run()` 平均分配并等待全部 worker，`native/hrc_parallel.hpp:72–86`。随后归并统计/RNG，下一批重新唤醒。**inferred：** 随机遍历路径工作量不一时，慢 worker 会让其他 worker 批末等待；高频 condition-variable 唤醒/汇总有固定成本。**unknown：** 本机具体 idle/straggler 占比、是否比锁和终局结算更大，未量化。

优化候选是持久 worker 自主获取任务、控制操作才停在安全点；要保留准确取消、CI一致快照、可恢复状态与训练计数语义，不能以无同步快照换吞吐。

## 4. 存储、缓存、随机与精度

| observed 原版 | 当前独立实现/范围 |
|---|---|
| `ma` 每 worker 一个初始1024 doubles scratch，必要时按2的幂扩大；`sources/0011/ma.java:7–19`。`mf` 用偏移为递归传 P/Q 共用缓冲，`0013/mf.java:75–113`。 | `scalar/vector` 栈上 `double p[MAXA],q[MAXA]`，主CPP:398–417。都是复用/栈上 scratch；不能笼统声称我们每节点动态分配。 |
| 每 deal `lV` 懒加载各街整桌 bucket；第一次牌力请求时一次评估全部座位并缓存。`0029/lV.java:52–75`。 | Engine 每座位按需 rank 与 bucket，board规范化row复用，winner-mask按eligible缓存，主CPP:336–359。我们已有原版未在此路径显露的额外缓存，不是完全无缓存。 |
| 训练23/25为 double[]，31 `mw` 分段double[][]（16384以内且对齐行宽），`0018/mw.java:16–43`。 | Node.raw/vector<double>；两者训练64位。原31的分段不是默认25的证据。 |
| `mt.a()[B` 保存为float32，`mt.a([B)V` 读float再放double；`0027/mt.java:106–129`。 | 不可因hrcz是float32而说原版训练是float32、或者将double改float当等价优化。精度/恢复误差另测。 |
| `lu` 默认XO_SHI_RO_256_SS，不传固定seed；洞牌按1326 combos抽样并排冲突，公共牌按单张抽；`0706/lu.java:8`、:30–51。 | 同家族RNG仍不等于随机序列一致：当前从52张逐张抽两张再编码，主CPP:327–334，bounded RNG实现不同。均匀分布可相同，单次路径不相同。 |
| 原 mf v4 vector/scalar 分支、special CHECK路径和marker已有数值探针。 | 当前constant_scalar shortcut主CPP:400–403省掉部分无效递归并改变RNG调用轨迹；有数学前提，不能宣称同seed同路径。 |

## 优先级与不能下的结论

1. **终局表与并发更新是已有证据的主要工程缺口**：先统计/计量，再在独立公式上实现；保留各种收益域边界。
2. **批次尾部汇合是第三个具体候选**：通过每worker忙碌/等待统计区分调度开销，控制一次只改一个变量。
3. 当前不能回答“差多少全由哪一项造成”：没有 JFR/native采样 profile、硬件性能计数、锁等待、内存带宽/缓存miss等归因。也未证明 JIT 内联/SIMD/GC 的净效果。
4. 本轮不等于恢复完整原工程：原构建系统、JIT运行时优化、依赖内部实现、全部特殊模型以及所有并发交错仍不完整。源级公式/拓扑/抽象正确性、并发数值行为、策略质量与速度，是需要分别验证的层次。
5. CI达到10是对应实现的稳定性指标，不等于已证明Nash exploitability或每手牌准确。加速后仍应保留双实现相同树、相同资源、线程数、实测CI轨迹和跨seed策略差异的验收。
