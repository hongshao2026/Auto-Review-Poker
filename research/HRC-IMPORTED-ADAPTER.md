# 原存档策略导入与独立续算适配器

实现：[`preflop_lab/hrc_imported.py`](../preflop_lab/hrc_imported.py)。测试：[`tests/test_hrc_imported.py`](../tests/test_hrc_imported.py)，12 项通过。

`HRCImportedSolver(config, source=None)` 使用 root 的 `SourceArchive/load_source`，来源是 SHA-256 身份固定的本地缓存。`config_for_source(source)` 产生完整映射配置；构造器也接受只包含 `engine='hrc_imported'`、`source_sha256` 和运行控制的配置。玩家/筹码/树/收益模型、源存储与策略约束不可被编辑覆盖，只允许 iterations、seed、solver_mode、CI 和时间/内存预算等运行控制变化。

树直接来自 `source.tree`，没有调用 custom builder，也没有挂载匹配对照 reference。源决策数据由 storage codec 转换为本机原生状态；源叶收益向量不进入训练。`compact_override` 已包含实际树、monetary equity、FGS、rake、原存储配置、锁定/频率目标和 `import_provenance`，上层通过 `solver_compact` 取得这个完整输入。

## 生命周期与基线

1. 构造：加载和映射源；组合设置/资源 profile 和存储格式的训练门控；独立 Python 对非 FGS 初始收益做快速校验。失败时仍允许只读策略查看，`training_supported=False`。
2. `initialize_checkpoint(output_dir)`：核验资源；使用生产原生收益引擎的 baseline-only helper 计算基线；与 `state.eqpre` 比对；通过后调用 `records_to_checkpoint` 并保存树 snapshot、index、import history、baseline validation；设置 `output/index/resume_from`。它不执行一轮训练，不枚举原叶收益。
3. `run(total_new_samples)`：从转换后的或续跑后的 checkpoint 继续至指定的累计新增样本数，使用独立随机流和实际收益计算。运行完成后再核验 native index 的基线，更新 `resume_from`，输出应用结果。
4. `build_result()`：无须训练也能持久化导入结果；保留 source state 和未知原历史。原文件重导出/ZIP 及应用 job 恢复由上层负责。

ChipEV 的 affine 转换为 `archive_absolute = native_net_bb × (BB_internal/100) + initial_stack_internal/100`。monetary 的 scale 为 1，offset 是经过独立验证的源 `eqpre`。外桌 MTT 筹码已经由 settings mapper 从原 GUI 单位转换为 native 与本桌相同的内部筹码单位。

基线允许误差为 `1e-7 + 1e-8 × |source|`；验证结果明确记录源值、独立值、绝对误差、方法和通过状态。FGS 使用真实递归基线而不是普通 ICM 替代；其预算或资源失败不会自动当成通过。

## 显示与计数

输出未建立 native checkpoint 时直接使用已审计原存档 decoder 显示策略：`visits=None`、`new_visits=0`、`saved_counter_float32` 单列。`has_saved_policy` 依据有效 denominator/regret/average 或已保存锁定数据识别，不通过虚构访问次数让 UI 显示策略。

建立 checkpoint 后原节点累计时钟继续保留，新 per-bucket visits 从 0 开始。展示 `visits/new_visits` 是新增访问次数，`storage_update_counter` 是保留旧时钟后的当前节点计数；即使新增 visits 为 0，仍保留 `has_saved_policy`。原全局迭代数、原逐桶 visits、原 RNG 始终标记未知。

`summary.hrcz_import` 给前端提供 `source_saved_counter`、`source_iterations_known:false`、`history_unknown:true`、`training_supported` 与 `unsupported`。不会把源节点累计时钟当成原全局样本数，也不会宣称本机续跑逐位复现原多线程执行。

## 实测

- 真实 HU 10m 源：节点时钟是 **20,000,500**，但未据此推断原全局样本。未训练时 169 手牌的显示策略与相对 EV 在 native 转换前后保持一致。
- 继续至 **100** 个新增样本：根新增 visits=100、节点累计时钟=20,000,600；继续至 **200** 个累计新增样本：visits=200、累计时钟=20,000,700。源计数继续为 null。
- 真实八人 PKO：源基线每人 **22.5**，独立 Python 模型差异约 `7.1e-15`；EV 保持金额单位。baseline-only helper 的生产 native 对照也由 leaf-helper 任务独立确认。
- 原时钟/策略来源标签、不可变场景、运行控制、篡改 eqpre、未知 profile、未知存储格式均有测试。未知格式保留只读诊断，不伪造频率。

测试没有进行长时间训练、收敛评估、原 GUI 重新打开或整个 archive/job 恢复循环；这些结果不替代 root 的端到端互通验证。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_hrc_imported.py -q
```
