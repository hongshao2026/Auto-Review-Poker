# 格式 27/31 与策略模式迁移：独立数值证据

2026-11-05，目标为已安装主 JAR `4.1.0.202603231401`（SHA-256 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`）。本批检查纯数值存储、缓存同步和转换，不执行 GUI，不把存档策略用作训练初值。

**已完成：**格式 27/31 的 30 个合成场景、363 个逐步快照，与独立 Python 参考全部一致；每步原始 double payload 的 SHA-256 与每次保存的 float32 字节 SHA-256 也相同。另有 12 个频率控制启用/禁用场景，全部数值零差异。数值域为有限输入、单线程、成功 CAS；并发竞争与弱 CAS 偶发失败不属于此证据。

随后通过只读 include 生产 `native/hrc_research_solver.cpp` 的独立 harness，直接调用真实 `Node.update/reset/flush`，201 个原始快照分步对照全部通过：完整 raw SHA、真实计数与共享累加器一致，最大绝对误差为 0。未用 harness 自行实现缺失的通用折扣或持久化 API。证据为 [生产 Node 对照](../reports/hrc-original-extended-store-native-validation.json)，复现脚本为 [validate-hrc-extended-store-native.py](../scripts/validate-hrc-extended-store-native.py)。

- 原始与独立对照：[extended-store 报告](../reports/hrc-original-extended-store-validation.json)、[模式迁移报告](../reports/hrc-original-store-migration-validation.json)。
- 独立参考：[hrc_extended_store.py](../preflop_lab/hrc_extended_store.py)。主 native Node 由另一任务接入，上述另行执行的生产 Node 对照验证了这三个调用。
- 可复现入口：[validate-hrc-extended-store.py](../scripts/validate-hrc-extended-store.py)、[validate-hrc-store-migration.py](../scripts/validate-hrc-store-migration.py)。完整输入、原始逐步输出在 `analysis/hrc-deep/extended-store/`、`store-migration/`；报告包含输入定义、源与证据 hash。

## 1. 存储与访问

设桶数 h、行动数 k。格式 27（`mB`）的 double 布局是 `[cachedCount, sharedAverage[k], h × (regret[k], bucketAverage[k])]`。格式 31（`mD extends mw`）的逻辑布局是 `[cachedCount, sharedAverage[k], h × (regret[k], denominator, bucketAverage[k])]`。格式 31 内部分块：第 0 块为 k+1 header；其余块最多 `16384 - 16384 % (2k+1)` 个 double，只在完整行之间切分。原 `mw.a:[[D`、`mw.a:I`（行动数）、`mw.b:I`（桶数）、`mw.c:I`（每块行数）、`mw.d:I`（行宽）已按 ASM descriptor 区分，不能按混淆字段名猜类型。

证据锚点：`sources/0024/mB.java:13`、`:31`；`0023/mD.java:9`；`0018/mw.java:15`、`:39`、`:43`。格式 27 `c()I=27` 无 EV denominator，`b(I)[D` 返回 null；格式 31 同方法返回 `(R[a]-R[0])/D`，D<=0 时为 NaN。显示范围使用正数归一化的 bucketAverage；训练范围用正 regret 归一化及原 CHECK 特殊分支。sharedAverage 的显示不是每桶策略。

## 2. 更新与缓存

`mB.a(ma,[D,int,int,double,double)V`、`mD.a(...)V`（descriptor `(Lnet/holdemresources/internal/ma;[DIIDD)V`）先检查 regretWeight>0；否则整个更新，包括平均策略都跳过。令 `E=sum(p[a]*q[a], p[a]>0)`，true LongAdder 计数加一，临时 n 初始为 `cachedCount+1`；若 `rng.nextInt() % floor(sqrt(n)) == 0`，刷新 cachedCount 并用 trueCount 作为 n。

随后两格式都执行：`R[a] += regretWeight*n*(q[a]-E)`，`bucketAverage[a] += n*p[a]`；格式 31 再加 `D += regretWeight*n`。仅 marker>0 时，加 `sharedAverage[a] += marker*n*p[a]`。格式 27 直接加 header；格式 31 加 DoubleAdder，header 仍可陈旧。**bucketAverage 不乘 regretWeight，也不乘 marker。**

格式 27/31 都有 LongAdder 与 cachedCount 两个不同状态；不能简单每步让 header 自动等于 trueCount。格式 31 `c()V` 刷新 cachedCount 与 sharedAverage header；`b()[D` 显示共享策略前也会刷新。25 格式的原更新则每次直接增加 header count。

## 3. 重置、折扣和保存

格式 27 的 `b(D)V` 缩放 sharedAverage 与 bucketAverage；`mt.a(D)V` 缩放 regret。格式 31 的 `mD.a(D)V` 名字虽然相同，却缩放 sharedAverage header 与 bucketAverage，然后 `b()V` 从 header **重建 LongAdder 和 shared DoubleAdder**。它不会先 flush，故已累积但未写回的 shared sums 以及 true count 可能被陈旧 header 覆盖。这一现象已由原始方法逐步探针确认，不是建议这样设计新的算法。

`a(ZZ)V` 的两个参数依次为 resetRegret/resetStrategy。策略重置先以 `1e-20` 缩放平均；regret 重置以 `1e-20` 缩放 R（格式 31 同时缩放 D），再将 count 置零。31 的 count setter 同样从 cached shared header 重建 adders。原 caller 若先 flush，效果与未 flush 时不同，应保持调用顺序。

`mt.a()[B`、`mw.a()[B` 在保存前 flush，将全部 double 转 IEEE754 float32 little-endian；恢复 `a([B)V` 按 float32 读回 double，再从 header 重建 adders。mw 的物理分块在保存时被顺序拉平。验证覆盖 k=2/3/4/8、正/零/负 weight、marker=0、刷新与不刷新随机条件、非整数 cached count、三种 reset 组合、往返保存，以及 16,384 double 边界前后行。

## 4. 25 转 27

纯原始 `mB.a(Lnet/holdemresources/internal/mA;)Lnet/holdemresources/internal/mB;` 把 count 与 sharedAverage 原值复制，保留每桶原始 regret，并将**当时的普通 regret-matching 策略**作为新 bucketAverage 初值。不把全局 sharedAverage 平铺成各桶策略，也不乘原采样次数。全负/全零 regret 转为均匀分布。

实际菜单调用证据为 `sources/0544/eF.java:23` 的后台任务；它筛选格式 25 并调用这个方法，再提醒继续采样及初始重置策略。此处 UI 未执行，纯转换已在三种行动数、正负/零 regret 的原字节码场景中执行并验证。

## 5. 频率控制启用、修改和禁用

纯 `mz.a(mx,double[],double[])` 启用时，只有旧格式 23 会复制旧 float32 R/D/A 数据并 reset(true,true)，所以这些行成为旧值乘 `1e-20`，count/shared 重新为零。其他旧格式 25/27/31 直接新建零存储。

一个容易遗漏的数值细节：旧格式 23 的启用流程先保存再读取新 mz wrapper。因此**新输入的 target/edge 也被 float32 量化**；例如 0.4 变为 `0.4000000059604645`。其他三种格式的 fresh 启用保持 double 0.4。此区别已在 12 个启用/更新/禁用案例中确认。

禁用 `mz.a()Lnet/holdemresources/internal/mx;` 时，仅 underlying 格式 23/31 会保留保存后的 float32 数值（23 去除 sharedAverage header）。25/27 返回全新普通存储。这意味着不能假设从所有模式返回都保留旧 regret/平均。

修改现有 target 的静态证据是 `sources/0525/fi.java:26`、`:60`：在对话框初始化读取旧 edge 时，先调用 mz 的 flush；确认后逐行动赋 target，清 cachedEdge 和 edgeAdder。新的 target=NaN 时，将手动 edge 写入 cache 和 adder。其余 R/D/A/count/extrema/sharedAverage 保持 flush 后状态。探针明确重演此字段赋值序列以核对数据边界，**没有执行 fi.execute 或 GUI**；不能把这项称为完整 UI 黑盒验证。

## 6. 执行限制与未证实项

Oracle 使用 platform-parent allowlist loader，只载入列明的数值存储类、BitConverter 和 UniformRandomProvider 接口。主 JAR、preflopdata JAR 与 RNG 接口依赖 hash 被钉住；运行不开放通用资源访问，不初始化应用/授权/GUI。所有实际载入类 hash 记录在报告中。

本批没有证明策略模式迁移后训练收敛、整局结果一致或任意并发操作相同；也没有证明任何具体场景一定选择格式 27/31。格式选择仍须根据真实设置/存档或运行路径核实。生产 Node 的局部数值一致不能代替整个训练路径、持久化读写或 GUI 的端到端验证。
