# FGS：真实未来手递归、独立实现与原始字节码验证

2026-11-05。本地对象为 HRC `4.1.0.202603231401`。主 JAR SHA-256：`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。本报告针对已安装版本的 FGS 数值子模型；并不证明完整产品、所有设置或其策略求解已等价。

**结果：**已实现独立 Python 参考与 C++ FGS。31 组原字节码/Python/C++ 场景、2,399 个根终局全部通过数值与状态检查；额外九人 depth=1 场景对照原字节码/C++，414 个递归状态、82,800 次阈值迭代、1,209 个根终局通过。两批合计 32 个场景、3,608 个根终局。Python 的大九人递归未重复执行。完整机会表也按全部 double 字节进行一致性校验，不只是抽样。

实现：[Python](../preflop_lab/hrc_fgs.py)、[C++](../native/hrc_fgs.hpp)、[产品配置适配](../preflop_lab/hrc_fgs_config.py)。证据：[31 场景报告](../reports/hrc-original-fgs-validation.json)、[九人递归报告](../reports/hrc-original-fgs-nine-validation.json)。本阶段 FGS API 已固定，产品主求解器接线由另一独立任务负责。

## 1. 模型范围与已确认的调用链

下表路径均在 `analysis/hrc-deep/sources/`，类位于 `net/holdemresources/internal/`。方法描述符以原 ASM 索引为准；表中 `N/` 代表该包路径。反编译器对混淆后同名字段及协变返回值会显示错误类型，不以伪 Java 能否编译为依据。

| 原方法及源码锚点 | 已确认行为 |
|---|---|
| `kP.a()LN/kK;`，`0903/kP.java:21` | FGS 叶值为 `kE(kW)` 的本桌 ICM，或 `ll` 的 KO/PKO 包装；该路径不使用外桌 MTT 估值器。 |
| `kP.a(ILN/lb;LN/lE;)Z`；构造器 `0903/kP.java:14`，原字节码索引同名 descriptor | 递归谓词为 `!tiedAward && (context.depth < depth3way || participants < 3)`，再由 kX 检查最大深度。`depth3way` 默认 1。 |
| `kX.<init>(ForkJoinPool,kC,kK,BiPredicate,int,int,rK,rL)`；`0919/kX.java:24` | 每个深度最多缓存 5,000 个上下文。深度 0、1 各执行 200 次阈值迭代，其后深度执行 50 次。真实字段/参数是 rK/rL，反编译文本误标为 rI/rJ。 |
| `kX.a(LN/kG;LN/ld;)[D`；`0919/kX.java:41` | 当前上下文人数大于 1 且深度未超限时建立 qI：边界深度使用普通权益，较浅层使用 kY/kZ/la 的递归终局效用，然后迭代并求每个座位的根权益。 |
| `kX.a(LN/kG;LN/lE;LN/ld;)[D`；`0919/kX.java:117` | 若允许递归，计算本手立即奖金/赏金，生成下一手上下文，递归结果按座位映射加回；否则返回普通终局权益。 |
| `qI.a()V`；`1001/qI.java:135` | 有限轮、平滑同时最佳响应；并非当前全行动树 MCCFR 内核。 |
| `qG.a(II)D` 及递归重载；`0957/qG.java` | 下一手只包含弃牌、推注、跟注、第二位跟注；达到三位参与者即结算，不继续接受第四人。 |
| `lc.a(LN/lE;)LN/kH;`；`0915/lc.java` 与 `lD.<init>([JZZ)V`，`0696/lD.java` | 淘汰座位、旋转盲位、传递未来盲注级别，返回旧座位到新座位映射；深度加一。 |
| `lC.a(LN/kG;)LN/lC;`，`0692/lC.java` | 实际扣除 regular ante / BB ante、SB、BB 与 straddle；短码按先后顺序扣至零。 |
| `lH.a(LN/lK;[ILjava/util/List;Z)LN/lF;`，`0699/lH.java:95` | 精确整数筹码、边池、奇数筹码和赏金归属；创建真实终局与平分标记。 |
| `lF.a()I`、`lF.a()Z`；`0702/lF.java:38` | 分别为未弃牌参与者数量、实际获奖组是否出现多位赢家；不是最初发牌人数，也不是任意两人牌力相同。 |

这些事实同时由静态证据和原始方法的受限数值执行支持。原版线程池并行枚举效用，独立实现串行计算并复用缓存；此处复现的是递归数值与模型规则，不是线程调度。

## 2. 下一手策略与机会分布

未来每手的范围不是任意 169 个独立频率，而是安装包 `necombined.range` 中固定排序的**包含端点前缀**。每个行动只储存一个整数阈值。初始 push=50、call=20、overcall=5，最后 BB 的初始 push=168。阈值 0 已包含第一手牌；push 搜索下限为 1，因此不是空范围。短盲全下或对手筹码已被盲注覆盖时，qI 会固定相关跟注/过跟分支。

机会表分别包含选定排序前缀的单人质量 `M1(a)`、两人联合质量 `M2(a,b)` 和三人联合质量 `M3(a,b,c)`。按已活动参与者前缀计算行动概率：第一人 `M1`，第二人 `M2/M1`，第三人 `M3/M2`；摊牌条件权益为各结果权重乘终局权益之和除以对应联合质量。没人推注则 BB 收走本手底池。两人结果 3 种，三人结果 13 种，包含各类平局。

这条未来手链只依赖所列活动参与者的二/三人联合机会表，未逐一追踪先前弃牌者的私牌条件。因此不能把该 FGS 阈值模型描述为完整下一手行动树、任意范围求解或全量弃牌条件下的 card-bunching 模型。

平滑最佳响应按原始浮点精度执行。令迭代序号 t 从 0 开始、累计质量 s 初始为 float32(1)，则：

```
s = float32(s + float32(0.11) * log(t + 10))
w = float32(1 / s)
smoothed = float32(float32(best * w) + float32(old * (1 - w)))
threshold = JavaRound(smoothed)
```

每轮先计算各座位所有 best response，再同时发布平滑阈值。搜索半径为 `max(169 // (t+1), minimum)`，push/call/overcall 的 minimum 分别为 14/8/3。push/call 的搜索窗口随着更好的候选移动；overcall 使用原阈值的固定窗口；上界不包含 169，下界可包含 0。最佳值初始化为最小正 float，比较为严格 `>`。原顺序、float32 舍入与此搜索窗口均影响结果，不能替换成普通全域 argmax 而声称相同。

## 3. 筹码、盲位、淘汰与下一手收益

单个未来终局先独立结算当手整数筹码和 KO/PKO，然后决定是否递归。递归值为：立即名次奖金 + 立即赏金现金 + 幸存者下一手权益；已淘汰座位没有下一手项。PKO 未立即支付的赏金按当手赢家归属转入新的头部金额，不能把本手普通终局的未来赏金估值再重复相加。

普通 ante 由每人先付；BB ante 支持 ante-first 和 blind-first 两种优先级。BB ante 是全局池，所有 live 玩家均可争夺，包括投入普通筹码为零的短全下玩家。普通 ante 仍属于各自投入。

本桌通常采用死按钮规则：删除零筹码后左移一个幸存座位；旧 BB 淘汰且下一手仍超过两人时跳过 SB。moving-button 且原人数大于二时，删除零筹码后按 `1 + 旧 SB/BB 淘汰人数` 左移；进入 HU 再额外左移一次，不产生 skipSB。HU 按普通一位轮换处理。下一盲注级别由递增后的深度是否达到配置 at-depth 决定。

结算的奇数筹码并非浮点平均分。每个实际同牌力获奖组分配整数商，并把**全部余数**加给原排序第一位赢家：贡献上限较低者优先，相同上限时座位序号较大者优先。相邻边池若属于同一获奖组，应合并后再分配。最低正贡献层无法表示 BB ante 的零贡献赢家，需要独立全局池。

qT 会预计算一些实际行动概率为零的参与者组合。对此，原模型会把高于最终被覆盖上限的剩余贡献返还给对应座位，包括某些不可能组合中的已弃牌者；验证工具也对这些完整组合核对，不能只检验概率非零路径后遗漏定义差异。

`tied_award` 只在实际分池获奖组人数大于 1 时为真。三人中两位输家牌力相同但第三人独赢，仍可继续递归。主树接入必须提供真实未弃牌人数与这个分池标志，不能用 winner_masks 是否非空推测。

## 4. 资源格式、溯源与隔离执行

生产代码不调用原版类，也不读取存档策略或原版叶值。机会分布作为用户已有安装包的研究输入，独立累加生成本地缓存，不包含在可分发源代码中。

| 安装资源 | 字节数 | SHA-256 |
|---|---:|---|
| calculator JAR 的 `net/holdemresources/sngnash/data/handranking/necombined.range` | 662 | `871775a8393968ac6be770835c1cce744aae91723c3181e1c7fdf5d53ceb52cc` |
| preflopdata.holdem JAR 的 `net/holdemresources/handevaluation/preflop/hands/data/2wh.dat` | 344,760 | `f329b9633decff877074b6dc5ff924c437e4a632cf168b35d789441fe65fc151` |
| 同路径 `3wh.dat` | 85,155,720 | `949cf28d7c78ad63063c33f372b8af121bd316d55e41662ebeaca02ddee2915d` |

容器为 `net.holdemresources.calculator_4.1.0.202603231401.jar` 与 `net.holdemresources.preflopdata.holdem_1.4.1.jar`；后者 SHA-256 `721c77d43459c6573b0b4aeb50f259f03d964991a73b80ebeb7a68777111ffa2`。资源与容器完整 hash 都保存在数值报告中。

缓存顺序为 magic `FGSCHN01`，接着 little-endian double 的 169 个 marginal、57,460 个二人累加值、11,463,270 个三人累加值，总长 92,167,200 字节，SHA-256 为 `3bc0f9f3304599ce02ebd315137f644b2ec2f12a7768fa476baa2c4e37c793e0`。每一组前缀行分别为 3/13 个摊牌结果加一个总质量。原三人 NaN 原子质量当作零。marginal 每个组合数先以 float32 除以 1326 再转 double 累加，最终总和可能略大于 1；保持此舍入是数值复现所需。

独立生成与原始 rK/rL 的完整字节对照如下：

| 数组 | 全部 double 数量 | 一致的 SHA-256 |
|---|---:|---|
| marginal | 169 | `8f635c1b4aa39eb158e12fd2d7d12fca055e0d239ed050c56a398719b4d05da2` |
| two | 57,460 | `6eb78fb8d31c04a128ea9bb5eef06450360ba3227f327f338f1ae47710d4cd71` |
| three | 11,463,270 | `e12a372915dc3eafb17238147a09dd197c8764bfcbbf28a2b5edb9398365b08a` |

验证 oracle 的 [OriginalFgsProbe.java](../scripts/java/OriginalFgsProbe.java) 采用 platform classloader 父加载器，只允许列明的主 JAR 数学类、已钉住 hash 的 preflopdata/Guava/failureaccess 依赖。只开放上述三个数据资源，拒绝工作目录同路径资源遮蔽，记录实际载入的 122 个类及其 hash。主应用、GUI、网络、授权门控和原版求解任务未启动。Guava 用于原缓存而不是独立生产代码；独立代码采用自身 LRU。

## 5. 稳定接口与运行预算

原始接口返回绝对奖金权益。主求解器需要用终局权益减去相同模型的基线，不应把 ICM baseline 与 FGS terminal 混用。

```python
from preflop_lab.hrc_fgs import Calculator, ChanceTables, Config, Context, Outcome
tables = ChanceTables.from_installation("D:/Program Files/HRC/plugins")
calc = Calculator(Config((100, 50), 100, 50, depth=1), tables)
context = Context((1000, 1000), depth=0, skip_sb=False)
baseline = calc.equities(context)
terminal = calc.terminal(context, Outcome((1200, 800), (0, 0), 2, False))
```

```cpp
auto tables = hrc_fgs::ChanceTables::read(cachePath);
hrc_fgs::Config config;
config.equity = existingIcmEquityConfig; // 可含 KO/PKO，无外桌 MTT
hrc_fgs::Calculator calc(config, tables);
auto baseline = calc.equities(context);
auto terminal = calc.terminal(context, outcome);
```

Context 含正整数筹码、当前幸存者赏金、深度、skipSB；Outcome 含完整本桌结算筹码、赏金赢家 mask、未弃牌人数与实际分池平局标志。金额是统一整数筹码或奖金货币，不混用 BB。`equities(depth=0)` 对当前下一手进行阈值求解，随后继续至配置深度；`terminal(depth=0)` 从已完成本手结果决定是否进入下一手。因此最大 depth=0 的 terminal 不递归，但直接 `equities` 仍会求当前手阈值，遵循原始 kX 接口。

C++ Calculator 每个 worker 单独使用，含可变缓存和预算，不支持并发共享；ChanceTables 为不可变共享数据。上下文缓存按深度分开，终局缓存键包括上下文筹码、赏金、深度、skipSB，以及结果筹码、winner_masks、participants、tied_award。终局默认最多 65,536 项；上下文每深度默认 5,000 项。

默认预算是 20,000 个新状态、2,000,000 次阈值迭代、60 秒**实际未缓存 FGS 工作时间**，不是构造后经过的墙钟时间。外部训练耗时和空闲等待不消耗此时间。缓存命中不再触发预算检查；已完成结果在预算耗尽后仍可复用。`reset_budget()` 只重置计数与工作时间，保留完成缓存。失败调用不会缓存不完整结果；超过预算抛 `ResourceLimit` / `FgsResourceLimit`，不得把较浅或未完成收益当成完整终局。主训练 checkpoint 也必须只标记已完成的迭代。

接入阶段新增可选 C++ `Config.cancel_check` 回调；每次递归/迭代检查点先检查取消并抛独立 `hrc_fgs::Cancelled`。该扩展不改变数值更新、缓存键或默认行为；允许单次很长的 FGS 计算响应外部取消。已完成缓存读取仍立即返回。

产品适配为 `validated_fgs(raw_fgs,equity,players)`、`fgs_spec(raw_fgs,equity,tree,chip_scale=...)` 和 `prepare_chances(plugins,cache_dir)`。disabled spec 返回 None。自定义场景使用 `chip_scale=10000`；固定 BB 场景默认使用 tree.rules.big_blind。未来盲注金额与所处场景的用户筹码单位一致，必须精确转成整数。规则从实际 tree.settings.handdata 读取。缓存 helper 钉住完整缓存 hash，缺失时独立构建、原子写入；损坏时显式拒绝。

## 6. 验证覆盖、耗时与已知差异

31 组包含 HU 深度 0/1/2/3、三人深度 0/1/2、三人 cutoff=0、短 SB/BB、四人普通 ante、两类 BB ante、moving-button、skipSB、单/双/button straddle、未来盲注级别、固定 KO、PKO alpha=0/0.5/1、PKO 短 BB ante、全奖相同、零奖金，以及六/九人 depth=0。

31 场景最大根权益差异 Python 和 C++ 均为 `2.842170943040401e-14`；终局权益/递延赏金最大差异 `5.684341886080802e-14`。所有最终筹码、winner masks、实际平分标志、下一手筹码、座位映射和 skipSB 均精确一致。普通 Python 测试 22 项通过；产品适配测试另有 22 项通过。

九人 depth=1 的筹码 `[400,600,800,1000,900,700,500,1100,1200]`，奖金 `[100,60,20]`，盲注 `[100,50,0]`。原值与独立值的根最大差异 `3.552713678800501e-15`，1,209 根终局的最大差异 `2.1316282072803006e-14`，全部离散字段精确一致。正式记录原版 8.66 秒、独立 C++ 15.20 秒（414 状态、82,800 轮）；这些是本机单个固定输入的观测，不是所有深度的耗时承诺。31 个较小场景的 Python 根计算累计约 96.4 秒，C++ 约 0.44 秒，未包含全部诊断枚举/编译/资源构建。

独立控制测试还确认：在 50ms 工作预算下空闲等待 75ms 不会错误耗尽计算预算；完成缓存可继续使用；真正耗尽状态预算时抛错且不返回部分结果。

**已知非逐位一致处：**所有名次奖金均相同时，独立 ICM 与原 ICM 的运算顺序引入约 `1e-14` 的差异。qI 使用严格 `>`，会把数学上无差异的行动选成不同阈值。`three_equal_prizes` 在第 1/2/10/50/200 轮均记录到阈值差异，例如最终一处 push 119 对 138。权益差异不超过 `2.842170943040401e-14`，但不能声称内部策略位完全相同。其余被直接追踪的 2–4 人场景阈值一致。报告完整保留 `threshold_index_differences`，未把它隐藏成“所有内部状态相等”。

## 7. 复现与剩余边界

从工作区运行：

```powershell
.venv/Scripts/python.exe scripts/validate-hrc-fgs.py
.venv/Scripts/python.exe scripts/validate-hrc-fgs-nine.py
.venv/Scripts/python.exe -m pytest tests/test_hrc_fgs.py tests/test_hrc_fgs_config.py -q
```

脚本固定本机 Java21、编译原始 oracle、独立构建机会缓存、编译 C++ 数值探针，并保存每个输入、原始输出、源文件/类/资源 SHA 与命令。C++ 使用 `-ffp-contract=off`；fast-math 不在验证范围。派生缓存与运行输出位于 analysis，不应分发原数据。

深度参数实现支持 0–10，但数值实测为 HU 至 3、三人至 2、九人至 1；更深/大桌的状态与运行时间增长很快，依赖明确预算。未证明该受限模型在数学上达到完整均衡，也未证明对所有筹码、奖金边界、不同版本资源或多线程调度都一致。未支持 FGS+MTT 混合、本模型以外的未来任意范围、未来四人以上对抗或未来完整翻后树。后者属于独立模型扩展，不能用这批数值证据替代。
