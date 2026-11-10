# Full Tree / Selected Subtree 的原生采样与运行时 CI

本批实现 `native/hrc_scope.hpp`，接入 `Engine.step/reset/start_ci` 与共享策略线程池。
选择子树只改变运行范围，保留原整树节点编号、策略数组、终局状态与 checkpoint 身份。
不裁剪存档、不把联合条件向量采样冒充原版模式 2。

## 原始依据与权重含义

本机 HRC4 主 JAR SHA256 为
`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。
证据路径均相对 `analysis/hrc-deep/sources/`：

* `0003/lU.java:14`，`f(I)[D`，从父节点递归提取每玩家 169 类到达范围。
* `0004/lR.java:72`，`a(Lnet/holdemresources/internal/lU;I)[D`，只乘该玩家在前序节点的行动概率。
* `0013/mf.java:189`，`b(I)[D`，通过 store 的展示概率逐桶取 action；不是训练 regret strategy，也不混入 epsilon 探索。
* `0034/mn.java:228`，静态 `a(Lqb;Lmf;LlZ;Ljava/util/function/BooleanSupplier;[J)Lmn;`，收集子树全部会行动的座位、冻结前序范围，按活跃座位是否均匀选择 mode1/2。
* `0034/mn.java:120–168`，worker `a(ILmc;Lmd;)V` 内的 mode1/mode2 分支：mode2 对每个 target 单独发牌并标量遍历，完成全部 target 才增加成功计数。
* `0707/lw.java:89–170`，`a([I)Z` 检查目标座位的 sampler 是否全 null；`a([IJILjava/util/function/BooleanSupplier;)J` 排除 target 的范围，其他加权座位牌冲突则整组重抽，然后均匀补齐 target/null 座位。
* `0029/lV.java:18`，context 的 double `a` 默认 1；`0013/mf.java:62–85` 的标量调用 `(LlV;IIDI)D` 最终传给 store `w=contextWeight=1,z=marker*contextWeight`。完整 JVM 包前缀为 `net/holdemresources/internal/`。

严格实现顺序：

```
reach[p][hand] = product(prefix display probabilities for seat p)
targets = distinct actors in selected subtree, in original DFS order
if selected node is the full root: mode0
else if all targets have constant positive reach: mode1
else: mode2

mode1:
  sample all seats from frozen reach, joint collision rejection
  fill missing board
  vector(selected)

mode2:
  for target in targets:
    sample others from frozen reach, whole-assignment collision rejection
    uniformly fill target and any other uniform seats
    fill board
    scalar(selected, target, depth=0, marker=reach[target][class])
  successful_outer_cycles += 1
```

**marker 是 z，不能改成遗憾权重 w。** 普通 mE 的 R/D/bucketA 不乘 z；自身前序概率为 0 的手仍可获得反事实更新。
支持 shared average 的后街 store、frequency store 才按其已审计公式使用 z。
所有真实座位均发牌，包括已弃牌玩家，故其前序 fold 范围继续产生 card removal / bunching。
不得逐座位按已抽牌条件重新归一范围，也不得把 target 自身范围重复乘入发牌提案与 w。

## 冻结、边界与线程

前序 display 在 `resume` 后、任何 reset 前只读快照；不调用 `flush/choose/sample`。
仅选中节点及其后代允许 reset/update；CI 从选中节点开始同街剪枝，故不会 flush 前序或兄弟分支。
节点所有 raw、visits、updates、shared/frequency 状态仍按旧格式完整保存。
子树外共享 DAG 后代会破坏冻结承诺，因此显式拒绝；常规树不受影响。

仅支持 preflop 决策点；终局、翻后点、无效路径或固定牌面/范围树与本运行范围的组合明确拒绝。
单座位零范围直接拒绝；非均匀范围做最多一百万步精确支持搜索，完成搜索后才断言“无合法联合发牌”。
搜索超预算报告“可达性未知/资源预算”，不假称不可达。机会采样继续使用独立 `hrc_chance` 的一百万重抽、千万随机调用预算与取消回调，
超预算不替换成有偏发牌，失败的部分遍历不写入检查点。

每线程私有 RNG、deal、终局缓存共享同一不可变 reach/scope；训练数组继续按节点锁同步。
`ParallelTrainer.run` 按各 worker 实际完成的 outer cycles 汇总，取消或异常不能用预约任务数伪造成功样本。
多线程调度不保证相同随机种子得到逐字节相同轨迹；单线程同 scope 分段续跑已验证 bit exact。

## 协议、计数与统计

CLI 在原 argv15 `constant_scalar_shortcuts` 后追加：

| 参数 | 含义 |
|---|---|
| argv16 | `-` 表示 Full Tree；否则描述符路径 |
| argv17 | runtime CI：`-1` 保留输入 flag，`0/1` 覆盖；不改变树 identity |
| argv18 | root mean validity：`-1` 自动读取原 index，`0` 无效，`1` 仅在原先有效时继续有效 |

描述符 `HRSCOPE1`（8 bytes）+ `edge_count:uint32` + `edges:uint32[]`，little endian，最多 256 边。
选中 root 的空路径使用 mode0，不额外消耗随机数。无描述符的 Full Tree 保留原随机调用与 checkpoint bytes。

progress/index/finished 新字段：

* `sampling_scope`, `sampling_root_node_id`, `sampling_mode`；Selected 另含 path、DFS targets、`prefix_reach_sha256`。
* `scope_effective_samples`：本次启动成功完成的 outer cycles，mode2 包含全部 target 后才加一。
* `sampling_deals`：本次实际发牌次数；mode2 通常为 cycles × targets 数。
* `sampling_attempts`：这些发牌中 weighted joint assignments 的尝试总数；均匀补牌的冲突重抽不计入该数。
* `sampling_counter_scope='current_invocation'`；checkpoint `samples` 仍为跨历史成功 outer cycles 总数，因此不能把跨 FullTree/Selected 的总数当作同一统计实验。
* `root_mean_valid`：任何 Selected 运行均置 false。`root_mean_net_bb/payout` 输出 null，后续切回 Full Tree 继续 false，避免混合分母污染。旧 root_sum 保留，但不再当全局 EV 展示；本批没有重建独立全局评估器。

`root_mean_valid` 依靠 index sidecar 和 argv18 跨运行携带；HRSOLV03 二进制未增加字段。
单独脱离 index/归档的裸 legacy checkpoint 不包含这一历史信息，调用方不得据此猜造有效全局 EV。

## CI 一致性与范围

`native/hrc_ci.hpp` 公式未修改，仍是近期展示策略漂移，不是置信区间/EV 误差/exploitability。
保留原 `mq` 216 快照探针对照，当前 header SHA 与原报告一致，最大数值误差 `5.684341886080802e-14`。
每个新 worker/run 重启 CI，先快照再等待至少 15 秒；只计算 selected root 开始、原同街 capability 筛选后的节点。
内存预算改为配置 scope 后按实际 CI 节点预留三份快照，避免把全部四街节点都当作 CI 保留数组。
生产快照仍在并行 batch barrier 后取，原 Java 是并发快照；墙钟和调度差异不等于公式差异。

CI JSON 新增 target、原 `-1.7` progress、root_node_id。
ETA 仅在至少两条有效历史且 progress 在 (0,1) 时以当前 CI 进度外推；
`eta_method='recent_ci_power_progress_not_error_bound'` 明示这是估计，尚无有效历史则 null。
停止采用原严格 `ci < target`；命中 sample/time 安全上限不能标为 CI target 达成。

## 动态对照与测试

`scripts/validate-hrc-native-scope.py` 比较实际独立 `SamplingScope+Engine.step` 与隔离加载的原：
`lU/lR` 范围提取、`lw/lu` 发牌、`lX/lY` context、`mf` 标量/向量遍历、`mE` 存储。
包含 mode1/mode2、v3/v4、seed42/43，各16轮，非均匀前序及 AA 零 reach。
**128 快照、324864 个 raw 数值、每轮底牌/board/RNG 调用/updates 全相同，最大误差 0。**
原 `mn` dispatch 根据已审计字节码显式组装，未运行原 mn/job/GUI；终局是声明的合成常数，
这不是一次原桌面完整真实树训练的性能/策略收敛对照。资源加载白名单、JAR/类/源码 hash、命令与完整输出保留在：

* `reports/hrc-original-native-scope-validation.json`
* `analysis/hrc-deep/sampling-scope/`

`tests/test_hrc_native_scope.py` 验证生产命令路径：mode2 零 reach 反事实更新、三线程准确计数、
子树外 bytes 冻结（含 CI/reset）、单线程 200→600 与直接600相同、切回整树 root mean 仍 null、
非空但三座位同时 AA 的不可达联合范围、取消只保留完整边界、选中 root 不改变随机轨迹。

```powershell
.venv/Scripts/python.exe scripts/validate-hrc-native-scope.py
.venv/Scripts/python.exe -m pytest tests/test_hrc_native_scope.py tests/test_hrc_ci.py tests/test_hrc_chance.py tests/test_hrc_checkpoint.py -q
```

上述小型测试本轮 43 passed；未执行长时间 CPU 吞吐基准，以避免影响同时进行的原桌面 CI 实测。
