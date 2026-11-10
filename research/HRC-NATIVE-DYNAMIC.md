# 固定公共牌 mode1 原生训练接线

本批把已经分别验证的加权发牌、动态映射和遍历数值模块接进生产训练循环，支持从固定 flop、turn 或
river 根开始训练。原始 HRC 求解器没有被调用，存档策略与原始叶估值没有进入初始存储。
独立 kernel 从零更新，支持现有25/27/31后街存储、策略锁、频率约束及断点恢复。

## 输入与实际执行

`compact.chance`：

```json
{
  "version": 1,
  "mode": 1,
  "board_history": [0, 1057],
  "ranges": [null, null],
  "max_attempts": 1000000,
  "max_random_calls": 10000000
}
```

示例mask只是三个牌ID的集合；真实输入必须按0、三张flop、加一张turn、再加一张river保留累计历史。
固定历史的最后一街必须等于子树根街，不允许在更早行动节点暗中固定后续发出的牌。
每个实际座位有一行范围，null表示均匀，非null必须是1326个有限非负组合权重。
组合编号为 `high*(high-1)/2+low`，牌ID为 `rank*4+suit`。范围即使属于已fold玩家也保留并参与死牌发牌。

`compact.dynamic` 使用逐街可移植资源描述：

```json
{
  "version": 1,
  "tables": [{
    "street": 1,
    "file": "flop.bin",
    "sha256": "资源文件的64位小写十六进制SHA256",
    "bytes": 12345,
    "effective_counts": [100, 120]
  }]
}
```

file必须为ASCII单文件名，不能有路径分隔符。资源从运行参数 `resource_dir` 读取；移动目录不改变树身份。
Python预检所有文件的大小和SHA，原生程序再独立流式计算SHA256、检查二进制内部尺寸、street、players、
有效桶数及固定牌面前缀。Table.prefix可以是chance历史的较短前缀：例如固定flop压缩的资源表仍可用于turn根。
每个决策节点必须具备相应街表，并满足 `node.buckets == table.effective(node.actor) > 0`。
有0桶的inactive玩家可被发死牌，但不能行动。任何缺街或桶不匹配直接拒绝。

`Engine::deal` 先采样受范围约束的整副私牌，冲突时整组重抽；再补均匀座位和未知公共牌。
只有完整deal成功才推进内部牌局epoch。`Engine::hand` 每街首次访问批量填充各座位桶，并按节点actor选择。
普通终局继续用独立七牌评估与已有筹码/权益结算。范围改变影响实际发牌，动态映射改变实际存储索引，
并非在展示时替换概率。

原加权发牌语义与范围CDF端点依 `reports/hrc-original-chance-validation.json` 的152例有限证据；
动态表及资源表依据 `reports/hrc-original-dynamic-native-validation.json`、
`reports/hrc-original-resource-dynamic-validation.json`。具体原类和方法证据见
[HRC-DYNAMIC-ABSTRACTION.md](HRC-DYNAMIC-ABSTRACTION.md)。

## 协议、预算与恢复

HRTREE04的flag128在rake段（如有）之后追加：

```text
mode:u32 (=1), prefix_count:u32 (2..4), max_attempts:u64, max_random_calls:u64
board_history[prefix_count]:u64
for each player:
  count:u32 (0 or 1326), weights[count]:f64
table_count:u32 (0..3)
for each table:
  street:u32
  file_length:u32, file[file_length]:ASCII
  sha_length:u32 (=64), sha[sha_length]:ASCII
  file_bytes:u64, effective_counts[players]:u32
```

`max_attempts`与`max_random_calls`各为1..1,000,000,000，分别限制整组范围拒绝和每次deal随机调用。
动态桶数上限为int32正数；实际内存预算会先于巨大数组分配触发，不能靠桶数上限放任分配。
`run(..., max_memory_bytes=1<<30)`可设1MiB至4GiB；CLI对应最后可选参数argv13，前面仍为
resume、reset_regret、reset_average、stop_after_seconds、target_ci、hard_seconds。
运行预算不进入compact和identity，因此恢复时可更换预算。

估算包括节点/边/终局对象与pot容量、原始数组、visits、锁定数组、频率扩展、CI快照及表加载临时内存；
动态资源按文件大小的2倍保守记账。固定全局抽象资源也计入其数组和board索引开销。
`started`及最终summary记录estimated_memory_bytes。该值不是操作系统RSS上限；线程、运行库和FGS递归缓存
有额外开销，FGS仍受其自己的状态/扫次/时间/缓存预算约束。

采样预算失败返回resource_limit并保留最近完整检查点，不将部分消耗的RNG状态另存为完成结果。
在采样中取消或触发秒数目标时回退至最近完整检查点，结果明确包含
`rolled_back_to_checkpoint:true, partial_iteration_saved:false`。因检查点每百万次保存，进度事件
可能高于最后可恢复迭代数；结果以检查点迭代数为准。

HRSOLV03无需改版：已有四个RNG状态字、全部存储、visits和实际累加器足够保存新mode1路径。
本批format25/27/31都实际验证连续1000次与400次保存后续跑至1000次的整个checkpoint逐字节相等，
恢复传入不同seed不会替换保存的RNG状态。

查询大节点可调用 `read_node(..., bucket_ids=[...])`，只读取指定桶的visits与存储行以及共享头，
不会展开整节点的百万行Python字典。返回bucket_selection和hands_complete；旧默认仍返回完整节点。
锁定与频率约束也在稀疏读取中按原数值语义应用。

## 有限验证与未证明范围

运行 `scripts/validate-hrc-native-dynamic.py` 保留42项生产测试、源文件哈希、构建信息和上游证据摘要。
输出是 `reports/hrc-native-dynamic-validation.json`，原始pytest输出和XML位于
`analysis/hrc-deep/native-dynamic/`。

- 固定flop/turn/river，真实独立strict表与显式合成寻址表，逐actor/逐street读取。
- 50副牌逐例核对完整公共牌前缀、所有座位无冲突、folded座位死牌和净筹码守恒。
- 4,000次两座位加权碰撞样本，对可行联合组合的理论质量3:2:1作统计检查。
- 20,000桶实际训练并检查第19,999桶被写入；int32最大桶在1MiB预算下分配前失败。
- 文件hash/长度/prefix/effective、路径、缺街、范围预算、取消、秒数目标和断点恢复。
- 25/27/31、锁定及频率约束下的稀疏读取与完整解码逐行相同。
- SHA256独立流式实现与Python hashlib对空文件、填充边界及100,000字节样本逐项相等。

合成寻址表仅用来隔离接线错误，不被描述为真实牌力抽象。加权联合分布检查属于抽样统计证据。
原chance模块和抽象表分别有原字节码对照；本批没有宣称运行完整原始worker取得相同随机序列。
mode2按目标玩家均匀发牌、169原始范围reach-weight的worker仍未接入；输入mode2明确拒绝。
本批也不证明多线程刷新时序、全产品行为或多人博弈均衡收敛。
