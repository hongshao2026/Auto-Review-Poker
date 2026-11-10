# 八人 15BB · BTN · 6000 万次对照

2026-11-05 差异诊断：追加同配置 seed44 的 6000 万次受控实验。seed43/44 的 BTN 逐手牌／行动 MAE 为 3.1179 个百分点，与 seed43/HRC 的 3.0473 同量级；支持有限预算下的轨迹敏感性，尚未排除共同实现偏差或证明混频等价。见[原因调查与验证边界](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-STRATEGY-DIFFERENCES.md)。

2026-11-05。双方均完成约 6000 万次完整树训练。BTN 的整体加注／全下比例接近，但部分手牌的行动分配仍明显不同；本次结果不能称为逐手牌一致或已收敛。

## 场景与原版证据

8 人、每人 15BB、SB 0.5BB、BB 1BB、无 ante、ChipEV、无抽水。前五人 UTG → EP → MP → HJ → CO 全部弃牌，轮到 BTN 首入池。底池 1.5BB，BTN 剩余 15BB，动作是弃牌、加注到 2BB、全下到 15BB。HRC 使用 BU 表示 BTN。

使用 HRC 桌面新建场景；开池尺寸 2.0bb / all-in，允许一个平跟，再加注仅全下，maxactive 4。保留翻后下注和原版 1024 / 256 / 256 桶。原版自动初始约 1000 万次后，以 HRC 4.0 Default、Full Tree、Fixed samples 再追加 5000 万次，未重置遗憾或平均策略。初始与最终存档的 settings.json、gametree.dat 字节完全相同。

最终原版根节点存档计数为 **60,000,500**；它是 float32 保存的计数快照。原版 BTN 节点计数为 **22,559,076**。GUI 同一节点显示前面 5 folds、加注 25.1%、全下 6.2%，与解码结果按一位小数取整一致。

[原版 BTN 加注界面](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/screens/49-eight15bb-btn-raise.png) · [原版 BTN 全下界面](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/screens/50-eight15bb-btn-allin.png) · [配置、树与存档核对](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-native-eight15bb-scenario-validation.json)

## 独立计算与结果

我们的任务 `e0873922bdca438ba02e226571cf3569` 使用 seed 43，从零完成 **60,000,000** 次，内核计时 **401.65 秒**，BTN 更新 **22,646,124** 次。训练导入原版行动树并读取本机翻后抽象资源；不加载原版已训练策略，不调用原版求解器。原版策略在完成后单独读取用于对照。

该树共 4,786 节点、2,201 决策节点：翻前 973、flop 180、turn 396、river 652。独立重放检查通过，包括合法动作、筹码守恒和终端边池归属。

| BTN 行动 | HRC 原版 | 我们 | 我们 − 原版 |
|---|---:|---:|---:|
| 弃牌 | 68.7663% | 69.2391% | +0.4728 个百分点 |
| 加注到 2BB | 25.0711% | 25.0005% | -0.0706 个百分点 |
| 全下到 15BB | 6.1626% | 5.7604% | -0.4022 个百分点 |

169 类手牌全部覆盖。按 1326 组合加权的逐手牌／行动频率 MAE 为 **3.0473 个百分点**，最大单项差异 **82.1982 个百分点**；相对首行动 EV 的 MAE 为 **0.025784 BB**。这些是当前节点的描述性误差，未按上游到达范围加权，也不是策略损失或 exploitability。

| 手牌 | 原版加注 | 我们加注 | 原版全下 | 我们全下 |
|---|---:|---:|---:|---:|
| A6s | 10.34% | 92.54% | 89.49% | 7.46% |
| A2s | 8.08% | 84.29% | 91.48% | 14.84% |
| QTs | 2.66% | 68.06% | 97.34% | 31.94% |
| T7s | 5.64% | 85.23% | 0.42% | 0.00% |
| 55 | 20.48% | 2.73% | 79.52% | 97.27% |
| 22 | 0.03% | 0.00% | 79.98% | 71.25% |

例如 A6s，双方主要都是入池，但在小加注与全下之间的分配相反；T7s 的主要差异则在弃牌与加注之间。因此不能用整体 25% 加注率接近代替逐手牌比较。

## 图表、网页与复核

[两套 13×13 图](D:/Users/Shao/Documents/ChatGPT/REA/reports/figures/hrc-15bb-btn-strategy-comparison.png) · [169 类完整 CSV](D:/Users/Shao/Documents/ChatGPT/REA/reports/figures/hrc-15bb-btn-strategy-comparison.csv) · [图表数据与指标](D:/Users/Shao/Documents/ChatGPT/REA/reports/figures/hrc-15bb-btn-strategy-comparison.json) · [BTN 完整节点含 EV 与访问次数](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-native-eight15bb-btn-node.json)

网页已提供八人 15BB 固定预设，并切到此任务的 BTN 节点。新增八座桌面布局，修正旧的九人专用提示。两套矩阵共 1,014 个行动频率与导出数据逐一核对，最大浮点误差 1.11e−16；1073 CSS 像素视口下八个座位不重叠，页面无水平溢出。相关预设与应用测试 16 项通过，JavaScript 语法检查通过。通用绘图脚本重绘旧九人结果 CSV 完全一致，旧图未被覆盖。

[网页截图](D:/Users/Shao/Documents/ChatGPT/REA/reports/ui/hrc-native-eight15bb-btn-matrix.jpg) · [显示数值验证](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-native-eight15bb-btn-matrix-validation.json) · [任务原始导出](D:/Users/Shao/Documents/ChatGPT/REA/.runs/e0873922bdca438ba02e226571cf3569.json)

重新生成该图：

```powershell
.venv/Scripts/python.exe scripts/plot-hrc-strategy-comparison.py .runs/e0873922bdca438ba02e226571cf3569.json --fold-to-btn
```

原版最终存档 SHA-256：`4cf1df34e8cef402087d713a0a9909637c86480bde05cefcd6ccd35a067b03c6`。
独立结果 SHA-256：`cfb2c88ee6755475be36377765bd3d3d9d043af34356b777a127494307962b6e`。

本轮只比较该 BTN 节点；没有新增八人全树最佳回应评估，没有通过调整单手牌频率来贴合原版。
