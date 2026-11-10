# 本地翻后 Solver

`postflop_lab` 是可编译、可修改的双人底池 NLHE 翻后求解器。Windows 程序已编译到 `bin/solver.exe`，同时提供 Python 接口和 Rust 库。运行、求解、读取策略都在本机完成。求解器使用 MIT 许可的上游 Rust 内核，本目录保留完整引擎与命令行源码、锁定的依赖和许可。[上游源码](https://github.com/ucsandman/postflop/tree/5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de) · [许可](LICENSE)

## 直接运行

从工作区根目录执行。下面先看树，再求解并保存 JSON，最后读取一个具体行动节点的策略和 EV。

```powershell
.\postflop_lab\bin\solver.exe tree --config .\postflop_lab\examples\river.json
.\postflop_lab\bin\solver.exe solve --config .\postflop_lab\examples\river.json --threads 4 --out .\river.solution.json
.\postflop_lab\bin\solver.exe query --solution .\river.solution.json --line bet:10 --ev
```

配置支持 JSON 和 TOML。`board` 给出 3 至 5 张公共牌。`oop_range` 和 `ip_range` 支持 `random`、`22+`、`A5s:0.5` 和 `AhKh` 等范围。`starting_pot` 是节点已经在底池中的筹码，`effective_stack` 是每方还能投入的上限。两项使用同一筹码单位。

常规配置可按玩家、街道和情境设 `sizings`。也可给出 `betting_lines` 精确描述每条下注线。数组中的数值是从求解起点累计投入的筹码。比如 `[[5, 5, 5, 12]]` 从转牌开始表示 OOP 下注到 5、IP 跟注、河牌 OOP 过牌、IP 再下注 7。默认生成合法的过牌、跟注、弃牌路径。节点查询的 `bet:7` 与 `raise:7` 使用**当前街的投入总额**，`allin` 代表全下。机会节点用 `Ah` 这样的牌面 token，例如 `bet:5,call,Ah,check`。`tree` 和 `query` 的 `actions` 返回下一步 token，可以直接拼接。

配置中加 `"suit_isomorphism": true` 可让训练共享花色等价的转牌与河牌分支。引擎逐一检查两方范围权重是否对交换花色保持不变。有节点锁定时使用独立子树。命令行报告共享策略存储的决策节点数，查询和 JSON 导出仍按具体发牌与实际组合展开，因此导出预算仍按完整树计算。

在 JSON 配置中加入 `"regret_floor": true` 和 `"gamma": 4`，并使用默认的 `alpha = 1.5`，即可运行 DCFR+。它将负的累计遗憾截为零，并用四次方权重平均策略。CLI 和 Python 接口都读取这些配置字段。[DCFR+ 论文](https://www.ijcai.org/proceedings/2024/0583.pdf)

单独调整 `gamma` 可以改变输出策略的平均权重，同时沿用固定 DCFR 的遗憾更新。在 100BB 宽范围翻牌基准中，`"gamma": 8` 首次达到 0.1% 半 NashConv 的检查点从第 272 轮提前到第 248 轮。CLI 的停止参数以完整 NashConv 计，该基准对应 `--target-exploitability 0.2`。

`prediction_weight` 可让下一次策略选择使用上一轮的瞬时遗憾，取值为 0 到 1，默认 0。配合 `"regret_floor": true`、`"alpha": 2.3`、`"gamma": 5` 和 `"prediction_weight": 1` 可运行论文的 PDCFR+。预测缓存按每个已分配的行动和组合占用额外 4 字节，计入 CLI 内存预算。[PDCFR+ 论文](https://arxiv.org/abs/2404.13891)

ChipEV 可试验 `"regret_startup_clip": true`。它在前 25 轮以当前底池和阻挡后对手到达质量乘 0.15 限制每次遗憾增量，接下来 50 轮用 0.35。累计遗憾和预测使用同一个截断值，节点 EV 按原来的行动值计算。该选项要求正的预测权重。

## Python 调用和 ICM

```python
import json
from pathlib import Path
from postflop_lab import Solver

solver = Solver()
spot = json.loads(Path("postflop_lab/examples/river.json").read_text())
spot["tournament"] = {
    "payouts": [500, 300, 200],
    "stacks": [20, 32, 45, 12, 8, 15],
    "seats": [0, 1],
}
print(solver.tree(spot)["actions"])
solver.solve(spot, "river-icm.json", threads=4, report_every=50)
node = solver.query("river-icm.json", "bet:10", ev=True)
print(node["actions"], node["hands"][0], node["meta"]["gain"])
```

`stacks` 是整个剩余场的筹码向量，填当前节点的身后筹码。`seats` 的两个索引依次是 OOP、IP，较短筹码应等于 `effective_stack`。求解时每个终局用 Malmuth–Harville ICM 算奖金权益，其他座位的筹码固定。CSTE 等于权益变化乘总筹码与总奖金的比值。去掉 `tournament` 可运行 ChipEV 对照。锦标赛 ICM 配置不能同时启用 rake。

`query(..., ev=True)` 返回每个组合的行动频率、每项行动的条件 EV，以及该组合按策略加权的 EV。数组顺序与 `actions` 一致。没有可达的兼容对手组合时 EV 为 `null`。`metric` 给出 `exploitability` 或 `nashconv`。两者的汇总字段沿用 `meta.exploitability_chips` 和 `meta.exploitability_pct_of_pot`。`gain` 按玩家存 `BR − EV`，汇总值使用双方收益增量之和。

要锁定节点，将 `locks` 加到配置。例如 `[{"line":"bet:10","player":1,"freqs":[0.7,0.3,0]}]` 按该节点的 `actions` 顺序锁定所有 IP 组合。`strategy` 可用逐组合的 action-major 数组替代 `freqs`，组合顺序与该节点的 `hands` 一致。引擎按锁定条件重新求解。

## 导入 Pio 预设

从已有 UPI 文本尾部读取 `set_board`、两份 `set_range`、有效筹码、底池和 `add_line`。范围按 Pio 的 1,326 项顺序解码，累计下注额保留原值。导入的命令只作为数据解析。`import_pio` 返回普通字典，可以在求解前修改范围、下注线、锁定和终止条件。[UPI 命令文档](https://piosolver.com/docs/upi/commands/) · [原包静态研究](../analysis/piosolver-3.3/investigation/README.md)

```python
from postflop_lab import Solver, import_pio

spot = import_pio(r"D:\path\to\BBvsBTN.txt")
spot.update(max_iterations=100, target_exploitability=0.2)
solver = Solver()
print(solver.tree(spot)["counts"])
solver.solve(spot, "imported.solution.json", threads=4, storage="f32")
```

也可以用 `python -B -m postflop_lab import-pio preset.txt` 输出 JSON。默认沿用预设保存的 `set_rake`，`rake_source="fields"` 或 `--rake-source fields` 改用 Viewer 配置字段。随包 51 份预设在这两处的 rake 信息不同。旧包中的 224 份翻后预设都能转换，共 61,689 条下注线。当前导入器要求 `set_pot 0 0 <dead>` 和完整建树尾部，遇到 `remove_line`、`force_line`、预设内 ICM 点表或其他未实现命令会报错。自建 ICM 配置走上面的 `tournament` 字段。

## 编译和复核

[同机性能对照](benchmarks/README.md) 包含 Pio Free 3.12.0 与本地引擎的翻牌、转牌、河牌和 ICM 实测。`0.1.0+rea.2` 修正了已经锁定名次奖金的出局结算。此前保存的相关 ICM 策略需要重新求解才能使用修正后的收益模型。

```powershell
.\postflop_lab\Build.ps1 -Test
python -B -m postflop_lab.examples.demo .research-cache/postflop-demo
```

`Build.ps1` 在这台机器使用工作区的 Rust 1.99.1 GNU 工具链和本机已有的 LLVM MinGW `dlltool`，也可使用 PATH 中的 Cargo。`-Test` 执行 Rust 和 Python 测试。`engine/src/` 是建树、牌力、终局、CFR 和 ICM 源码，`cli/src/` 是程序入口，`client.py` 是 Python 接口。可以直接使用 Rust 的 `NlheGame`、`Solver` 和 `Solution`，在同一个进程操作内核。

160 项 Rust 测试和 6 项 Python 测试通过。原包 224 份预设的累计下注线全部通过原生树编译校验。31,124 节点的 `8max0.5anteTreeBuilding/3bet_sqz/BBvsBTN.txt` 已用含 rake 的筹码收益和六人奖金结构 ICM 分别完成 12 次迭代，保存后重开并读取组合 EV。另一份 `6maxTreeBuilding/srp/BTNvsBB.txt` 展开到 3,832,274 节点，已验证建树。[测试日志](../.research-cache/postflop-verification.log)

默认配置逐张展开公共牌。启用花色同构时，训练只求解等价组的代表并按具体花色回填。默认 `max_tree_nodes` 为 5,000,000，默认策略数组预算为 4,096 MiB，包括保存时的策略副本。`--max-strategy-mib` 或 Python `max_strategy_mib` 可调整。树、牌力索引和运行临时内存另计。

解文件为本项目的策略 JSON，可重开、读节点和重算条件 EV。它不包含遗憾累加器和 RNG 状态，继续训练需重新求解。现有范围限于双人底池的翻牌、转牌与河牌，`.cfr` 互通、HRC 效用点导入和多人同底池求解尚未实现。求解使用独立的 DCFR 内核，ICM 平分彩池与 Pio 3.3 的整数奇数筹码结算有差异，未做策略逐位一致性比较。
