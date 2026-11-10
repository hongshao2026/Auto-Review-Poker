# 独立终局权益：精确 ICM、KO 与 PKO

2026-11-05。本批交付是 [hrc_equity.hpp](D:/Users/Shao/Documents/ChatGPT/REA/native/hrc_equity.hpp) 中独立实现的终局数学层。它接收已经结算的整数筹码和每个被淘汰者的击杀者集合，不读取 HRC 保存策略，不调用原版求解器。原版纯数学方法仅在另行隔离的验证程序中作为对照。

## 接口与单位

`namespace hrc_equity` 定义 `Mode::{Chips=0,ICM=1,MTT=2}`、`BountyMode::{None=0,Fixed=1,Progressive=2}`。`EquityConfig` 指定本手开始时 2–10 个正整数筹码、非负递减奖金、完整悬赏额、立即支付比例及缓存容量。MTT 的外桌筹码与本桌筹码必须使用同一单位；奖金和赏金使用相同货币单位。

`Calculator(config, optional_mtt_callback)` 保存不可变配置；`baseline()` 返回手前绝对权益；`compute_terminal(Chips, WinnerMasks)` 返回 `EquityResult`。这两个类型分别是长度 10 的 `int64_t` 和 `uint16_t` 数组，未用席位必须为零。每个 `winnerMasks[v]` 的 set bit 对应淘汰 v 的幸存者；有赏金时每个出局者必须提供非空集合。终局筹码必须非负且至少一人存活。筹码守恒属于调用方的结算责任，本层不会自行调整筹码。

结果包括 `total`、`immediate_prizes`、`immediate_bounties`、`future_equities`、`remaining_bounties` 五个长度 10 的 double 数组。净收益应由调用方执行 `terminal.total − baseline.total`；ChipEV 的绝对值是 `final_stack × chip_unit`。ICM/赏金路径不将货币金额转换为 BB。

固定 KO 只支持原 `lj` 所使用的全场统一赏金，必须全部立即支付。PKO 支持不同悬赏额，`immediate_fraction` 在闭区间 `[0,1]`。`None` 模式拒绝提供悬赏向量，ChipEV 拒绝混入货币赏金。非有限值、负金额、错误数组长度、给幸存者标记击杀者、无效席位、非幸存击杀者均明确报错。

## 已恢复行为与原始方法

主 JAR SHA-256 为 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。描述符和字节码保存在 `analysis/hrc-deep/equity/{ordinal}_{class}/bytecode.txt`；完整先前分析见 [HRC-EQUITY-ABSTRACTION.md](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-EQUITY-ABSTRACTION.md)。

| 行为 | 实际原版方法与源码位置 |
|---|---|
| 正筹码精确 ICM | `kW.a([D)[[D`，`kU.a([D)[D`；[kW.java:9](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0896/kW.java:9) |
| 本手已确定的名次奖金 | `kC.a(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D`；[kC.java:18](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0933/kC.java:18) |
| 淘汰后幸存者 ICM 与索引映回 | `kE.a(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D`；[kE.java:24](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0935/kE.java:24) |
| 击杀赏金均分 | `kB.a(Lnet/holdemresources/internal/kI;Lnet/holdemresources/internal/lE;D)[D` 与 `a(Lnet/holdemresources/internal/kI;Lnet/holdemresources/internal/lE;[DD)[D`；[kB.java:4](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0934/kB.java:4) |
| PKO 立即支付及悬赏滚入 | `lk.a(Lnet/holdemresources/internal/lE;)[D` 与 `a(Lnet/holdemresources/internal/lE;)Lnet/holdemresources/internal/kH;`；[lk.java:17](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0910/lk.java:17) |
| 固定 KO 幸存悬赏池 | `lj.a()D`；[lj.java:28](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0909/lj.java:28) |
| 未来悬赏池按筹码占比分配 | `ll.b(Lnet/holdemresources/internal/kG;)[D`；[ll.java:21](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0911/ll.java:21) |

同手出局者按**本手开始筹码**降序获得剩余名次，起始筹码相同者平均相关奖级，未获奖名次按零计入分母。存活者对奖金表前端执行精确 ICM。实现采用独立的前向子集概率传播，原 `kW` 使用反向子集递推；本实现以 long double 累计后输出 double，因此不承诺浮点逐位相等。

若 v 被集合 K 淘汰，PKO 即时支付给每个 i∈K `alpha × bounty[v] / |K|`，同时将 `(1−alpha) × bounty[v] / |K|` 滚入该幸存者的悬赏。固定 KO 只进行即时支付。未来权益包含幸存者普通 ICM 和 `剩余悬赏池 × 幸存者筹码/总筹码`。冠军最终取得剩余池，包含自己头上的悬赏。这个未来悬赏公式是原版模型的复原，不代表对未来所有击杀过程进行精确博弈求解。

击杀集合必须由底池结算提供；边池输家不能一律被全局最强手牌淘汰。原 `lH` 在覆盖被淘汰者全部投入的获胜层记录 `lE.a(I)[I`。本层拒绝推测缺失集合。

## 缓存和 MTT 扩展

每个 `Calculator` 有独立的固定容量 direct-mapped 缓存，key 包括完整终局整数筹码及所有击杀集合。默认 65,536 槽，容量上限 1,048,576，设为零可关闭；碰撞会替换槽内结果，不无界增长。`cache_stats()` 返回命中、未命中、碰撞和占用数。返回的结果引用只保证在同一实例下一次评估或清空之前有效；每个训练线程应使用独立实例。

MTT 要求显式传入 `MttEvaluator(survivor_stacks,payouts,other_stacks)`，缺少回调直接报错。其职责只返回普通奖金权益。wrapper 按外桌人数偏移本手淘汰奖级，并将剩余本桌赏金与外桌赏金总和按全场筹码占比分配。外桌赏金数组的分布本身不被此模型使用，求和等价于原 `otheravgbounty × 外桌人数`。本报告验证的是本桌 ICM/KO/PKO；MTT 内核由单独的 `hrc_mtt.hpp` 对照报告覆盖。测试 probe 中的 MTT 回调明确标记为“总人数 ≤10 的全场精确 ICM 测试回调”，不冒充原版 MTT 大场积分路径。

## 验证结果

运行 `.venv/Scripts/python.exe scripts/validate-hrc-bounty.py` 可复现 [hrc-original-bounty-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-bounty-validation.json)。共 143 组 2–10 人案例全部通过，逐项比较手前权益、终局总权益、即时名次奖金、即时击杀赏金、更新后悬赏及未来权益；最大绝对误差 `1.1368683772161603e−13`，最大总奖金守恒误差相同。覆盖同手多人出局、同起始筹码平分、多个击杀者平分、不同边池击杀者、零至全额立即支付，以及最后幸存者。≤7 名幸存者另以全部完赛排列枚举交叉验证。

原始探针是 [OriginalBountyProbe.java](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalBountyProbe.java)。它固定原 JAR SHA，使用 platform-parent 且只允许已审数学依赖的 ClassLoader，以确切 JVM descriptor 调用原 class。实际加载的 22 个类哈希保存在报告。原 `lc/lD/kH` 的幸存席位旋转和映射也被执行并映回原席位；`ky` 的初始化仅涉及 `kz/kA` 枚举。没有调用 HRC 应用、许可、求解循环或原底池结算，输入末态和击杀集合是明确给定的合成数据。

`.venv/Scripts/python.exe -m pytest tests/test_hrc_equity.py -q`：**43 通过**。另复用了先前 41 组原 `kW` 精确 ICM 输出，增加全部 24 个四席排列、缓存碰撞、同筹码不同击杀者、非法参数和极端有限筹码比例测试。

[equity-performance.json](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-native/equity-performance.json) 是单一固定终局重复评估的本机微基准：10 人完整奖金表不缓存约 18,637 次/秒；缓存命中约 1,878 万次/秒。2 人和 6 人缓存命中分别约 2,640 万和 2,176 万次/秒。数据包含终局输入检查与 cache key 比较，但不包含发牌、牌力、遍历、陌生终局的 cache miss 分布，因此不能当作完整训练吞吐。缓存实际命中率须由集成后的真实树单独报告。

本批不包括通用树生成、未来局面 FGS、真实赏金 GUI 场景训练对照，也不证明整个产品功能等价。
