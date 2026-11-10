# 独立四街树生成器

2026-11-05。实现文件为 [hrc_tree_builder.py](D:/Users/Shao/Documents/ChatGPT/REA/preflop_lab/hrc_tree_builder.py)。它从显式配置生成节点、动作和筹码状态；生成过程不打开 HRC 存档，不读取策略、叶子权益或原版求解类。原始存档只在生成完成之后用于验证。

## 已交付接口与边界

```python
from preflop_lab.hrc_tree_builder import default_settings, build_tree

settings = default_settings(players=8, stack=150000, big_blind=10000)
tree = build_tree(settings, node_budget=250000)
button = tree.describe_node(["0"] * 5)
native_input = tree.compact_export()
```

`stack` 可为正整数或每席位整数列表。也可直接提供包含 `handdata/treeconfig/engine` 的显式 HRC 形状配置。金额全程使用整数，`10000=1BB` 只是本地场景的约定。`GeneratedTree` 提供 `settings/rules/nodes/states/root/provenance/validation`、`node_path/get_node/describe_node/compact_export`。取消回调立即中断并报出取消，进度回调每 1,000 个生成节点提供计数；超过节点预算、256 个行动的深度或单节点 16 个动作时明确失败，不截断并冒充完整树。

运行耗时保留于 `tree.validation`，从 compact 导出中移除；相同显式配置重新生成的 compact JSON 完全一致，训练续跑不会因生成耗时改变 checkpoint identity。

已实现 2–10 席、不同正筹码（可不足盲注）、0≤SB≤BB、普通 ante、BB ante 的先 ante/先盲注模式、skipSB、单/双/button straddle，四街的 fold/check/call/raise、有效全下、原版最小加注/重开、参与者 cap、强制动作合并。HU straddle 被明确拒绝。

树策略支持已审 `preflop.settings.simple` 与 `postflop.settings.simple`，后续亦支持两个 `*.settings.general` 并可独立混搭。翻前支持 BB 倍数、最近下注倍数、pot 百分比、all-in，以及按已有跟注者添加的 `2bb + 1bb` 形式；支持各下注层 flat 上限、SB complete、all-in 阈值。simple翻后支持 HU/多人两组 geometric hints、flop bet/cbet/donk/raise 的 pot 尺寸覆盖、SPR 附加全下、donk/曾加注例外、下注次数阈值和按人数规定最后下注街。

`movingBu` 已接受并保留；原版该字段只作用于终局以后下一手的轮转，不改变当前手建树。general的全部38个本机设置和moving原方法证据见 [HRC-GENERAL-BUILDER.md](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-GENERAL-BUILDER.md)。任意 JavaScript 仍不执行；固定board subtree由独立后续模块处理。这里的“simple”是原版设置类型名称，不代表把后街改成 check-down；已比对场景具有完整四街策略节点。原设置指定的 forced check-down 限制仍保留。

## 状态与 BB ante

普通 ante 计入每位玩家的累计贡献，不计入当前街下注。BB ante 从 BB 余额扣除，保存为独立 `dead_money`，不增加 BB 的个人可赢投入。各状态满足：

`sum(remaining) + sum(contributions) + dead_money == sum(initial_stacks)`。

`compact_export().terminals` 比旧导入格式额外包含 `dead_money`。结算方必须将它作为最底层的独立资金，资格为所有未弃牌者，包含被 BB ante 扣尽且个人贡献为零的玩家；随后才处理普通正贡献层。将这笔钱直接加入首个正贡献池，会错误排除零贡献的全下 BB。

弃牌时，原 `lC` 将该席当前街下注移入累计死钱，本实现照此记账。旧独立 replayer 会在弃牌席保留当前街投入；因此两者 `street_contributions` 在已经弃牌的席位不必相同，但累计投入、底池与全部后续行动一致。生成器不采用旧 replayer 的标准累计短加注重开规则，而使用已观察到的原 `lB` 历史规则。

## 原始依据

主 JAR SHA-256：`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。完整原始规则研究见 [HRC-TREE-PERSISTENCE.md](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-TREE-PERSISTENCE.md)。

| 功能 | 具体原类/方法与证据 |
|---|---|
| 初始化 ante/blind/straddle | `lC.a(Lnet/holdemresources/internal/kG;)Lnet/holdemresources/internal/lC;`；[lC.java:199](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0692/lC.java:199) |
| 动作状态更新、换街 | `lC.a(Lnet/holdemresources/internal/ly;)Lnet/holdemresources/internal/lC;`、`a()LlC;`；[lC.java:86](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0692/lC.java:86) |
| 行动顺序、minimum/maximum | `lB.<init>(LkG;LlC;Ljava/util/List;II)V`（类名均在 `net/holdemresources/internal/`）；[lB.java:42](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0695/lB.java:42)，完整描述符见 `analysis/hrc-deep/tree/0695/bytecode.txt` |
| 低层加注归一化 | `lB.a(J)Lnet/holdemresources/internal/lB;`；同字节码文件方法第 790 行起 |
| 有序行动、参与者 cap、特殊 check/fold | `mF.a()[Lnet/holdemresources/internal/rD;`；[mF.java:48](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0047/mF.java:48) |
| 强制单子边折叠 | `ml.a(Lmf;ILrD;Lmi;Lld;Z)Lmj;`（同内部包）；[ml.java:20](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0015/ml.java:20) |
| pot / geometric 尺寸 | `mG.c(Lnet/holdemresources/internal/lB;D)J`、`mG.d(Lnet/holdemresources/internal/lB;D)J`；[mG.java:20](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0045/mG.java:20) |
| 预置 simple 策略 | 主 JAR 内 `net/holdemresources/scripting/treescripts/scripts/preflop/preflop_simple.js` 与 `postflop/postflop_basic.js`；仅作为规则证据，不打包或执行原脚本 |
| PKO 的额外 fold 分支 | `mL.a(Lnet/holdemresources/internal/lB;)Ljava/util/Collection;`，将后街尺寸映为全下或靠近 75% 的 geometric；[mL.java:25](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0046/mL.java:25) |

`special_fold_mode` 可显式设 `none/checkdown/compressed/ordinary`。默认从 `eqmodel.structure.bountyType` 选择：无 bounty 为翻前 checkdown 反事实 fold，有 bounty 为 compressed，后街不增加此分支。它只在可过牌且存在加注尺寸时出现，供原求解语义排除动作 0，并非把无代价弃牌当正常策略。可平跟的测试场景证明两种模式生成不同子树；本批桌面默认场景没有触发这条特殊翻前分支。

## 实际验证与纠正

执行 `.venv/Scripts/python.exe scripts/validate-hrc-tree-builder.py`，结果保存在 [hrc-original-tree-builder-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-tree-builder-validation.json)。

160 组不同配置、943 个原 `lB/lC/mG` 快照全部逐项相等，覆盖 2–10 人、短于盲注的栈、三种 ante、四种 straddle、skipSB、跨街行动、下注/跟注次数、参与者/弃牌 mask、minimum/maximum、完整行动序列、66% geometric 与 50% pot 尺寸。探针复用已审隔离 loader，只执行真实规则类，不启动应用、许可流程或求解器。

首轮实验发现并修正两处误解，失败记录保留于 `analysis/hrc-deep/probes/tree-builder-first-validation.json`：

- 原 `lB.b:J`（maximum）在 actor 存在时仍有值，即使 minimum=-1 禁止加注；反编译的同名字段曾掩盖 int actor 与 long minimum 的区别，字节码偏移 742–805 已核实。
- `mF` 先将尺寸钳制到有效上限，随后 `lB.a(J)` 重新提升到 minimum，并**先检查自身总栈再检查有效对手上限**。某些短筹码条件下最终原始边会高于有效上限并留有未跟注部分。本实现保留实际原行为，不用常见规则替换。完整原 `lH` 结算须返还未跟注资金。

五棵独立生成的完整树与桌面存档逐节点、逐动作、逐金额、逐 all-in flag、逐终局筹码相符：

| 场景 | 节点数 | 本机生成时间（秒，近似） |
|---|---:|---:|
| HU 10BB push/fold | 5 | 0.0002 |
| 八人 15BB raise/call 四街 | 4,786 | 0.10 |
| 九人 10BB raise/call 四街 | 6,629 | 0.15 |
| 九人 20BB raise/call 四街 | 12,193 | 0.28 |
| 八人 15BB PKO，50/30/20，悬赏10，alpha=.5 | 4,786 | 0.10 |

生成配置均由明确数字独立构造，未先读取存档 settings 或 gametree。对照阶段只读取原 gametree，既不使用 `nodedata` 也不使用叶子 EV。八人默认场景 ChipEV 与 PKO 的拓扑相同，因为它们没有产生需要特殊处理的翻前可过牌节点；这不推广为所有赏金配置拓扑相同。

`.venv/Scripts/python.exe -m pytest tests/test_hrc_tree_builder.py -q`：**57 通过**，覆盖以上五棵原树、无存档读取、重复生成的确定性、2–10 人各 ante 的全树守恒、straddle 行动顺序、零贡献 BB ante 全下资格、短加注重开、有效全下后剩余筹码、再加注与跟注附加尺寸、特殊 fold 子树、预算/取消与配置错误。数值快照和有限场景相符不等于已穷举全部配置，也不证明求解范围已收敛。
