# MTT 权益：独立实现与原始字节码对照

2026-11-05。对象为本地 HRC `4.1.0.202603231401`，主 JAR SHA-256 为 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。本报告的“一致”只指下述 MTT 纯权益数值接口，不是整局策略、MTT 全部规则或近似模型准确性的证明。

**交付：**`preflop_lab/mtt_equity.py` 和 `native/hrc_mtt.hpp` 已实现可独立运行的 MTT 权益；生产路径不载入 HRC 类、存档叶值或策略。72 组原始字节码/Python/C++ 对照全部通过，最大差异分别为 `2.842170943040401e-14`、`1.1368683772161603e-13` 奖金单位。另有 3 个数值域边界对照和 33 个普通单元测试。原始输入、输出、类与文件 hash、编译命令见 [完整验证记录](../reports/hrc-original-mtt-validation.json)。

## 1. 稳定接口与调用约定

```python
from preflop_lab.mtt_equity import Calculator, mtt_icm_equities
values = mtt_icm_equities(table_stacks, payouts, other_stacks)
prepared = Calculator(payouts, other_stacks)
values = prepared.equities(table_stacks)
```

```cpp
#include "native/hrc_mtt.hpp"
auto values = hrc_mtt::equities(table_stacks, payouts, other_stacks);
const hrc_mtt::Calculator prepared(payouts, other_stacks);
auto values2 = prepared.equities(table_stacks);
```

三项均为浮点序列；本桌和外桌筹码必须使用同一单位。`table_stacks` 仅包含幸存者，返回顺序对应本桌输入顺序，结果是绝对奖金权益，不是净变化、百分比或 BB。`payouts` 是完整原始名次奖金表，允许长于当前幸存人数。调用者处理立即淘汰奖金、淘汰平分、赏金现金支付、PKO 递延池和原座位映射；不得把这些再加进本内核一次。

配置可预构建以免反复复制外桌数组。计算 scratch 是每次调用私有的，C++ `const Calculator` 可供不同线程并发调用。未添加结果缓存；调用者可以对相同终局筹码状态复用结果。

## 2. 原始路径与确定事实

| 方法/证据锚点 | 已确认行为 |
|---|---|
| `lg.<init>([D[D)V`，`sources/0930/lg.java:16`，`equity/0930_lg/bytecode.txt` BCI 15–27 | 第一数组为完整奖金表，第二数组为外桌筹码；只在外桌人数 `>=100` 时选择大场近似，与总人数阈值不同。 |
| `lg.a([D)[D`，`lg.java:23` | 拼接本桌和外桌，每个本桌玩家单独计算，不返回外桌玩家向量。 |
| `lg.a([D[DID)D`，`lg.java:122` | 条件排名的精确 Poisson-binomial 递推，奖金与排名点积仅取 `min(奖金长度, 全场人数)`。 |
| `lg.a(DDDD)D`，`lg.java:149` | 连续性修正的正态 CDF，加三阶 Edgeworth 修正；未裁剪到 `[0,1]`。 |
| `lg.java:41,87,100` | 第三名以后做 QNG 积分；前两名用闭式精确概率；特殊分段最多 20 次。 |
| `lg.java:80,114` | 近似积分值为 NaN 时回退精确排名积分；最终 NaN 抛异常，但最终 infinity 没有同等检查。 |
| `li.b(Lnet/holdemresources/internal/kG;)[D`，`sources/0929/li.java:12` | 读取 `lh`，调用 `lg`，再按本桌筹码占全场筹码比例加入未来赏金池。 |
| `li.a(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D`，`li.java:35` | 立即淘汰奖金从奖金表偏移外桌人数后交给 `kC`；幸存者仍使用完整原始奖金表，不先截断。 |
| `lh.a()D`，`sources/0928/lh.java:39` | PKO 未来池是本桌当前 bounty 之和加外桌人数乘 `otheravgbounty`；固定 KO 为剩余全场人数乘固定 bounty。 |
| `lh.a(Lnet/holdemresources/internal/lE;)Lnet/holdemresources/internal/kH;`，`lh.java:44` | 本桌淘汰后更新本桌 bounty，外桌筹码与平均 bounty 保持不变。 |
| `kS.a(Lnet/holdemresources/internal/kJ;)Lnet/holdemresources/internal/kG;`，`sources/0904/kS.java:18` | `otherstacks` 与 PKO 的 `otheravgbounty` 来自配置。 |

源与字节码证据均位于 `analysis/hrc-deep/`。这些路径的字段名称被混淆，表中依赖 descriptor 区分返回类型和同名字段，不能仅凭 Java 反编译变量名解释单位。

完整外桌 bounty 列表在该静态未来池公式里可用总和表示；原对象实际上仅存平均 bounty，不能据此声称模拟了外桌各人的后续 KO 过程。

## 3. 独立公式与兼容细节

设全场正筹码为 `s`，目标为 `h`，总筹码 `S`，名次奖金从 0 开始为 `p`。

前两名的贡献为：

\[
E_{h,1}=p_0\frac{s_h}{S},\qquad
E_{h,2}=p_1\sum_{j\ne h}\frac{s_j}{S}\frac{s_h}{S-s_j}.
\]

其余贡献采用指数竞争模型。令目标的指数时钟为 `T_h`，取 `t=exp(-s_h T_h)`，则 `t` 在 `(0,1)` 均匀；对手晚于目标的条件概率为 `q_j(t)=t^(s_j/s_h)`。给定 `t` 时各对手独立。对“落在目标之后的人数”做 Bernoulli 卷积，映射为名次后与奖金点积，再对 `t` 积分。这是独立实现中 `_rank_integrand` / `detail::rank_integrand` 的来源；不使用任何原始存档权益。

外桌人数达到 100 后，设 `m=Σq`、`v=Σq(1-q)`、`κ=Σq(1-q)(1-2q)`、`σ=sqrt(v)`，用

\[
F(k)=\Phi(z)+\frac{\kappa}{6\sigma^3}(1-z^2)\phi(z),\qquad
z=\frac{k+0.5-m}{\sigma}
\]

近似落后人数的累计分布。仅在奖金变化处取 CDF 差，加权为积分值。原实现没有把负概率或超过 1 的概率裁剪，也没有全场归一。实现保留这些行为。近似的完整奖金循环在奖金表长于场人数时仍继续运行；精确递推则自然截断。

QNG 是固定嵌套 21/43/87 节点积分。绝对和相对停止阈值均为 `1e-10`，但到 87 节点后无论误差估计是否达标都返回。这解释了小场也会有积分误差。另一个兼容细节是第一次误差缩放使用尚未乘区间半长度的偏差总和；后续层使用缩放后的值。

特殊分段以近似积分函数在 `(1-left)*0.75` 处是否恰为 0 为条件，同时要求已积累积分也恰为 0。注意原检查点并不是 `left+(1-left)*0.75`；后一项才是新区间右边界。最多分 20 段，之后总是积完剩余区间。即使处于小场精确分支，分段检测也使用近似函数。

正态尾部延续被审计依赖的渐近展开停止约定及 `exp` 截断。实现用平台 `erf` 和独立积分/概率代码；本次 Windows JDK/Python/zig 数值结果高度一致，不声称跨平台逐位相同。

## 4. 原始字节码的执行隔离

[OriginalMttProbe.java](../scripts/java/OriginalMttProbe.java) 将主 JAR、JQuantlib 和 Commons Lang 三项 SHA-256 固定到已审计版本。ClassLoader 的父层仅为 Java platform loader；允许加载的 14 个类为：

- HRC 的 `lg`、`kV`。
- Commons Lang 的 `ArrayUtils`。
- JQuantlib 的 `QL`、`LibraryException`、`Constants`、`ErrorFunction`、`Ops$DoubleOp`、`Derivative`、`NormalDistribution`、`CumulativeNormalDistribution`、`Integrator`、`KronrodIntegral`、`GaussKronrodNonAdaptive`。

`lg.<clinit>` 仅构造标准正态对象；正态类初始化数字常量、误差函数和标准密度；`ArrayUtils.<clinit>` 仅构造 JDK 类型的空数组。`QL` 的成功断言路径不触发日志系统。`LibraryException` 为验证时需要解析的异常类型，在成功数值路径没有实例化；未把其潜在日志依赖加入 allowlist。原始 target 的资源查找会被探针拒绝，成功执行未触发资源查找。探针自己的文件操作仅为读取已知 JAR/输入 TSV 和向标准输出写审计记录。

没有调用 HRC 应用入口、GUI、授权逻辑、原求解器或保存策略。报告保留所有实际加载类的 hash。故本验证不是对任意换版 JAR 的运行授权。

## 5. 覆盖范围、准确性和域边界

72 个兼容案例覆盖：外桌人数 0、1、8、99、100、1000、5000；本桌 1–8 人；等筹码、阶梯奖金、所有人同奖、仅前两名、冠军独得、零奖金；筹码单位缩放 `1e-100` 和 `1e100`；最高测试筹码比例 `1e15`；存活后保留长于当前人数的完整奖金表。原始与独立值之差只是实现兼容误差。

小场另用“前一名获胜后从剩余筹码重新选择下一名”的独立前向名次枚举对照真实 ICM。发现下述原始行为并照实保留：

| 输入 | 原始结果或误差 |
|---|---|
| 本桌 `[2,4,9]`，全员奖金 100，无外桌 | `[100.00000000000067,99.99999882767574,99.99997615984006]`；最大真实 ICM 偏差约 `2.38e-5`。 |
| 本桌 `[.001,10,10000]`，奖金 `[1000,500,200]`，无外桌 | 与前向精确 ICM 最大差异 `0.01999801975600235`。 |
| 本桌 `[20,35,90]`，100 个固定异质外桌筹码，全员奖金 100 | `[99.85060005517461,99.9826818098798,100.0011198849433]`；数学上每人必然得到 100，而大场近似未严格守恒。 |
| 同一 101 人等筹码场，99 人外桌 vs 100 人外桌，奖金 `[1000,500,200]` | 一个目标权益由 `16.831683168316832` 变为 `16.83170414167392`；这是原阈值切换造成的模型差异。 |

因而“与原版对齐”不能被写成“所有场规模下的精确 ICM”，也不能用这些测试推断策略已经收敛。

生产接口额外拒绝非有限或非正筹码、空本桌、空/负/非递减奖金表、总筹码溢出，以及全场总和已无法分辨最大筹码以外筹码的 float64 输入。后两项与原版错误数值行为有意不同：

- `[1,1e18]`、奖金 `[100,50]`：原始输出 `[Infinity,100]`，独立接口拒绝。
- `[1e308,1e308]`、奖金 `[100,50]`：原始输出 `[0,0]`，独立接口拒绝。
- `[0,10]`、奖金 `[100,50]`：原始抛 `IllegalArgumentException`，独立接口给出明确输入错误。

这些检查不构成全部极端数值域的误差上界。非常小/大的筹码比例仍可能触发近似回退和分段积分。没有证明全域正性、奖池守恒、统一收敛误差或跨版本兼容。

## 6. 成本与复现

固定平台本次运行的 72 案例 C++ 求值时间合计约 45.6 ms；单例 5000 外桌/2 本桌/前 3 名约 9.6 ms；1000 外桌极端筹码/3 本桌约 13.1 ms。该统计是有进程预热影响的单次探针记录，不是生产吞吐承诺。Python 参考在极端 1000 外桌案例约 2.31 秒，适合验证，不宜放入高频终局训练热路径。

精确排名积分每次评估约 `O(N²)`，大场近似约 `O(N + 奖金表长度)`；近似遇到退化方差/NaN 会回退 `O(N²)`。还须乘本桌人数、QNG 节点数和特殊分段次数。固定外桌配置的 `Calculator` 减少配置复制，但不消除这些计算。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_hrc_mtt.py -q
.venv/Scripts/python.exe scripts/validate-hrc-mtt.py
```

前者 33 项通过且不需要原软件。后者生成输入并编译独立 C++ harness 与隔离 Java probe，72 个有效域案例和 3 个明确域边界全部通过。C++ 采用 `-O3 -ffp-contract=off`；不得用 `-ffast-math` 破坏 NaN 回退/严格有限检查。再生输入不依赖 `analysis/` 中的旧反编译文件。

尚未覆盖：外桌动态淘汰/换桌、外桌 bounty 分布演变、不同 HRC 版本、所有实数输入的误差界、MTT 加赏金的整局策略一致性。立即结算与赏金 wrapper 由独立收益模块负责，其验证不由本报告代替。
