# 本地求解器与 Pio 的同机基准

对照对象为官方 PioSOLVER Free 3.12.0，build `6ea1b938`，使用默认算法 `v4_small`。发行文件来自官方 updater 使用的 [分发清单](https://piofiles.com/download3/PioSolverFree3/files.txt)，SHA-256 为 `910eccb881ab5cd90f69b983b1690f00535284af3c8fbdcf8adcf9dae88a5020`。实测对象与原研究压缩包中的 3.3 Edge 版本不同。[官方免费版说明](https://site.piosolver.com/docs/product_comparison/)

环境是 Windows 11 build 26200、Intel Core i5-13600KF、约 32 GiB RAM，两边都配置 4 线程。同一牌面、范围权重、有效筹码、起始底池和累计下注线。无 rake。主对照关闭 Pio 花色同构，翻牌额外测了同构开启。样例使用 Qs Jh 2h 及其后续牌面，来自免费版可用范围。

## 测量口径

- 误差为 `((BR_OOP − EV_OOP) + (BR_IP − EV_IP)) / (2 × 起始底池) × 100%`。ICM 的收益和最佳反应以筹码缩放后的奖金权益计算。它对应一半 NashConv。Pio 的 `calc_results` 输出精确到 0.001 筹码，判定达标时留出 0.0005 筹码的舍入裕度。[UPI 命令文档](https://piosolver.com/docs/upi/commands/)
- 先测递增迭代检查点。达标选取该点以及之后所有采样点都符合阈值的最早检查点。然后从空策略一次求解到选中的迭代数，重复三次并取中位数。阈值结论限于实际检查点和迭代上限。
- `solve_to_result_s` 从树已就绪计至得到精度读数。Pio 包含 `go` 到 `SOLVER: stopped` 的等待及 `calc_results`，`worker_s` 单列 `started` 到 `stopped` 的事件间隔。本地测原生 Rust 调用，不含启动进程与打印策略。构树时间另记，解文件导出和策略查询不在这段计时内。
- 河牌有解析均衡。无 ICM 时 OOP 诈唬和 IP 跟注均为 50%，底池分配 EV 为 75/25。三人三奖 ICM 例中，按各终局栈的精确名次概率算效用，诈唬和跟注分别为 `23/28` 和 `15/38`，绝对 CSTE 为 `150.21929825/121.13095238`。Pio 通过效用点表使用同一组终局收益，把 EV 加回起始栈的效用后再对照。

## 结果

时间取三次中位数，从树就绪到精度读数。每格依次为 **0.10% / 0.01%** 起始底池误差目标。

| 案例 | 本地 | Pio `v4_small` | Pio `v4_small` + 同构 |
| --- | ---: | ---: | ---: |
| 河牌 ChipEV，6 节点 | 0.58 / 4.64 ms | 109 / 113 ms | |
| 河牌 ICM，6 节点 | 0.046 / 0.30 ms | 110 ms / 未持续达标 | |
| 转牌 ChipEV，1,305 节点 | 97 / 192 ms | 143 / 190 ms | |
| 翻牌 ChipEV，63,954 节点 | 2.24 / 8.59 s | 2.74 / 5.42 s | 1.75 / 3.60 s |

河牌 ChipEV 到 0.01% 时，Pio 记录到的工作线程事件间隔为 13.0 ms，含等待的 `go` 到结果为 113 ms。本地 Rust 新进程启动加测量约 9.2 ms。转牌到 0.01% 时，Pio 工作线程为 111 ms，本地训练为 188 ms。翻牌 0.01% 档本地建树和分配为 18 ms，Pio 关闭同构为 39 ms，开启同构为 33 ms。

转牌高迭代点双方 OOP EV 分别为 70.12576 和 70.126 筹码，翻牌分别为 64.67871 和 64.680 筹码。河牌 ChipEV 在 16,384 次迭代时都显示 75/25，独立重算的残差分别为本地 0.00474% 和 Pio 0.00116%。同一迭代数下 ICM 河牌独立重算的残差为本地 0.000165%、Pio `v4_small` 0.02745%。`v4_small` 曾降至 0.007% 后反弹，另测 Pio `pio_cfr` 在 64 次的检查点开始持续达标，含接口等待约 110 ms。[ICM 算法复测](../../.research-cache/pio-benchmark/icm-pio-cfr.json) · [河牌独立验算](../../.research-cache/pio-benchmark/river-oracle.json)

首次 ICM 对照发现本地终局遗漏了本手新出局者已锁定的名次奖金。`0.1.0+rea.2` 修正了这个收益边界。上表使用修正后的本地收益计算。

## 复跑

从工作区根目录执行。基准源码使用 [Rust 计时器](../engine/examples/compare_latency.rs) 和 [UPI 比对脚本](compare.py)。

```powershell
.\postflop_lab\Build.ps1 -Bench
python -B -m postflop_lab.benchmarks.compare `
  --pio .research-cache/pio-benchmark/official-free/PioSOLVER3-free.exe `
  --local .research-cache/postflop-target/release/examples/compare_latency.exe `
  --out .research-cache/pio-benchmark/final-comparison.json `
  --modes local v4_small v4_iso
python -B -m postflop_lab.benchmarks.river_oracle .research-cache/pio-benchmark/final-comparison.json
```

[原始检查点和每次试验](../../.research-cache/pio-benchmark/final-comparison.json) 包含输入、策略样本、EV、最佳反应、各段延时及实际测试程序的 SHA-256。

### 用 Pio 预设做 ICM 对照

使用 `--preset` 加载一份翻牌预设，`--tournament` 提供 `payouts`、`stacks` 和 `seats` 的 JSON。两边沿用原范围和累计下注线，锦标赛模式关闭预设 rake。对照要求偶数起始底池，保证平分彩池的终局收益一致。可用 `--board` 指定 Pio Free 支持的牌面，报告会记录源牌面、原始 rake 和预设 SHA-256。

```powershell
$run = '.research-cache/pio-benchmark/preset-icm'
$preset = 'analysis/piosolver-3.3/original/piosolver3.3-en/piosolver3/TreeBuilding/6maxTreeBuilding/4bet/BTNvsSB.txt'
python -B -m postflop_lab.benchmarks.compare `
  --pio .research-cache/pio-benchmark/official-free/PioSOLVER3-free.exe `
  --local .research-cache/postflop-target/release/examples/compare_latency.exe `
  --out "$run/comparison.json" --preset $preset --board 'Qs Jh 2h' `
  --tournament "$run/tournament.json" --modes local v4_small
```
