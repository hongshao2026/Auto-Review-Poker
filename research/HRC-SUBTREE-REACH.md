# 父策略范围递归与独立子树提取

2026-11-05。本批实现 `preflop_lab/hrc_subtree_ranges.py`，输入已验证的原/独立树、节点路径、公共牌历史，以及调用方显式选择的父策略；输出每座位 1326 物理手牌的 reach 权重、active 标记、源节点筹码状态和原 subtree JSON 的字段形状。模块不自动打开原存档策略或 checkpoint，不训练，也不裁剪树。

**验证结果：**20 条合成跨街链、92 个所选节点、365,976 个 double，与原始 `lq` 递归及原 `lR/lU` 默认祖先遍历逐位一致，最大误差 0。另对原 `lO` 格式化和 `lQ` 回读覆盖 8 种小数位（0/1/2/3/4/5/6/12），含删牌阈值两侧、舍入边界、接近 1、超过 1、极小权重，文本和回读数组完全一致。11 项单测通过，包括独立生成树及真实九人存档的**拓扑/状态**适配；该存档测试使用显式合成父策略，没有读取其 `nodedata`。

证据：[hrc-original-reach-validation.json](../reports/hrc-original-reach-validation.json)。该结论验证范围数学和输入状态交接，不证明子树训练收敛、整局策略或多线程 worker 等价。

## 一、原调用链与精确语义

目标主 JAR SHA-256：`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。源码锚点以下相对 `analysis/hrc-deep/sources/`，descriptor 已以 ASM 索引核对。

| 原方法 | 源码锚点 | 事实 |
| --- | --- | --- |
| `lU.f(I)[D` | `0003/lU.java:14` | 普通根返回 169 个 1；子节点沿父接口请求该玩家到达此节点的范围。 |
| `lR.a(LlU;I)[D` | `0004/lR.java:72` | 沿祖先递归；只在祖先 actor 等于目标玩家时乘所选行动概率，不乘其他玩家的策略。完整类型名为 `net/holdemresources/internal/lU`。 |
| `mf.a(I)[D` | `0013/mf.java:140` | 返回当前 actor 的进入范围乘所选行动概率。 |
| `mf.b(I)[D` | `0013/mf.java:189` | 逐 bucket 取 storage 的显示行动概率，非未经处理的 regret。 |
| `mt.a(I)[D`、`mt.a(II)D` | `0027/mt.java:48`、54 | 有平均策略区则从平均策略区归一化；否则从 regret 区归一化。locks/频率控制包装仍由其 storage 接口决定。 |
| `lq.a([DJ)[D` | `0691/lq.java:7` | 按原 169 类到 1326 combo 映射扩展，清除指定 board 的冲突牌。 |
| `lq.a([D[D[IJ)[D` | 同文件 19 行，private static | `old[c] * action[bucket[c]]`；bucket<0 或与 board 冲突则置 0，不归一化。 |
| `lq.b([DJ)[D` | 同文件 33 行 | clone 后清除 board blockers；null 输入保持 null。 |
| `lq.a(LlR;Loj;[JI)[D` | 同文件 91 行 | 对决策节点做完整范围递归，按父街、父 actor 和 bucket mapper 分支。 |
| `lq.a(LlU;Loj;[JI)[D` | 同文件 75 行 | 对一般子节点/叶的额外重载；本批执行的是上面的决策节点重载，不把叶重载也计为已动态覆盖。 |
| `mg.f(I)[D` | `0037/mg.java:13` | 固定子树根显式返回该玩家的 1326 初始范围 clone。 |

注意 `lq` 的 blocker 是分支局部的：若目标玩家刚在父节点行动，某分支乘法使用父街 board，未必立即排除新街牌。真实训练的 `lw` 固定 board factory 随后会对全部座位再次清除完整固定 board。独立提取器把这一步作为最终 conditioning 显式执行。原探针也在原递归输出之后调用原 `lq.b`，因此比较的是实际传给 fixed-board 发牌模型的权重，而不是声称每个原 `lq` 中间数组均已应用最新 board。

数学上每个玩家的数组为 `initial_weight_i(hand) × ∏ 该玩家沿路径的行动概率`，随后施加全部已知 board blockers。它是个人 reach 因子，**不是**给定其他玩家范围后的单手牌边缘概率。牌张排斥和弃牌玩家 bunching 由联合机会抽样处理，不能在这里按座位归一化或提前删去 inactive 玩家。

## 二、原 wizard 的边界和量化

原 `kp` constructor（`0056/kp.java:36`）只保留 `action.street < selected_node.street` 的序列，再重放得到新街起始筹码状态；`kp.a()JsonObject`（95 行）生成：

```json
{
  "subtree": {
    "street": 1,
    "board": "As9c7h",
    "sequence": [{"player": 0, "type": "R", "amount": 20000, "street": 0}],
    "players": {"0": {"active": true, "range": "AsKs:0.25"}}
  }
}
```

`ac.a(Ljava/util/List;)Lcom/google/gson/JsonArray;`（`0136/ac.java:237`）按 `player/type/amount/street` 序列化行动，类型为 F/X/C/R；amount 是原内部整数筹码单位。`lt.a([J)String`（`0709/lt.java:153`）输出各街新增牌，flop 内由高牌索引到低牌索引，随后保持 turn/river 次序。

active 来自 `!folded && !all_in`（`kp.java:107`），不是仅 `!folded`。全下和弃牌座位依然有 range，其死牌必须参加联合发牌。

`ko` 默认 `precision=2`（`0054/ko.java:14`），UI 允许 1..5 小数位；`kp.java:106` 先调用 `lO.a([DI)String` 导出。`lO`（`0714/lO.java:11`）删去 `<0.5×10^-precision` 的手牌，将 `>=1-0.5×10^-precision` 输出为无权重文本（即 1），其余保留固定小数位。`ko.b()I`（`0054/ko.java:108`）随后 `lQ` 回读、应用完整 board blockers，并检查**每个座位**是否为空；它没有跳过 folded/all-in。

因此，若要匹配原 wizard 默认初始化，应明确选择 `range_precision=2` 并使用 `serialized_ranges`。直接使用精确 `ranges` 是无量化扩展，可能保留原 UI 丢弃的稀有 combo。两者均由模块返回，不隐藏这种差异。8 个原文本/解析探针包含原 UI 全部 1..5 精度及额外边界；并非全 double 域格式化证明。原 `String.format` 可能受 locale 影响；本次原进程使用小数点，产品文本明确使用小数点。

独立产品允许裁剪任意非终局后街节点。若路径已经含所选街的行动，原 wizard 的“只保留早街序列”不能原样表达该节点筹码状态。因此本模块输出完整选择序列，同时标注 `original_wizard_compatible=False`、`selection_semantics=independent_midstreet_extension`，另附静态复原的 `original_wizard_sequence`。没有声称这种中街选择是原 wizard 起街导出的等价操作。

## 三、稳定接口与产品交接

```python
result = extract_reach(
    tree, path, board_history,
    action_probabilities,  # (node_id, edge_index) -> [probability_per_bucket]
    bucket_map,            # (street, full_history, actor) ->1326 bucket IDs
    initial_ranges=None,  # 每实际座位None/169/1326；None在这里为均匀先验
    range_precision=None,
    policy_source="explicit_callback",
)
```

tree 使用 `ImportedTree/GeneratedTree` 共同接口，path 为现有 edge-index 字符串。`action_probabilities` 应提供父节点的 display/average 行动列；不能误用 current regret policy。preflop 内部使用原顺序的 169 类映射，不调用外部 bucket_map。postflop 由父策略所属的抽象提供 1326 bucket ID，支持每座位不同的映射。

返回 `ReachExtraction`：

- `ranges`：每座位 1326 精确权重，保留 folded/all-in；`active`：仅是否仍能决策。
- `serialized_ranges`：经过显式 precision 格式化/回读后的权重。precision=None 使用无科学计数法的精确十进制往返，不套原 UI 截断。
- `zero_mass_seats`、`serialized_zero_mass_seats`：分别报告原始/量化后无正质量的座位。任何实际座位为空都无法创建合法联合死牌分布；训练应拒绝，不能删座位或替换均匀。所有座位单独非空**不保证**联合可发，交叠造成的联合不可能由 chance 的显式拒绝预算检测。
- `initial_state`：源节点剩余、累计投入、当街投入、folded、pending、reopen 等状态，以及原 `initial_stacks`、BB 和 pot；GeneratedState 的 dead_money/participant_mask 同样保留。未重置投入或把剩余筹码当新初始筹码。
- `sequence`、`subtree_config`：完整历史行动与原字段形状。中街扩展标记见上一节。
- `trace`：每个真正决策边的 actor/street、前后个人权重总和、输入行动列及 bucket map 的 hash。一个 incoming edge 的 forced suffix 不额外乘概率；状态由原已验证的 action replay 提供。

节点 ID 重排、高层树裁剪、独立 checkpoint 适配和公开 API 由根任务负责。模块不把父策略复制成新节点的 regret/average 初值；即使调用方显式采用父策略来定义初始范围，新子树训练存储仍应按其独立初始化规则建立。

## 四、原始字节码探针隔离

`scripts/java/OriginalReachProbe.java` pin 主 JAR，资源访问全部拒绝，HRC allowlist 为 `lq/lR/lU/lA/ly/lz/lr/oj/oi/ls/lt/lO/lQ`。原 `lq`、`lR/lU` 默认 ancestry 方法实际执行；synthetic node adapter 只提供显式策略列、parent/children/street/actor 与根范围。无需原 `mf` storage、原游戏状态或 scheduler。

因混淆接口存在同参数不同返回类型，普通 Java Proxy 无法正确实现；ASM 9.7.1 仅生成自己的接口适配字节码，不改原 class。方法清单直接读 classfile descriptor，避免反射枚举默认方法时额外解析未使用类型。该步骤发现 `lR.a/b` 的两个未用默认方法实际参数是 `qZ`，而反编译文本显示另一泛型类型；没有扩大 allowlist 来运行这些无关接口。报告包含 ASM JAR hash、每个实际加载原 class hash和生成 adapter hash。

20 条链覆盖普通 preflop 根、已有 flop/turn/river 根、同一玩家重复行动、其他玩家行动、跨多个街、四种 board 纹理以及非均匀/零支持初始固定子树范围。普通 preflop 原根验证使用其默认全 1 先验；泛化的外部 169/1326 初始因子由独立单测验证，没有把原根自定义范围入口未经执行的部分计为原证据。

原 `lq` 决策重载、最终 blocker 和 `lO/lQ` 原文解析已经执行；`kp/ko/ac` 的 UI/config 路径仅静态分析，没有打开 wizard 或访问应用许可。源代码/输入/执行命令/hash及逐查询结果都在 JSON 报告中。复现：

```powershell
.venv/Scripts/python.exe scripts/validate-hrc-reach.py
.venv/Scripts/python.exe -m pytest tests/test_hrc_subtree_ranges.py -q
```

## 五、mode-2 完整 worker 的后续可执行边界

本批没有实现或执行 `mn` mode 2。已有独立证据覆盖 `lw` 的 skip-target 发牌原语（3 个精确场景）、v4 scalar traversal 的嵌套数值探针，以及本批祖先范围；这些组合起来仍不能自动算作完整 worker 对齐。

静态事实：`mn.a(qb,mf,lZ,BooleanSupplier,[J):mn`（`0034/mn.java:228`）取得 169 范围和活跃行动 actor 列表；非均匀活跃范围进入 mode 2。case 2（148 行）逐 target p 调用 `lw.a([I,0,p,cancel)`，target 均匀，其他范围整组拒绝；补齐 board 后调用原 scalar traversal，初始 reach weight 为 `range169[p][preflopBucket(p)]` 的原值。整个 target 循环完成后迭代计数只增 1（169 行），不能替换成 mode-1 单次 vector traversal。原实现 82 行明确拒绝 postflop root 的 mode 2。

完整 worker 入口 `mn.a(ILmc;Lmd;)V`（69 行）创建 `ForkJoinPool`、`mo` 双 barrier，使用每批 250 次预算（93 行）、`lu.a()` 工厂随机源及周期进度/取消逻辑。`mc.isFinished(J,Lmq;)Z` 与 `md.updateProgress(J)V` 都是纯接口，可以为后续构造有限批次测试；`qb` 是参数 record，但包含 `kG/mf/ok/lm`，须逐依赖审计。`mo`（`0008/mo.java`）与 `mq`（`0030/mq.java`）还需纳入计数和 flush/snapshot 检查，不能仅给一次目标调用当作 worker 测试。

可行的下一步是独立 allowlist probe：复用已审核的合成 `mf` 树、`kG`、`lV/lY`，构造 `qb` 和 169 范围；单 worker、`mc` 精确限制为一个或少量 250 次批次、显式 `BooleanSupplier` 截止、无 GUI/资源 registry。若需要逐步随机序列对照，应通过已审计的 `lu` supplier 注入固定随机源，并记录每个 target 的初始权重、raw storage、真实计数与进度计数。完整 `mn` scheduler/counter 与上述新增依赖尚未执行，当前不能宣称已完成。
