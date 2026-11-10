# HRC 拓扑导入与独立筹码重放

日期：2026-11-05。本轮目标是为独立 native 求解内核提供与本地 HRC 九人 20BB 存档相同的行动拓扑、逐街筹码状态和终局投入。实现位于 [hrc_tree.py](D:/Users/Shao/Documents/ChatGPT/REA/preflop_lab/hrc_tree.py)，测试位于 [test_hrc_tree.py](D:/Users/Shao/Documents/ChatGPT/REA/tests/test_hrc_tree.py)。

**已完成的是导入拓扑并独立验证状态，不是独立重建 HRC 的树生成器，也不是证明我们的策略已收敛到 HRC。** 本模块只打开 `settings.json` 和 `gametree.dat`；不打开 `nodedata.dat`、`state.json`、`idx.dat`。没有将存档策略、regret、平均策略、训练次数或叶子收益作为训练初值。独立训练能否数值对齐由另一套求解与比较实验验证。

## 实际验证结果

执行 `.venv/Scripts/python.exe -m pytest tests/test_hrc_tree.py -q`：**33 passed，1.36 秒**。三个主 fixture 的每条边、边内全部动作及每个节点状态都完成验证。

| 存档 | 节点 | 边 | 决策节点 | 终局节点 | 重放动作 | 边内额外强制动作 | 逐街切换 |
|---|---:|---:|---:|---:|---:|---:|---:|
| HU 10BB / 10m | 5 | 4 | 2 | 3 | 5 | 1 | 0 |
| 九人 10BB / initial | 6,629 | 6,628 | 3,090 | 3,539 | 7,049 | 421 | 296 |
| 九人 20BB / 60m | 12,193 | 12,192 | 5,322 | 6,871 | 12,627 | 435 | 586 |

决策节点的 preflop/flop/turn/river 分布分别为：HU `[2,0,0,0]`，九人 10BB `[1586,232,492,780]`，九人 20BB `[1586,348,1072,2316]`。对应抽象桶数从 settings 读取，当前三份存档均为 `[169,1024,256,256]`。

全部节点逐玩家满足 `remaining[i] + contributions[i] == initialStack[i]`；每个状态还满足总筹码守恒、非负投入/余额和 `streetContribution<=totalContribution`。所有终局贡献层都存在合法的未弃牌获奖者，没有发现“正底池但无 eligible 玩家”的层。全部终局已完成当前轮应答；不存在仍有两个可行动玩家却在 river 之前无故截断的终局。

| 存档 | 有弃牌死钱的终局 | 存在独占最高投入层的终局 | 最多非零贡献层 |
|---|---:|---:|---:|
| HU 10BB | 2 | 2 | 2 |
| 九人 10BB | 3,422 | 1,091 | 4 |
| 九人 20BB | 6,698 | 2,757 | 4 |

因此不能仅按 active 玩家平均分总 pot，也不能把已经弃牌的 SB/BB 或先前跟注资金丢掉。九人 20BB 有大量未跟注的最高投入：导出保留原始贡献，结算内核必须返还未匹配部分。

## 动作与状态语义

读取器是独立小型 Python 模块，不 import 研究脚本。`gametree.dat` 的每个记录以存储的 node ID 为键，记录 parent ID、decision/leaf 类型、决策 street/actor、incoming action 序列及有序 child ID 列表。树结构检查包括重复 ID、缺失子节点、父子关系、环、重复引用、不可达节点、截断与尾部多余字节。

每个 64-bit action word 解码为：

- low 4 bits：`0 fold / 1 check / 2 call / 3 raise`；保留位 4–7 必须为零。
- bits 8–11：actor；bit 12：all-in；bits 13–15：street。
- bits 16–63：金额。**call 是本次新增投入，raise 是当前街 raise-to 总额。**

初始发盲来自 settings 的 `[bigBlind,smallBlind,ante]`，不是根据第一条行动猜盲注。当前 fixture 每个 BB 是 `10000` 内部整数单位；20BB 初始栈为每人 `200000`。全程使用整数，UI/utility 接口才除以 BB。九人座位索引是 0 开始行动，最后三席 BTN/SB/BB 为 6/7/8；HU 的 BTN/SB 为 0、BB 为 1。

重放状态包括总投入、当前街投入、余额、弃牌标志、当前街、当前最高下注、最小完整加注增量、尚待行动者、加注权恢复阈值及下一行动者。每条边从父状态独立复制，不与兄弟边共享可变数组。

正常行动逐项检查：行动顺序；弃牌/全下玩家不能再行动；check 不得面对未跟注额；call 增量必须恰好为 `min(应跟额,剩余栈)`；raise-to 必须超过当前最高额且不超过自有筹码；非全下加注不得低于最小增量；不足一个完整加注的 all-in 不立即重开先前行动者的加注权；多个小额 all-in 累积达到完整增量时重开。call/raise 的 all-in flag 必须与剩余筹码是否归零完全一致。

街切换只能连续进行，并要求上一轮所有应答已结束。换街后当前街投入归零，累计投入保持，postflop 最小下注为 BB，先行动者从 SB/BB 顺时针选择；HU 翻后 BB 先行动。多条街可能已经压在一条边的 forced suffix 中，所以不能只重放第一条动作。

明确保留 HRC 的一个终局形式：弃牌后只剩一名玩家时，存档仍可能附带该幸存者的 forced check，例如 HU SB fold 后 BB check。这个 check 被识别为终局规范化动作，不错误地视为另一个策略节点。

这些检查验证通常的下注合法性与状态一致性。`ALLOWED_FLATS_PER_RAISE`、`maxactive`、下注尺寸模板、donk 限制等**树抽象配置产生了哪些候选边**仍由输入拓扑给定，本模块没有独立生成并证明所有应有分支都存在。

## native 数据接口

```python
from preflop_lab.hrc_tree import load_hrc_tree

tree = load_hrc_tree(
    "analysis/hrc-desktop/nine20bb-raise-call-postflop-60m.hrcz"
)
native_input = tree.compact_export()
```

顶层 schema 为 `hrc-topology-replay-v1`：`root`、`players`、`big_blind`、`initial_stacks`、`nodes`、`terminals`、`provenance`、`validation`。金额保持内部整数，不提前转换为浮点 BB。

`nodes` 按原 node ID 连续索引，每项为：

```text
id, actor (-1=leaf), street, buckets,
children [node IDs in saved edge order],
actions [0/1/2/3, first decision action per edge],
terminal_id (-1=decision), special
```

`special` 对应第二条边首动作是 check 的情形：其子节点为 leaf 时为 1，decision 时为 2，否则为 0。它不改变重放；供 native 调度路径使用。

`terminals` 每项包含 `id/node_id/remaining/contributions/folded/live/live_mask`。完整强制动作已重放到终局 state，native 不得再重复扣这些钱。全部贡献包含死钱及未跟注最高层；这些值不是最终派奖后的 stack，也不是存档叶子 EV。

浏览可用 `tree.describe_node(path)`、`tree.describe_node(node_id=...)`、`tree.get_node(path)`、`tree.node_path(node_id)`。path 是原 edge index 的字符串数组，例如 `["1","0"]`；返回的新字典/列表使用 BB 单位，nodes/states 本身使用 frozen dataclass 与 tuple，不消耗训练 RNG、访问计数或预算。根代理已有相同约定的 GUI adapter，可直接沿用。

## 与现有结算研究衔接

此前原始 `lH` 数值探针已经确认 HRC finalChips 对平局使用整数商及余数，见 [HRC-TREE-PERSISTENCE.md](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-TREE-PERSISTENCE.md)。具体方法为 `lH.a(Lnet/holdemresources/internal/lK;[ILjava/util/List;Z)Lnet/holdemresources/internal/lE;`。

原始 `lJ.compareTo(Ljava/lang/Object;)I` 排序是 rank 降序、贡献升序、seat 降序。`lH` 指令偏移 749–767 把整个 `pot % winnerCount` 加给排序首位赢家，不是给前 r 个玩家每人一单位。pot detail 的余数记录位置不同；本次 native 应对齐 finalChips。证据：[lH bytecode](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0699/bytecode.txt)、[lJ bytecode](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0697/bytecode.txt)。

还需避免一个容易遗漏的整数舍入差别：不能在所有贡献阈值各自独立分配余数。HRC 会按实际获胜者贡献边界合池；若相邻 tier 的赢家集合相同，应合并后再做商/余数。例如贡献 `[100,100,100,1,2]`，前三人平局、后两人弃牌，总池 303，应得到 `[101,101,101,0,0]`。把所有贡献层各自除以 3 并总把余数给同一位，会错误得到赢家 `[100,100,103]` 的某种座位排列。这个风险已经同步给 native 内核作者；本拓扑模块只导出原始状态，不自行派奖。

## 存档训练/重载一致性

四组比较通过：HU initial→10m、HU 10m→reloaded、九人 10BB initial→reloaded、九人 20BB initial→60m。settings 字节相同，解析后所有节点/动作/父子关系和全部重放状态相同。

**实际发现：**HU 和九人 10BB 重新保存后，`gametree.dat` 的记录序列会重排；原 node ID 及逻辑拓扑不变。因此不能把“文件中第几个记录”当 node ID，也不能以 gametree 原始字节差异直接宣称树变化。九人 20BB initial/60m 这两份文件恰好连 gametree 字节也相同。

主 fixture 的结构指纹：

| 存档 | settings SHA-256 | gametree SHA-256 |
|---|---|---|
| HU 10BB / 10m | `763347419d06934f26cf708ebcdae430db796f06ab242cd536cda1299434c51a` | `371b46c4a652854cb09a9b863f3261cb84fb8bb66e8179f0059b9aa674c3c66f` |
| 九人 10BB / initial | `1ba60d2cc3e4a776a49c1743d5dea8bf64900ff93c643add9aba7908cb61f2b2` | `9f8f7e2910be7dcc41ee2af9dafd9976f2bac5f4404e04cfcffe2513c0f30bb5` |
| 九人 20BB / 60m | `713a472a3465cbdb542b1fa848059be011297ba137d60071210fcc8b141b7789` | `7059799d13f3aca37e2d941644ef4dcd09b0da404709d74dc666cf9c103c44a8` |

## 测试范围与限制

33 项 pytest 实例覆盖：只读取两个允许成员；修改策略 payload 不影响导入；HU walk、all-in call、弃牌死钱和未跟注投入；native 导出顺序；不可变浏览；跨街 raise-to；HU 翻后顺序；单个不足额 all-in 不重开与累积不足额 all-in 重开；七种非法动作/轮次；过早 leaf；五种结构损坏；四种未验证配置；三份真实存档全量重放；四组训练/重载一致性。

当前导入明确限于：2–10 人，初始栈均大于 BB，正 SB≤BB，无 ante、straddle、skip-SB、moving-button 或固定 board subtree，unraked chipEV，四街正桶数且 preflop=169。其余设置显式拒绝；不能从这三份 fixture 推导所有 HRC 配置均已支持。local fixture 测试在原文件缺失时 skip，合成边界测试不依赖商业软件。

本报告没有宣称 native CFR 更新、抽象桶、发牌、最终收益、统计精度或训练范围已经与 HRC 相同。它提供了可复现的拓扑/状态基础，使这些后续比较不再混入未记账的强制动作、错误盲注单位、丢失死钱或不完整轮次等问题。
