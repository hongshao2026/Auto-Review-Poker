# HRC 原始字节码数值验证

日期：2026-11-04。本报告记录对本机 HRC 原始 class 字节的隔离执行结果。它不同于重新编译反编译源码，也不同于运行我们之前的 Python 翻前原型。

目标主 JAR 的 SHA-256：`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。各探针在执行前检查此哈希；类和使用的数据资源另行记录哈希。原始安装目录未被修改。

## 隔离与证据范围

Java 21 的专用 ClassLoader 使用 platform parent，只允许加载预先审读的目标类。没有加载 Application、Activator、Eclipse 工作台或整个应用上下文。这里的“隔离”是依赖加载范围限制，不是操作系统沙箱；不得把它描述成完整沙箱安全证明。

反射同时匹配名称、参数类型和返回类型。混淆后的 HRC 包含相同名称和参数、但返回类型不同的方法，普通的 `getMethod(name, parameters)` 不足以准确选择它们。

审计以 `javap -c -p -s` 和 ASM 调用/字段索引为准。实际遇到了一个重要例子：Vineflower 输出的 `og.java` 没有显示初始化动作，但原始 `og.<clinit>()V` 存在 `getstatic lt.a:[J; pop; return`。初次严格白名单加载因此失败；审读 `lt` 的牌名、掩码和花色数组初始化后，将它加入白名单，测试才成功。该失败支持“不能仅依赖反编译文本审核初始化”的结论。

## 精确 ICM 内核

直接执行 `kW.<init>([D)V`、`kW.a([D)[[D` 和继承的 `kU.a([D)[D`，仅加载原始 `kV/kU/kW`。

- 41 个固定种子案例，覆盖 1–10 人、不同筹码、不同奖励名次、等额奖励、仅第一名有奖、筹码同比缩放。
- 独立 oracle 从“已有获胜者集合”向下一名逐步传播概率；六人及以下再用全部名次排列交叉核对，避免把同一段反编译循环重写一次作为唯一依据。
- 比较每个玩家的总权益、每个奖励名次的权益矩阵及奖池守恒。
- 全部通过，玩家权益最大绝对误差 `2.2737367544323206e-13`，验收阈值 `1e-9`。

证据：[完整输入、原版输出和误差报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-icm-validation.json)。可复跑入口：[validate-hrc-icm.py](D:/Users/Shao/Documents/ChatGPT/REA/scripts/validate-hrc-icm.py)，原版调用器：[OriginalIcmProbe.java](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalIcmProbe.java)。

边界：这是正筹码精确 ICM 内核。没有在本组测试中验证零筹码包装逻辑、淘汰与赏金、MTT 数值积分、FGS 或完整求解器。

## 牌力、花色同构和二进制读取

直接执行原始 `og/oD/lv/lt`；`lv` 只读取原 JAR 中的 `lookup7card.dat.gz`，没有改写或复制到原型产品。资源哈希记录在结果中。

| 验证对象 | 案例 | 比较方法 | 结果 |
|---|---:|---|---|
| `og` 公共牌/手牌掩码规范化和花色置换 | 2,528 | 独立提取四种花色的13位rank集合后排序；核对 permutation 应用与规范化相等 | 通过 |
| `lv.a(J)S` 七张牌强弱 | 2,318 | 枚举七张牌中的21组五张牌，以常规牌型/踢脚元组取最大值，核对原版结果的全局顺序和平局 | 通过 |
| `oD.a([BI)S/I/J` | 32 组，每组3种宽度 | Python signed little-endian 整数转换 | 通过 |

七张牌样本覆盖九种牌型、A2345、两组三条、固定牌型的全部24种花色置换及2,000组固定种子随机手牌。所观察的原版 short 牌力值随牌力增强而增大。比较证明的是这些样本的排序和平局一致，不是所有133,784,560组七张牌穷举，也不是将原版内部编码等同于某公开评估库的数值编码。

证据：[卡牌验证报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-cards-validation.json)。可复跑入口：[validate-hrc-cards.py](D:/Users/Shao/Documents/ChatGPT/REA/scripts/validate-hrc-cards.py)，原版调用器：[OriginalCardsProbe.java](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalCardsProbe.java)。逐案例原版输出保存在 `analysis/hrc-deep/probes/cards-original-output.jsonl`。

## 策略存储与概率提取

原始 `mE/mA/mt/mx/my/ma/mu/mv` 与安装的 `UniformRandomProvider` 接口通过允许名单加载。探针使用可审计的 RNG 输入（`nextInt()` 固定0），强制计数缓存刷新；没有把这个调度当作真实多线程运行。

30项对照全部通过：正遗憾归一化、全非正回退、check特殊分支、翻前两步遗憾与平均累积、相对EV读取、不同w/z的作用，以及翻后每桶当前策略与共享动作平均的区别。例如两次更新后，`mE` 原始数组确为 `[2,0.5,2.5,3,1.25,1.75]`；平均策略为 `[5/12,7/12]`。`mE` 的平均量不乘w、忽略z，而 `mA` 的共享平均受z控制。

证据：[30项完整输入输出](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-strategy-validation.json)，复跑 `python scripts/run-hrc-probe.py strategy`。数学解释见 [核心算法报告](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-SOLVER-CORE.md)。这些测试验证恢复出的更新公式，不构成整个算法的无偏性或均衡收敛证明。

## 下注状态与真实候选生成

原始 `lB/lC` 状态链与 `mF` 候选生成器共8项对照通过，包含盲注、短全下、minimum/maximum、回到原加注者时的行动重开、尺寸规范化及有效全下。探针给 `mI` 的替代实现只提供明确的输入尺寸和允许flat条件；合法候选仍由原始 `mF` 产生。

首次7项中有1项失败，原因是静态推断错误，并非修改了HRC来让测试通过：

- 筹码 `[2000,400,1000]` 时，`mF` 把请求9999截为有效加注1000；原玩家仍余1000，动作已经标记有效all-in。
- 直接把9999传给更底层的 `lB.a(J)`，其“请求≥自身总筹码”快捷分支产生2000，玩家余0。这个底层接口不能替代完整合法动作生成器。

修订测试既验证真实生成的1000，也单独保留直接调用得到2000的行为；不是把原失败悄悄改成成功。首次失败记录保存在 `analysis/hrc-deep/probes/tree-first-validation.json`。

证据：[8项完整状态与行动历史](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-tree-validation.json)，复跑 `python scripts/run-hrc-probe.py tree`。这里只验证当前配置的实际HRC行为，没有把它等同于所有赛事的下注规则。

## 边池与最小遍历链路

`OriginalSettlementProbe` 用原始lC构造合成终局，经lK扫街，调用原始lH直接排名结算重载；独立oracle按投入阈值分池。7项检查通过，覆盖多层边池、未跟注退款、弃牌贡献、两人/三人平局与BB ante。所有样本都守恒。在3个有余数的并列样本中，lF最终筹码与lG逐池明细确实把余数分给不同玩家；这是显式检验的数据差异，不能概括成“一切一致”。未验证rake或桌面显示。

[结算报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-settlement-validation.json)，复跑 `python scripts/run-hrc-probe.py settlement`。

`OriginalTraversalProbe` 连接原始lu发牌、lX/lY工厂、mf遍历、mh终端、lv牌评估、me胜负索引和mE策略存储。4副固定随机输入的向量遍历与脚本RNG控制的标量分支共52项通过。v3更新、v4跳过不更新、v4不跳过正常更新都得到原字节码观察。初始化时额外解析到lE纯接口，审读后加入白名单；没有放开全应用类路径。

叶子收益表是明确的合成输入，RNG也由探针控制。因此这证明一条原版核心小链路按恢复的逻辑运行，不是实际ICM/翻后建树/多线程训练的端到端对照。[遍历报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-traversal-validation.json)，复跑 `python scripts/run-hrc-probe.py traversal`。

## 已安装64桶翻牌抽象：完整输入域对照

选择 `Johanson13_2021-02.64.1`，其已安装Brotli资源解压后为4,127,760字节。完整SHA-256匹配资源名 `5c50391a2dffc81287be70955ad7a86f9f607745f6a1a8f96af159d51db2e22d`；1,755行，每行1,176个不冲突的两张手牌，以little-endian short编码，全部2,063,880个桶编号落在0–63。

在1,152组固定样本对照之外，再遍历**全部22,100种物理翻牌牌面和25,989,600组合法牌面/手牌组合**。独立oracle以每种花色的13位rank集合排序、重映射手牌、查原始资源行，与原始 `ol` 批量映射接口逐项比较，全部一致；冲突手牌的-1哨兵也一致。原始公共牌表顺序的整体哈希与独立枚举相符。原始 `oh` 对错误摘要返回null，对截断输入拒绝解析。

证据：[原版全域映射验证](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-abstraction-validation.json)，[探针](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalFlopBucketProbe.java)，[运行器](D:/Users/Shao/Documents/ChatGPT/REA/scripts/validate-hrc-abstraction.py)。使用未修改的HRC类及本机Brotli/Eclipse Collections依赖，没有调用应用入口或配置注册器。

这验证了**一个既有flop profile的读取与映射全域**；没有验证其他桶数、turn/river资源、抽象数据的训练生成过程或抽象近似误差。

## 结论边界

这些结果已把具体数值内核从“静态推测”推进到“原始字节码输入输出对照”。它们不能代替真实配置下的整树训练、抽象桶映射、线程调度、保存恢复以及逐节点策略对照；完整 HRC 数值等价尚未建立。
