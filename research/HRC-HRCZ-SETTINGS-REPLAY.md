# `.hrcz` 设置、结果单位与保存树重放

本批实现设置/状态双向映射和已保存拓扑的独立规则重放。它不读取原存档策略、regret 或叶收益，不执行建树 JavaScript，也不以重新生成的默认树替代源树。原策略存储及 ZIP/API 集成由其他模块负责，因此本报告不单独宣称整个产品已完成双向互通。

实现入口：[`hrc_hrcz_settings.py`](../preflop_lab/hrc_hrcz_settings.py)、[`hrc_hrcz_tree.py`](../preflop_lab/hrc_hrcz_tree.py)。证据：[`hrc-original-hrcz-settings-validation.json`](../reports/hrc-original-hrcz-settings-validation.json)。

## 稳定接口

```python
config = settings_to_config(settings, state=None, chip_scale=10000)
settings = config_to_settings(config, template=None, chip_scale=None)
state = config_to_state(config, template=None, eqpre=None, eqpost=None,
                        units='archive')  # archive / scene / internal
tree = replay_archive_tree(settings, gametree_bytes, state=None, provenance=None)
tree = load_archive_tree(path)
```

`settings_to_config` 返回完整 custom-shaped 配置，`engine='hrc_custom'`；应用的导入入口可替换为 `hrc_imported`。不能通过普通 custom constructor 重建树。`chip_scale=10000` 表示应用场景的一筹码单位对应 10,000 个原内部整数，不会擅自把大盲归一化为 1。

`config.hrcz_metadata` 保留原 settings/state、原始映射投影、单位、`source_training_iterations=None` 和明确的 `unsupported`。未经编辑的映射结果返回原 JSON 对象形状，保留稀疏奖金阶梯、未知字段和脚本文本；经过编辑时只更新已支持字段。它保留语义/对象，而非 JSON 空白或 ZIP 原压缩字节；原包按字节保留属于上层归档职责。

`config_to_state` 只输出明确给出的或保存的观测值；全新导出若缺 `eqpre` 或 `eqpost` 会报错，不把筹码直接冒充求解结果。修改映射场景后若未明确提供两个新结果向量，也会拒绝复用过期 metadata.state。`units='scene'` 和 `'internal'` 对 ChipEV 做相应转换；奖金/赏金金额不转换。应用座位昵称没有原 handdata 对应字段，导入按座位生成显示名。

`ArchiveTree` 继承 `ImportedTree`，可使用 `get_node`、`node_path`、`describe_node`、`compact_export` 和 `dataclasses.asdict`。`nodes/states` 始终按 ID 索引；`record_order` 另保留文件实际记录顺序。读取源物理记录顺序无须等同 ID 顺序或父节点先出现。`archive_state` 保留原观察结果。

`compact_export().terminals` 在既有 `remaining/contributions/folded/live` 上增加 `dead_money`、`street`、`raise_count`、`participant_mask`、`street_contributions`；初始筹码仍是整手开始筹码。BB ante 的独立公共池不塞进 BB 的个人投入，因此已经因 ante 全下且个人投入为 0 的玩家仍可参与该池。

训练端须检查 **`tree.validation.unsupported`** 或调用 `tree.require_trainable()`。脚本/未知建树策略是 `scope='rebuild'`：保存树仍可重放。未知收益模型、资源 profile、尚未接线的保存后街子树和大于 16 个行动的决策是 `scope='training'`：可以查看，不能静默替换为默认模型继续训练。已知 profile 也仍须在训练启动时核验本地资源存在及 hash。

## 已核实的原格式与单位

| 原字段 | 实际含义与映射 | 原证据 |
|---|---|---|
| `handdata.stacks/blinds` | 原内部整数；`blinds=[BB,SB,ante]`，映射时除 `chip_scale` | `kJ`/现有原规则逐步数值对照；独立重放调用已审计 `_Builder.initial/apply/advance` |
| `eqmodel.id` | `chipev`、`icm`、`mtticm`、`fgs`；原 MTT 名称是 **mtticm** | [jD.java:66](../analysis/hrc-deep/sources/0075/jD.java:66)、[kS.java:6](../analysis/hrc-deep/sources/0904/kS.java:6) |
| `structure.prizes` | key 开始一个奖金台阶；每个名次查 `floorEntry`，不插值。末 key 为零则长度为末 key−1；因此数组中可保留尾零 | `oL.getPaidSpots()I` [214](../analysis/hrc-deep/sources/0750/oL.java:214)，`oL.createStructure()[D` [238](../analysis/hrc-deep/sources/0750/oL.java:238) |
| `structure.bounty` | 固定 KO 全场相同赏金；非 PKO 且金额大于 0 时实际启用 KO，不只按 type 名称猜测 | [kR.java:21](../analysis/hrc-deep/sources/0902/kR.java:21)、[kS.java:16](../analysis/hrc-deep/sources/0904/kS.java:16) |
| PKO | 本桌 `handdata.bounties`；`structure.progressiveFactor` 是立即支付比例；外桌仅 `otheravgbounty` | [kR.java:25](../analysis/hrc-deep/sources/0902/kR.java:25)、[kS.java:20](../analysis/hrc-deep/sources/0904/kS.java:20)，既有 bounty 数值探针 |
| `eqmodel.otherstacks` | **原 GUI 筹码，即内部筹码 /100**。import 乘 100 再除 scene scale；export 做逆变换 | [jE.java:232](../analysis/hrc-deep/sources/0071/jE.java:232)、[jE.java:303](../analysis/hrc-deep/sources/0071/jE.java:303)、`li.b(kG)[D` [16](../analysis/hrc-deep/sources/0929/li.java:16) 将本桌经 kF 转换后与外桌一起送入 lg |
| ChipEV `state.eqpre/eqpost` | 绝对筹码权益，内部筹码 /100；不是净 BB，也不是训练次数 | `kF.a([J)[D` [4](../analysis/hrc-deep/sources/0925/kF.java:4)、`kD.a(kG)[D` [5](../analysis/hrc-deep/sources/0923/kD.java:5)、[bM.java:76](../analysis/hrc-deep/sources/0393/bM.java:76)，本机真实 state |
| Monetary state | 绝对奖金/赏金权益，原货币单位不缩放 | 既有 ICM/MTT/KO/PKO/FGS 数值证据及真实 PKO state；不是 GUI 百分比 |
| rake | `raked` 开关、`rakepct` 比例、`rakecap` 内部整数；`nfnd` 优先，其次 `raketype_ggnetwork`，否则 Full | [jx.java:63](../analysis/hrc-deep/sources/0065/jx.java:63)、[kO.java:32](../analysis/hrc-deep/sources/0901/kO.java:32) |
| FGS | `eqmodel.id='fgs'`，`depth`、`depth3way` 默认 1，`nextlevel={atdepth,tolevel:[BB,SB,ante]}`；未来盲注仍为内部整数 | [kP.java:14](../analysis/hrc-deep/sources/0903/kP.java:14)、[kP.java:64](../analysis/hrc-deep/sources/0903/kP.java:64) |

外桌 PKO 的应用数组在导出时变成平均值，保留原模型使用的外桌总赏金池；个别外桌玩家的赏金身份不在原格式中。静态额外信息仍可放上层自身 metadata，但不能说 HRC 原格式保留了这些身份。

## 拓扑重放和规则检查

`_Rules` 仅绑定已审计的规则函数，未初始化 policy，也未调用 `build/children/sizings/normalize/next_street`。每条 incoming action 都检查行动者、街、类型、金额和 all-in 位。跨街只允许在当前轮结束后发生；源 child 的第一个行动必须属于父 decision。

原 lB 对短有效筹码存在“先按有效上限夹紧候选，再应用最小加注，先检查自己的全下”的可观察行为，可能留下未跟注余量；重放通过同一已独立验证规则重新生成这个行动，然后与保存的金额和 all-in 位精确比较，没有按常见扑克规则擅自修正。

每个节点检查总筹码和逐座位筹码守恒，逐座位核算单独归属 BB 的 ante pool。终局检查本轮行动已结束、正个人投入层至少有活跃合资格玩家。保存策略选择提前 checkdown 的未来街不会被补成默认树，另以 `saved_early_checkdown_terminals` 计数。

subtree 的 `sequence` 可以在保存根的 incoming path 之外，也可以完整出现在根 path 中；后者仅在序列精确相等时避免重复应用。两个边界有合成测试，仍缺真实原版导出子树整包的互通证明，因此当前标记为不可训练，而不宣称完整后街导入已完成。

## 验证结果与边界

- **11 个真实原存档：56,803 节点、59,327 个行动全部重放通过**，包括 HU 10BB、九人 10/20BB、八人 15BB 及 PKO。未编辑 settings/state 对象往返精确一致。
- **93 项 pytest 通过**：上述真实档案；2–10 人三种 ante；四种 straddle × skip/moving 组合；不等筹码、BB ante 吃尽筹码、短全下；物理记录反序；损坏金额/行动者/all-in 位/未完成终局拒绝；脚本绝不执行；稀疏奖金、rake、FGS、MTT 单位、未知资源门控、两种 subtree 前缀形状、修改场景后拒绝复用过期结果。
- 原始 `oL` 的 **10 个奖金台阶**（含空结构、同奖、尾零、1,000 名次）与独立展开完全一致；`kF` **10 个整数筹码转换值**完全一致。探针只允许 oL/oM/kF 和 hash 固定的 Gson 验证依赖，平台 parent loader，拒绝资源读取，未加载应用或求解器。
- 变体树重放测试使用独立 builder 生成的拓扑，证明序列化/重放一致性，不把它误算为新增的原版 GUI 存档对照。原始规则自身的数值依据在 [HRC-TREE-BUILDER.md](HRC-TREE-BUILDER.md) 及既有报告。
- 未在本批验证原版 GUI 对新导出 ZIP 的打开结果，也未在本批验证存储格式 warm start、训练继续计数或收敛；由 ZIP/storage/GUI 集成任务提供后续证据。

复现：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_hrc_hrcz_settings.py tests/test_hrc_hrcz_tree.py -q
.venv/Scripts/python.exe scripts/validate-hrc-hrcz-settings.py
```

探针及输入生成器位于 scripts，删除 analysis 后也能重新生成数值输入；真实 `.hrcz` 仍需由用户本地档案提供。
