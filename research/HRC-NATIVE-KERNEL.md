# 独立 native v4 内核：范围、接口与验证

本内核把已恢复的 HRC `mf/lV/mE/mA/mv` 数学操作重新实现为 C++。训练不调用 HRC 求解器，不载入原版保存的遗憾、平均策略或终局效用。全体节点和桶的存储从零开始，终局收益由独立七牌评估与逐边重放的筹码状态计算。

结构输入可使用独立 `hrc_tree_builder.py` 生成的四街树，也可显式导入原版存档的 `settings.json/gametree.dat` 供同树对比。翻后桶分配读取本机安装中的三个指定 abstraction 资源；没有声称重新训练出这些桶。独立树生成器的已验证范围见 `HRC-TREE-BUILDER.md`。

本报告保留初始数值内核与吞吐证据。后续已接入 ICM/MTT、KO/PKO、FGS、逐桶锁、频率约束、CI、27/31存储和显式模式迁移；当前控制/检查点协议及限制见 `HRC-NATIVE-CONTROLS.md`，各数学模块的原字节码验证见对应报告。

## 实现与边界

- [native/hrc_research_solver.cpp](D:/Users/Shao/Documents/ChatGPT/REA/native/hrc_research_solver.cpp)：实际发牌、向量/标量遍历、探索、v4 跳过、更新、终局、检查点。
- [preflop_lab/hrc_native.py](D:/Users/Shao/Documents/ChatGPT/REA/preflop_lab/hrc_native.py)：编译、输入导出、进度/取消、检查点和单节点懒读取。
- [tests/test_hrc_kernel.py](D:/Users/Shao/Documents/ChatGPT/REA/tests/test_hrc_kernel.py)：原始字节码数值对照与执行控制验证。

每轮均匀无放回发出全部玩家底牌和五张公共牌，之后桶和牌力按实际访问懒计算。向量递归沿选中行动返回玩家收益向量，并对其他行动做目标玩家标量递归；标量目标节点以 `1/(d+2)` 概率跳过更新，只沿选中行动继续并增加 d。探索率为 `1/sqrt(cachedNodeCounter+10000)`。特殊 CHECK 分支和其 1% 向量访问按 `mf` 分支实现。具体 descriptor/BCI 依据见 [原核心报告](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-SOLVER-CORE.md)。

翻前使用格式 23 对应的逐桶遗憾、分母与平均累计量。`mE` 的局部 t 先取缓存计数+1；触发有符号 `nextInt()%floor(sqrt(t))==0` 时，以已递增的实际节点计数替换局部 t 并刷新缓存。平均累积 `t*p` 不乘 w，不使用 z。非翻前使用格式 25 对应的逐桶遗憾和跨桶共享平均，平均仅在 z>0 时更新 `t*z*p`。

**显示语义单独保留**：格式 23 的 `display_strategy` 为每桶平均累计归一化，格式 25 为每桶当前正遗憾归一化；格式 25 的 `global_average` 单独输出，不能冒充每桶平均。格式 23 的 EV 为 `(R[a]-R[0])/D`，单位是净 BB 的相对差值；没有访问的桶标记 `trained=false`，没有伪造求解覆盖。

训练 raw 数组使用 double，与原运行时 `double[]` 一致。原版存档通常压为 float32，本检查点保留 double，因而不模仿保存/重载造成的量化。实际节点/桶更新计数为 uint64。自检覆盖 60,000,001 次的 t 值与 double 更新，没有 float32 计数停滞。

终局保留内部整数筹码单位。相邻贡献层若有相同赢家集合，先合池再整数均分；余数全部给赢家中贡献最低、同贡献时座位最高者。最后转换成相对初始筹码的净 BB。这避免逐个死钱阈值舍入或简单浮点平均造成的差异。

内核当前是确定性的单线程执行，随机源为自行实现的 Xoshiro256**、SplitMix64 种子和无偏有界整数拒绝采样。它不复刻 Commons RNG 的逐字节流、HRC 多线程交错、CI/界面刷新写回缓存的墙钟时序。因此采用相同 seed 并不产生原版相同样本序列，也不保证有限样本策略逐项相同。没有为九人博弈声称 Nash 收敛或 exploitability 保证。

## 调用与持久化

```python
from preflop_lab.hrc_native import build, prepare, run, read_node

result = run(
    "analysis/hrc-desktop/nine20bb-raise-call-postflop-initial.hrcz",
    ".research-cache/abstractions",
    samples=60_000_000,
    seed=42,
    output_dir="analysis/hrc-native/my-run",
    progress_callback=lambda event: print(event),
    cancel_check=lambda: False,
)
root = read_node("analysis/hrc-native/my-run", 0)
```

`samples` 是累计发牌硬上限，现允许 0–1,000m；可另设时间或CI目标。用 `resume_from=.../checkpoint.bin` 可续跑同一结构、同一模式。检查点包含 RNG 状态、raw double、实际节点/桶计数和在线收益累积。独立测试证明 750→2000 的续跑与一次跑到 2000 的二进制检查点逐字节相同，即使续跑传入不同 seed 也由保存 RNG 状态继续。策略/存储变化需按 `HRC-NATIVE-CONTROLS.md` 显式迁移，不能忽略身份检查。

native 每 250 个样本检查取消标记，每约 0.5 秒输出进度，每 1m 保存一次检查点；取消也保存部分结果。Python 启动器每 0.1 秒检查取消回调。`index.json` 提供每节点 offsets，`read_node` 不必加载全部训练存储。

`root_mean_net_bb` 是训练期间变化中的探索策略的在线回报，不是对最终平均策略做独立评估。应用只把经过语义说明的逐桶相对 EV 用于原档比较。

构建优先使用已校验的 portable Zig 0.15.2，`-O3 -std=c++17 -ffp-contract=off`；本机 MSVC 工具虽然存在，但缺 Windows SDK/UCRT，不能单独完成构建。启动器不会自行联网安装依赖。

## 已完成的检验

`tests/test_hrc_kernel.py` 30/30 通过，其中 18 项把 native 归一化或数组更新直接与已执行原始字节码探针的 JSON 结果比较。其余涵盖缓存计数不刷新/后续刷新、60m double、v3/v4 固定 RNG 跳过分支、整数平局合池、取消与检查点精确续跑。固定 RNG 输出和编译/文件哈希见 [kernel-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-native/kernel-validation.json) 与 [fixed-rng-probes.jsonl](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-native/fixed-rng-probes.jsonl)。

卡牌模块独立验证包括 30,008 个七牌案例与 PHEvaluator 的胜负/平局比较，三个街共 5,400 个桶样本与 Python/原 `ol` 对照、全部 1326 组合类别和 3000 个 canonical board；见 [卡牌验证](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/independent-native-cards-validation.json)。

九人 20BB 同一棵树（12,193 节点，5,322 决策节点）从零跑 10,000 次，纯训练约 0.0552 秒，约 181k 次/秒；加末尾检查点为 0.245 秒，启动/加载总约 1.35 秒。全街实际更新数量为翻前 91,062、flop 706、turn 450、river 285，根更新 10,000，各桶真实更新数之和为 10,000；九人净在线收益之和误差 `7.6e-17`。这些是短测的吞吐和连通性证据，不能把它们当作 60m 长跑成绩或原版策略一致性的结论。长跑与保存档对比由单独报告记录。
