# HRC 本体还原：当前成果与验收范围

2026-11-05 差异诊断：追加同配置 seed44 的 6000 万次受控实验。seed43/44 的 BTN 逐手牌／行动 MAE 为 3.1179 个百分点，与 seed43/HRC 的 3.0473 同量级；支持有限预算下的轨迹敏感性，尚未排除共同实现偏差或证明混频等价。见[原因调查与验证边界](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-STRATEGY-DIFFERENCES.md)。

2026-11-05 八人 15BB 补充：双方约 6000 万次已完成；前五人弃牌后的 BTN，加注原版 25.0711% / 我们 25.0005%，全下 6.1626% / 5.7604%。逐手牌／行动频率 MAE 3.0473 个百分点，A6s 等混合行动分配仍存在明显差异。见[八人 BTN 对照报告](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-8MAX-15BB-BTN.md)。

2026-11-04。本轮直接分析本机HRC 4.1.0.202603231401，并执行未修改的原始数值与规则类。随后已启动真实HRC Pro桌面，建立单挑和九人计算，保存原版结果并进行独立数值核对。此前Preflop Lab仍是独立简化原型，不能当作HRC已复现的结果。

**2026-11-05 更新：独立九人训练已接通并实测。** 网页新增固定原生对照模式，使用独立 C++ v4 内核，从零完成两组九人 20BB、各 6000 万次训练。行动树导入自原版存档，翻后桶读取本机资源；原版已训练策略只用于事后比较。UTG 开池率为 13.1361% / 13.1246%，原版为 13.0864%；逐手牌／行动频率 MAE 为 1.2336 / 0.6815 个百分点。全部翻前节点已比较，按原版到达分布抽样的平均策略 TV 仍为 3.3744% / 3.4225%，没有整树完全一致的结论。详见[最终对照报告](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-NATIVE-COMPARISON.md)。下文桌面操作为上一阶段历史记录。

## 新增：真实桌面对照

Windows桌面控制已接通：通过HRC自身的新建、计算、保存、载入菜单操作。REA自带原生UI观察仅支持macOS，本次Windows观察使用pywinauto、进程限定的输入和PrintWindow截图，证据不冒充REA原生UI调用。

- **单挑10BB ChipEV全下/弃牌**：原版先自动训练约1000万次，再通过HRC 4.0计算选项追加1000万次。两份存档恢复全部169×2手牌策略；原版SB全下58.412911%，独立线性规划58.283785%。原版平均策略在独立有限博弈中的双方最佳回应改善之和为0.000801842 BB/手。临界手牌仍有显著混合频率差，不能称逐项一致。
- **保存往返**：通过GUI载入训练后单挑文件再另存，settings/state、树、原始策略累加量、计数与锁集合均精确一致；记录顺序不同导致ZIP字节不同。18项有限GUI数值/保存检查通过。
- **九人10BB建树**：原版实际创建2BB开局加注、跟注、全下和翻后分支；3,090个决策节点，其中翻前1,586、flop232、turn492、river780。保存解析恢复UTG加注8.130668%、全下2.840083%，与GUI的8.1%/2.8%对应。九人存档也经GUI加载再另存，format23/25的规范化核心状态精确一致。这是原版实测夹具，尚未由独立引擎重建求解。

独立LP与最佳回应代码没有调用HRC求解器，但摊牌机会概率读取本机HRC已安装的2wh资源；不是已独立生成全部胜率表。详见[数值基准](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-HU-INDEPENDENT-BENCHMARK.md)、[GUI与保存核对](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/HU-SAVE-CROSSCHECK.md)及[实际操作日志](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/actions.jsonl)。

[九人存档报告](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/NINE-SAVE-CROSSCHECK.md)记录19项实际GUI/结构/往返核对，均通过。可运行[桌面证据复核脚本](D:/Users/Shao/Documents/ChatGPT/REA/Run-HRC-Desktop-Checks.ps1)重做单挑存档解码、保存往返和独立基准；该脚本不操作GUI，已实际运行通过。原始存档和观察保持在analysis/hrc-desktop，复核输出独立放在rechecks子目录。

## 已完成的具体工作

随后应用户要求完成[九人20BB桌面试算](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-20BB-DESKTOP.md)：设置只改九个筹码值，决策节点5,322；累计约6000万采样后UTG加注2BB为13.0864%、全下0.0212%。初始与追加结果仍有明显频率变化，未宣称收敛或独立引擎已复现。

主插件986个class全部建立按精确大小写、原JAR序号及SHA-256区分的源码索引；全部完成javap反汇编。ASM索引覆盖5,847个方法、2,895个字段、28,978个直接方法调用位置和1,659个invokedynamic位置。两个方法的Java反编译失败仍保留原始字节码，其他反编译文本也不能当作可重新编译的原始源码。调用索引不声称已经解析所有动态分派和反射。

三条主调查链已落到具体方法、字段布局、描述符和字节码偏移：

- [求解核心](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-SOLVER-CORE.md)：v3/v4选择、worker、机会采样、向量与标量递归、遗憾/平均更新、探索、锁定、CI。
- [收益与抽象](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-EQUITY-ABSTRACTION.md)：ICM、MTT积分近似、KO/PKO、FGS、牌评估、概率表、翻后桶与动态子树。
- [建树与保存](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-TREE-PERSISTENCE.md)：脚本桥、合法候选、短全下、参与人数限制、边池、ZIP内部结构及状态恢复。

## 原始字节码验证结果

| 对象 | 已完成验证 | 证据边界 |
|---|---|---|
| 精确ICM | 41案例，1–10人；最大绝对误差2.27e-13 | 正筹码内核，不包括全部扩展收益模型 |
| 七张牌评估 | 2,318组，九种牌型、平局/踢脚/花色置换 | 排序与平局验证，未穷举所有七张牌 |
| 花色规范化和二进制读取 | 2,528掩码案例、32组小端读取 | 具体纯方法 |
| 策略存储 | 30项通过 | mE/mA/mv等，无并行调度复现 |
| 下注规则/合法候选 | 8项通过 | 固定配置，保留首轮失败与纠正 |
| 边池结算 | 7项通过 | 合成终局，无rake；发现奇数筹码明细差异 |
| 原始发牌→遍历→牌评估→存储 | 52项通过 | 单节点合成收益夹具，直接验证v3/v4跳过差异 |
| 一个64桶flop配置 | 22,100牌面、25,989,600合法牌面/手牌映射全域通过 | 只限该已安装profile，不代表其他街或抽象生成算法 |

完整输入、原始输出、运行命令、源码/工件哈希和失败记录见 [验证说明](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-BYTECODE-VALIDATION.md)。可直接运行 [统一检查脚本](D:/Users/Shao/Documents/ChatGPT/REA/Run-HRC-Research-Checks.ps1)，七组检查已统一通过。

## 对先前算法判断的修正

HRC当前核心不能等同于原型的通用external-sampling MCCFR实现。原始向量遍历沿选中行动返回全体玩家收益，同时用标量递归估计替代行动；v4在标量路径以 `1/(d+2)` 概率跳过当前目标玩家节点的更新，d仅随这类跳过增长。

翻前mE的遗憾更新为 `R[a] += t*w*(Q[a]−sum(p*Q))`，平均累积为 `A[a] += t*p[a]`。t来自本节点计数与缓存刷新，不是简单全局迭代号。翻后mA的公共平均采用另一参数控制，不能套用相同布局。

CI实际取近期策略L1变化、节点更新计数及历史平滑，没有在这条路径上计算统计置信区间或最佳响应误差。原型若要对齐HRC，必须明确实现这些实际行为，并加入抽象翻后延续；只增加座位数不足以做到算法等价。

本机Monte Carlo的maxactive编辑器接受2–10，但maxactive是累计参与者限制，不是桌上人数。之前原型的六人限制来自我们自己的范围与性能取舍；精确ICM和本轮所恢复的核心没有由此得出六人数学上限。

## 尚未达到的完成标准

完整HRC的功能及数值等价尚未建立。单挑全下树已形成原版GUI→存档→独立优化/最佳回应的实际闭环；九人固定树的翻前与翻后独立训练、全部翻前节点范围/相对 EV 对照也已完成。主要缺口是独立树生成和抽象训练、九人整树策略差异及翻后桶误差认证、全部抽象配置和动态子树、MTT/KO/PKO/FGS、非空锁与其他存储格式，以及其余影响输出的插件和配置分支。

固定树已重放全部 12,193 个节点，并接入三街桶、真实发牌和整数筹码结算。200 个合成案例的 3200 个嵌套遍历快照与原始字节码完全一致，覆盖 136,960 个数值；这验证具体更新逻辑，不能替代整产品证明。后续应定位已测到的下游策略差异，补全翻后逐桶对照和独立树生成。详细逐项状态和REA残余未知在[调查账本](D:/Users/Shao/Documents/ChatGPT/REA/INVESTIGATION.md)。
