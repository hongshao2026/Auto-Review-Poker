# 九人20BB原版桌面试算

2026-11-04，使用正在运行的本机HRC Pro，按上一轮九人10BB配置建立20BB手局。九人筹码从每人1000改为2000，SB50、BB100、ante0，ChipEV、无抽水、maxactive4。逐字段比较真实存档设置，差异恰好只有九个stacks值；下注尺寸、flat限制、翻后选项及抽象资源ID全部相同。

原版先自动完成约1000万次初始采样，再经Nash Calculation对话框选择HRC 4.0、Full Tree、Fixed number of samples=50 million，未重置遗憾或策略。追加完成后根节点float32计数为60,000,500，初始为10,000,250。这是本节点计数快照，与对话框采样量相互印证，不是逐手牌访问数或收敛证明。

## 实测结果

下表是UTG根的169类平均策略，按6/4/12具体组合数加权。EV为加注2BB相对弃牌的历史加权值，单位BB。

| 指标 | 10BB，初始约1000万 | 20BB，初始约1000万 | 20BB，累计约6000万 |
|---|---:|---:|---:|
| 弃牌 | 89.0292% | 89.3819% | 86.8925% |
| 加注2BB | 8.1307% | 9.8553% | 13.0864% |
| 直接全下 | 2.8401% | 0.7628% | 0.0212% |
| AA加注EV | +4.6289 | +6.4558 | +6.0250 |
| KK加注EV | +3.5945 | +4.5356 | +4.0111 |

初始两列采样量相同，但均无收敛证明。20BB追加采样后加注比例继续变化了3.2311个百分点，直接全下降低0.7416个百分点，说明初始值不稳定；不能将末列与第一列的所有差异都归因于筹码深度。最新全下概率0.0212%在原版界面显示0.0%，并非数学上的精确零。

| 街道 | 10BB决策节点 | 20BB决策节点 |
|---|---:|---:|
| 翻前 | 1,586 | 1,586 |
| Flop | 232 | 348 |
| Turn | 492 | 1,072 |
| River | 780 | 2,316 |
| 合计 | 3,090 | 5,322 |

20BB实际存档共12,193节点，包括6,871个叶节点；全部节点payload完成解析，全部idx偏移/长度核对通过。format23翻前1,586节点，format25翻后3,736节点，无锁。解码逐节点校验后仅保留根169类和概要，避免再生成数百MB的展开JSON；原始hrcz完整保留全部数据。

## 配置边界与证据

此树沿用此前的Simple配置：开局2BB或all-in、允许一个flat；3bet及更高次加注只设置all-in，没有加入非全下3bet尺寸。这是固定行动集合下的原版运行结果，不代表任意20BB行动树的完整均衡，也不是网页独立引擎已经复现了20BB。maxactive4仍是累计参与人数限制，不能理解为9人无限制进入翻后。

- [约6000万采样完整存档](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/nine20bb-raise-call-postflop-60m.hrcz)
- [初始存档](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/nine20bb-raise-call-postflop-initial.hrcz)
- [逐字段设置对比、节点统计与169类数据](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/nine10bb-vs20bb-comparison.json)
- [原版结果截图](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-desktop/screens/37-20bb-add50m-result.png)
- [只读复核脚本](D:/Users/Shao/Documents/ChatGPT/REA/scripts/compare-hrc-stack-depth.py)

复核命令（项目根目录）：

```powershell
.venv/Scripts/python.exe scripts/compare-hrc-stack-depth.py analysis/hrc-desktop/nine10bb-raise-call-postflop-initial.hrcz analysis/hrc-desktop/nine20bb-raise-call-postflop-initial.hrcz analysis/hrc-desktop/nine20bb-raise-call-postflop-60m.hrcz --output analysis/hrc-desktop/nine10bb-vs20bb-comparison.json
```

20BB本次未额外做GUI载入另存往返，不能把此前10BB往返测试写成本次也已执行。独立九人求解器、最佳回应误差和20BB收敛证书仍未建立。
