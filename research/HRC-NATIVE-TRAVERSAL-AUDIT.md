# 当前 native 遍历的独立字节码对照

本轮没有发现 native 在默认权重 `w=1` 下的标量/向量遍历、采样返回值、marker 传播或 `mE/mA` 更新公式与原始字节码不一致。新增 200 组嵌套合成案例、3,200 个逐步快照，共 136,960 个数值完全一致，最大绝对误差为 0。结论只覆盖下述输入域与执行方式；它不是九人整局均衡或 HRC 全产品等价证明。

执行报告：[hrc-original-nested-traversal-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-nested-traversal-validation.json)。执行时 native 主文件 SHA-256 为 `1378e89e2c5381a9d932eea0b4f82d22f3114e29f9cacea87895a10609675c36`；原始主 JAR SHA-256 为 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。报告记录了实际命令、所有探针/内核源文件哈希、原始加载类哈希、输入哈希及独立探针可执行文件哈希。

## 已核对的分支与公式

| 项目 | 原始字节码证据 | 当前 native 对应 | 审计结论 |
|---|---|---|---|
| scalar 先采样，后判断 target/gate | `mf.a(lV,int,int,double,int):double`，descriptor `(Lnet/holdemresources/internal/lV;IIDI)D`，BCI 26–104 | `Engine::scalar` | 顺序相同。先抽行动也会消费 RNG，不能挪到 gate 之后。 |
| 跳过或其他 actor 的递归 | 同方法 BCI 107–140 | `scalar` 的最后一个 return | 只有 actor==target 被 gate 跳过时 depth+1；其他 actor 不增加 depth。原 marker 原样传递。 |
| 展开目标玩家所有行动 | 同方法 BCI 141–205 | `scalar` 的 for 循环 | 每个子树保持 depth；仅选中行动继承 marker，其余为 0。 |
| scalar 更新与返回 | 同方法 BCI 208–251 | `n.update(...,1,marker); return q[chosen]` | 原始更新参数为 `w,marker*w`；返回 **抽中行动的 Q**，不是 `sum(p*Q)`。 |
| vector 抽中子树 | `mf.a(lV,int):double[]`，descriptor `(Lnet/holdemresources/internal/lV;I)[D`，BCI 72–109 | `Engine::vector` | 抽中子树继续 vector；取其中当前 actor 的分量用于本节点更新，整条向量作为返回值。 |
| vector 未抽中子树 | 同方法 BCI 112–198 | vector 中另外两个分支 | 一般 scalar(target=当前 actor,depth=0,marker=0)；action0 且 special==2 时另有 1% vector 调用。 |
| vector 更新与返回 | 同方法 BCI 212–248 | `n.update(...,1,1); return result` | 更新用 `w,w`，返回抽中子树向量；不是每个行动向量的期望。 |
| v4 gate | `lV.a(UniformRandomProvider,Integer):boolean`，descriptor `(Lorg/apache/commons/rng/UniformRandomProvider;Ljava/lang/Integer;)Z`，BCI 0–20 | `rng.bound(depth+2)!=0` | 原始跳过谓词 `nextInt(2+d)==0`，native 用其补条件决定展开。 |
| 探索与动作采样 | `lV.a(double[],int,int,double):int`，descriptor `([DIID)I`，BCI 0–123 | `Engine::sample` | 相同 `epsilon=1/sqrt(cachedCounter+10000)`；探索覆盖所有行动，随后检查概率1与累计抽样。 |
| `mE` 计数与更新 | `mE.a(ma,double[],int,int,double,double):void`，descriptor `(Lnet/holdemresources/internal/ma;[DIIDD)V`，BCI 94–233 | `Node::update` street0 | LongAdder/updates 每次增加；`t=cachedCounter+1`；随机刷新时 t 改为精确次数并尝试写缓存；`R+=t*w*(Q−V)`、`A+=t*p`、`D+=t*w`。marker/z 不参与翻前 A。 |
| `mA` 计数与更新 | 同 descriptor，`mA` BCI 75–198 | `Node::update` street>0 | t 为节点级计数加1，按桶更新 R；仅 z>0 时共享 `A+=t*z*p`。计数不是每桶独立计数。 |

对应反汇编：[mf](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/0013/bytecode.txt:158)、[lV](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/0029/bytecode.txt:69)、[mE](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/0021/bytecode.txt:119)、[mA](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/solver/0026/bytecode.txt:71)。当前实现：[更新](D:/Users/Shao/Documents/ChatGPT/REA/native/hrc_research_solver.cpp:55)、[采样及遍历](D:/Users/Shao/Documents/ChatGPT/REA/native/hrc_research_solver.cpp:127)。期望值 `V=sum(p*Q)` 用于 regret baseline；它与递归返回的 sampled Q 语义不同。不能为降低方差而直接把当前递归返回替换成 V 并仍声称保持原算法。

## 新探针的具体覆盖

[OriginalNestedTraversalProbe.java](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalNestedTraversalProbe.java) 复用已审读 `OriginalTraversalProbe` 的白名单 ClassLoader，通过原始 `mf` 构造函数建立合成嵌套树。每个决策节点使用两个桶，两个玩家分别固定到桶0、桶1；树含翻前/翻牌/转牌/河牌节点。叶子仍是原始 `mh`，但是唯一收益表项由探针提供；bucket 与 rank cache 明确作为合成输入设置。没有调用真实发牌、真实桶映射或真实结算。本次最终运行加载 31 个 HRC 类与 1 个 Commons RNG 接口，**没有读取任何原始资源表**，没有启动 HRC 应用/OSGi/GUI/许可组件。

[nested_traversal_probe.cpp](D:/Users/Shao/Documents/ChatGPT/REA/scripts/native/nested_traversal_probe.cpp) 直接 include 当前 native 源文件，只重命名其 main，使用真实 `Engine::scalar/vector` 与 `Node::update`。原内核源文件、正在执行的生产可执行文件和 60m 训练目录均未修改。C++ 使用与原 Java 探针代理相同的 xoshiro 流；这是人为控制随机输入的数值对照，不是声称 native seed 与 HRC 默认线程 RNG seed 同义。

测试矩阵是 5 类树 × v3/v4 × 5 种调用 × 4 个种子 × 16 次连续调用：

- 五类树：常规嵌套树；根 actor 改为另一玩家；第二行动为 CHECK 且子树是决策节点（special2）；第二行动为 CHECK 终止叶子（special1）；含三个行动的 special2 树。
- 五种调用：vector；scalar target0/depth0/marker0；scalar target0/depth0/marker2.75；scalar target1/depth0/marker1；scalar target0/depth2/marker1。
- 四个种子：42、43、45、9。种子45使 special2 根未进入 epsilon 探索但触发额外 1% vector；种子9使第一个动作采样进入 epsilon 探索。
- 每一步核对返回值、所有决策节点完整 raw 数组、精确 update 次数、三类 RNG 调用计数。原始侧同时记录 bounded RNG 的每一个 bound。
- 覆盖 gate/exploration bound 2、3、4、5、6；观察到 480 个翻前节点快照的缓存 counter 落后于精确更新次数，这些位置也逐项一致。
- 种子45的第一次 vector：special2 的未选中 action0 子树根更新1次，special1 的对应子树根更新0次，明确区分1%分支。
- 在 1,626 个 marker0 且后街节点实际更新的快照中，共享 A 仍全0；本节点 regret/计数照常更新。

复现命令（不启动原应用）：

```powershell
.venv/Scripts/python.exe scripts/validate-hrc-nested-traversal.py
```

全部合成输入由该脚本生成，保存在 `analysis/hrc-deep/nested-traversal/synthetic-cases.txt`。原始输出为 `2-stdout.jsonl`，native 输出为 `3-stdout.jsonl`，各命令 stderr 单独保存。删除 analysis 后也可从 scripts 重新生成，不需要保存任何专有策略或资源表。比较器检查记录数量、数组维度、有限数值与计数；接受阈值为 `1e-10+abs(original)*1e-13`，本次实际误差均为0。

## 已确认的执行差异与解释边界

**缓存计数器的外部刷新节奏不同。** 原 `mE.a():void`（BCI 0–18）将 LongAdder 写回 raw[0]；`mt.c():void` 和 `mt.a():byte[]` 会走此刷新。CI 测量路径也先调用 `mx.c()`。native 的 `save()` 写出 raw[0] 与独立 updates，保存本身不会刷新 raw[0]。两者会因保存/CI时机产生探索率与 t 权重的轨迹差别。新探针验证的是不插入外部刷新时的更新等价，不覆盖这个时序差别。当前没有证据将早期2.13BB误差归因于此；不能将这项差异描述成已定位的系统性收益偏差。

**并发读写与 RNG 轨迹不同。** 原始执行器按250样本批次交给线程池，节点存储使用 atomic add、LongAdder 和 weakCompareAndSet；native 本轮为单线程。原始 CAS 可能失败，且读取策略与其他线程写入可能交错。本次单线程字节码探针观察到的 CAS/更新均与 native 相同，不证明并发交错等价。native 的独立 RNG/发牌实现与 HRC 默认每线程 RNG 的消费顺序不同；使用相同整数 seed 不能要求训练数组逐位一致。

**存档数值精度不同。** 原 `mt.a():byte[]` 将 double 存储量化为 float；native 自己的 checkpoint 保留 double。仅用于读取参考策略时应考虑小量舍入差异；若原程序曾由存档恢复后继续训练，量化还会改变后续数值轨迹。它不构成当前 root 策略差异的已证实原因。

**适用模型仍有限。** 本探针中 `lV.a:D` 取默认1，树为两个玩家的合成子树；不覆盖有锁定策略的 `my`、加权子树发牌、非1 context权重、真实9人牌面/抽象/终局结算或收敛保证。实际九人20BB配置的拓扑回放、牌评估、资源桶映射及独立终局结算需结合各自已有证据与最终多seed训练对照。根平均频率接近也不代表所有深层节点已收敛。

本轮审计结论：保持现有内核运行，等待独立 seed 的完整训练与逐节点误差结果。现有逐分支静态证据和嵌套字节码测试支持当前 traversal/update 实现；尚无证据支持为追逐早期频率而修改采样返回值、marker 或计数权重。
