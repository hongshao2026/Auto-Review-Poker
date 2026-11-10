# 八人15BB BTN：逐手牌差异的实现审计

本轮只读检查现有原始字节码、独立内核、存档、桌面记录和数值探针；没有改内核、覆盖旧证据或启动训练。对象是八人15BB、前五人弃牌后 BTN 的节点5，动作顺序为 fold / raise-to-2BB / all-in-15BB。固定基线为 native seed43、60,000,000全树样本，对照 HRC 保存根计数约60,000,500。

**结论：整体频率接近不能证明逐手牌准确。本轮没有定位足以解释差异的确定实现错误；也没有证据证明这些差异全部无害。** 既有原字节码探针缩小了若干实现错误的可能范围，不能排除未覆盖路径、集成错误或双方都未收敛。

机器可读证据、源文件哈希、选定手牌完整数据和数值推导保存在 [hrc-strategy-difference-audit.json](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-strategy-difference-audit.json)。以下“观察”指文件/代码/图像中的直接结果；“推导”明确从这些结果计算；“候选解释”尚无因果验证。

## 1. 整体接近确实掩盖了逐手牌差异

**观察与算术推导。** BTN 总加注比例 native 25.0005%、HRC 25.0711%，仅差 −0.0706个百分点。但按169类的1326组合权重，逐手牌同一加注行动的加权绝对差是 **4.5066个百分点**：正向差贡献 +2.2180，负向差贡献 −2.2886，几乎抵消。弃牌、加注、全下三行动共同 MAE 为3.0473个百分点，最大单项82.1982个百分点。[固定节点数据](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-native-eight15bb-btn-node.json)；[聚合权重代码](D:/Users/Shao/Documents/ChatGPT/REA/preflop_lab/hrc_research.py:48)。

这个总量按通常的6/4/12组合数量计算，表示范围图的均匀组合摘要。它没有按“五人已弃牌”后的真实条件手牌概率加权，也不衡量策略损失或可利用度。

| 手牌 | native / HRC 加注频率 | native 本手更新次数 | native 历史 raise EV | HRC 历史 raise EV | native / HRC 历史 shove EV |
|---|---:|---:|---:|---:|---:|
| A6s | 92.54% / 10.34% | 72,758 | +0.17668 BB | +0.15499 BB | +0.14225 / +0.20784 BB |
| T7s | 85.23% / 5.64% | 68,104 | +0.02737 BB | −0.02252 BB | −0.27192 / −0.13898 BB |
| A2s | 84.29% / 8.08% | 72,193 | +0.11410 BB | +0.07722 BB | +0.04525 / +0.10191 BB |
| K3s | 4.92% / 67.19% | 67,825 | −0.06963 BB | +0.00902 BB | −0.32143 / −0.25524 BB |
| QTs | 68.06% / 2.66% | 72,178 | +0.19010 BB | +0.28384 BB | +0.21757 / +0.30570 BB |

上述 EV 都是下节定义的**训练历史相对弃牌估计**。A6s 的 raise−shove 在 native 为+0.03443BB，HRC 为−0.05285BB，排序反转。T7s 和 K3s 则连 raise 相对 fold 的符号都不同。它们处在小价值差容易影响行动选择的区域，是值得检查的候选；没有误差条与冻结策略评估，不能据此认定为精确等EV、任意混频或已经找到不同均衡。

60m 是全树发牌数；BTN 自己更新22,646,124次，A6s仅72,758次。这些仍是自适应、加权的训练更新，并非72,758个独立同分布的最终策略评估样本。当前记录缺少构造有效误差条所需的独立评估与二阶统计。

## 2. EV 与策略平均的口径已经核对

**观察。** 原始 `mE.a(ma,[D,int,int,double,double):void`，descriptor `(Lnet/holdemresources/internal/ma;[DIIDD)V`，更新为：

```
V = sum(p[a] * Q[a])
R[a] += t*w*(Q[a]-V)
A[a] += t*p[a]
D += t*w
```

t 来自**本节点**精确/缓存更新计数；负 R 没有截断存回0。取当前策略时才归一化正 R。翻前展示归一化 A，后街 `mA` 的逐桶展示则取当前 R，其共享 A 另存。native 对应实现是 [Node::update](D:/Users/Shao/Documents/ChatGPT/REA/native/hrc_research_solver.cpp:55) 和 [存储读取](D:/Users/Shao/Documents/ChatGPT/REA/preflop_lab/hrc_native.py:253)；原始证据是 [mE.java](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0021/mE.java:48)、[mA.java](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0026/mA.java:39)、[mt.java](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0027/mt.java:48)。

`mt.b(I)[D` 返回 `(R[a]-R[0])/D`。**推导：**共同的 V 消去，所以它是过去各次更新中 `Q[a]-Q[0]` 的 t*w 加权平均。Q 来自当时的机会样本、当时对手当前策略及探索，而非固定最终平均策略下的一次新估值。因此两套历史EV接近只是描述性证据；“EV MAE=0.0258BB”不能转写成“使用本策略最多损失0.0258BB”。平均策略里有较多某动作而历史估计另一动作较好，也不自动构成展示错误。

**观察与有限排除。** 在已检查的默认 `mn→mf→mE/mA` 路径没有发现周期性乘折扣、CFR+负遗憾清零或每次新增job自动清空平均策略。看到的是 t 递增加权与显式 Reset。对主JAR的相关调用索引检索也只找到显式重置、旧存档格式转换等缩放调用；这个静态负结果不覆盖未知插件或反射路径。

原版初始10m的 A6s 平均权重总量只占最终60m的 **2.8763%**；选定边缘牌为约2.79%–2.88%，而不是样本占比1/6。它与后期更新权重较大的代码一致。该数字只能描述平均权重占比；初始阶段留下的 R 会影响后续学习路径，不能说早期轨迹已被完全遗忘。

## 3. 10m＋50m重启worker的实际影响

**观察。** 初始10m入口是 `jN.run(IProgressMonitor):IStatus`。ASM索引的 field-access ordinal39 读取 `lV.a:Lnet/holdemresources/internal/lY;`，所以初始就是v4；call ordinal50进入固定样本 `bM.a(WeakReference,lZ,long,long,IProgressMonitor)`。见 [索引记录](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/bytecode-index.jsonl:10205)、[初始样本数](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0110/jN.java:82)。不能因混淆后字段都叫 `a` 而误判初始使用v3。

追加50m的 [截图46](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/screens/46-eight15bb-add50m.png) 已独立查看：HRC4.0 Default、Full Tree、50m；Reset Regret与Reset Strategies均未勾选。[动作日志175行](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/actions.jsonl:175)之后直接点击OK。初始存档保存后继续原会话，未reload。两份存档settings和gametree字节相同。

**静态事实。** 每次 `bM` 采样调用重新创建 `mn`，而 `qb` 持有原树对象。新的 `mn` 创建新的运行计数、根收益累加器、CI快照管理和ForkJoinPool；每个worker重新调用 `lu.a()`获得RNG。默认根的 `mE/mA` 数据继续保留。只有非空 reset Consumer 才遍历树清理数据；本次未选择它。[bM.java:249](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0393/bM.java:249)、[mn.java:34](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0034/mn.java:34)、[mn.java:73](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0034/mn.java:73)、[ew.java:40](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0521/ew.java:40)、[bN.java:22](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0390/bN.java:22)。

**候选解释。** worker重启会更换随机流与并发交错，并重建CI/缓存刷新时刻，从而改变有限样本轨迹。它不会因job计数归零而把节点t从1重新开始，也没有证据表明它改变了本次目标博弈。当前无对应消融，不能认定其解释了A6s差异。

另一个口径差异是原 `bM` 完成追加job后用该新 `mn.a():double[]` 更新 `eqpost`，因此该在线根收益均值来自本次job；native `root_sum` 续跑时保留全程。该均值与BTN逐桶 `(R[a]-R[0])/D` 是不同指标，不能互相替代。[bM.java:329](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0393/bM.java:329)、[mn.java:211](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0034/mn.java:211)、[native保存/恢复](D:/Users/Shao/Documents/ChatGPT/REA/native/hrc_research_solver.cpp:150)。

## 4. 随机流、线程、探索与条件发牌

**随机和调度不逐位对齐。** 原 `lu` 默认 `RandomSource.XO_SHI_RO_256_SS.create()` 没有传入固定seed；worker各自持有随机源。native用固定整数seed经SplitMix初始化xoshiro，并使用自己实现的有界整数拒绝法。即使核心生成器同属xoshiro256**，初始状态、整数/双精度调用、发牌拒绝与线程消费顺序均不同。[lu.java:8](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0706/lu.java:8)、[native RNG](D:/Users/Shao/Documents/ChatGPT/REA/native/hrc_research_solver.cpp:23)。

原存储用LongAdder、atomic add和weakCompareAndSet；native本轮单线程。原 `mq` 构造/更新快照调用 `mx.c()`刷新mE缓存；原保存也刷新，native save则原样保存cachedCounter与独立updates。缓存差别会影响epsilon和t。以上都是**已确认的执行轨迹差异**；没有测得它们各自产生多少频率差、是否构成持续偏差。[mE.java:65](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0021/mE.java:65)、[mq.java:12](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0030/mq.java:12)。

**探索公式没有发现差异。** 双方 `epsilon=1/sqrt(cachedCounter+10000)`，探索时可抽到当前策略为0的动作；v4目标节点跳过与special CHECK分支也相同。既有200组嵌套案例、3200逐步快照、136960数值完全一致，包含缓存滞后、marker、depth及额外1%分支。[已有审计](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-NATIVE-TRAVERSAL-AUDIT.md)。这只能排除那些输入和分支上的差异，不证明完整八人集成没有bug，也不证明HRC特定估计器有某个误差界。

**当前未看到忽略bunching。** native每次先给8人发完整无冲突底牌与5张公共牌，弃牌者的牌仍留在used mask，未放回牌堆。原full-tree mode0先抽所有玩家不冲突的组合，再相对总mask发公共牌。两种抽法消费随机流不同，但在全范围均匀输入下都给无放回联合发牌分布。[native deal](D:/Users/Shao/Documents/ChatGPT/REA/native/hrc_research_solver.cpp:105)、[原worker mode0](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0034/mn.java:103)、[原组合/公共牌抽样](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0706/lu.java:27)。

**条件分布推导。** 到达此BTN首次决策需要前五家被抽到fold；对给定完整底牌与此前历史，每家实际抽样fold概率是 `(1-epsilon)*p_fold+epsilon/K`。条件在“到达BTN”之后，底牌与剩余牌堆不再是孤立三人全范围分布。不同上游策略会改变该条件分布，即使BTN拿到同一A6s，对手牌分布也可能不同。逐手牌EV差因此不必只来自BTN自身；冻结局部策略评估时必须固定/说明前五家的到达条件，不能删除五个弃牌人的牌后直接给三人均匀发牌。

## 5. 已缩小的疑点与仍未知的部分

**本次已排除或有明确反证的解释：**

- “前10m是v3，后50m才v4”：初始入口descriptor和追加对话框均支持v4。
- “追加50m误勾了Reset”：截图与动作日志支持两个Reset未勾选。
- “初始保存float32后重载导致继续训练偏差”：本次仅保存，没有reload；live数组仍为double。
- “当前保存格式/策略锁不一致”：两存档都是973个格式23、1228个格式25、2585个叶格式1024；locked_action_total均为0。
- “图表只是错位/错列”：已有矩阵核对覆盖1014个行动值；最大浮点差1.11e−16。它验证显示一致性，不验证数值策略正确。
- “float32参考值舍入造成82个百分点”：按每个保存值的相邻float32中点区间保守反推，整个BTN169类的频率舍入误差上界仅 **2.195×10⁻⁶个百分点**；相对EV上界 **4.794×10⁻⁷BB**。这是存档量化误差界，不是训练误差界。计算输入与方法保存在本审计JSON。

**仍未知，不能用“没找到bug”填补：**

- 没有在统一、冻结的完整对手策略及相同上游条件下，对双方每手牌各行动进行独立交叉EV评估。
- 没有最终逐手牌独立误差条；访问次数不等于有效独立样本数。
- 不掌握HRC每个worker实际种子、交错顺序、全程CI刷新日志或原始每手更新次数。
- 尚无完整八人原字节码与native在同副牌、同随机调用流下的全树集成逐步轨迹对照；既有组件与合成探针不能代替它。
- 没有本场景全树best-response/exploitability证书；CI只比较近期策略变化，不能充当准确性证明。[mq公式](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0030/mq.java:49)。
- 同一内核不同seed若出现相当幅度的差异，会支持有限样本/学习轨迹敏感性的解释，但共同实现错误仍可能同时存在。

现有证据支持继续把“逐手牌策略距离”“历史行动差估计”“不同seed稳定性”“冻结策略下的实际价值损失”分别报告。整体范围接近只说明一个低维摘要接近；没有必要为了贴合单个HRC存档而手调A6s等频率。
