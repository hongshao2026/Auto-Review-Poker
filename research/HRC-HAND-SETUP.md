# HRC Hand Setup：输入与联动证据

日期：2026-11-06。对象：本机 `net.holdemresources.calculator_4.1.0.202603231401.jar`，SHA-256 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。本次仅静态阅读已有反编译及 `javap -c -p`；没有启动/操作原 GUI、训练或修改产品。以下是本版本程序规则，不等于本轮已逐项完成实机 UI 测试。

源码根目录：`D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/`。下文 `ordinal/Class.java:line` 均相对此目录。含同名不同 descriptor 的反编译字段应按类型辨认，不能把反编译文本当可直接编译的原源码。

## 1. 筹码、BB 与座位

原始数据以整数 `raw` 存筹码，每 **100 raw = 1 界面 Chips**。这与独立应用内部自行采用的 10000 倍缩放不是同一概念。

| 输入/显示 | 原版规则 | 证据 |
|---|---|---|
| Chips、SB、BB、Ante、Total Chips | 显示 `raw/100`，`DecimalFormat("0.##")`；非空写入 `Math.round(Double.parseDouble(text)*100)`，空值转 null | `0258/gH.java:10–22`；`0249/if.java:39`；`0221/gt.java:185` |
| 座位 BB 列 | 显示 `stack_raw / bb_raw`；编辑后 `stack_raw=round(input_bb*bb_raw)` | `0234/ij.java:153–175` |
| BB 现有值重写保护 | 仅当 `round(old_stack_raw/bb_raw*100) != round(input_bb*100)` 才重写 stack。两位 BB 舍入相同则保留原始精度 | `0234/ij.java:170` |
| 改盲注大小 | 只修改盲注数组该项；不等比例缩放现有 stacks，座位 BB 随新除数重算 | `0235/ig.java:51–65` |

例：Chips=1500、BB 盲注=75，座位显示 20 BB。将座位 BB 改为18，Chips 变1350；再把盲注 BB 改100，Chips 仍1350、座位变13.5 BB。

注意：两位 BB 的条件是**编辑提交保护**，不能据此声称 BB 列格式一定只显示两位。该列使用依赖中的 `DefaultDoubleDisplayConverter`（`0221/gt.java:181–182`），本轮没有复查依赖格式化实现。所有上述 `round` 是 Java `Math.round`，不是 Python 默认的 ties-to-even `round`。

座位输入以**发盲注前**筹码为准，从翻前第一行动者开始；见 `0102/jJ.java:53`。人数选择 Auto/HU/3–10max：

- Auto 删除未填写的占位行；输入新筹码后座位名自动更新。固定人数不足时在队列开头插入未填写行，缩人数先去未填写行，仍超出则从队头删除（`0234/ij.java:24–45`）。
- 清空一格：Auto 删除该玩家；固定人数将其设为未填写，不立即减少座位数（`ij.java:128–146,160–168`）。
- 两个旋转按钮移动完整 `ii` 对象，筹码和赏金一起移动：forward 首行到末尾、backward 末行到首行（`0102/jJ.java:229–255`）。
- 逐座菜单 Duplicate / Delete / Move to，移动保留筹码和赏金；`0234/ij.java:77–121` 及 `ik/il/im`。
- 当前手 SB、BB 输入必须 raw>0；Ante raw>=0。SkipSB 是独立规则，不能用 SB=0 代替（`0235/ig.java:51–71`）。页级检查 SB<=BB、至少两名玩家且所有固定座位有正筹码（`0102/jJ.java:259–280`；`0236/ih.java` 的 `a()String`）。
- Ante 类型：每人 Regular、BB Ante AF（ante 先）、BB Ante BF（blind 先）。Straddle：Off/Single/Double/Button。Moving BU tooltip 明确只影响 FGS 中 BB 被淘汰后的下一手轮转（`0235/ig.java:13–30,42–48`）。

## 2. KO-T$、KO-P$ 与赏金模式

令当前头赏金为 `T`、Instant 输入百分数为 `p`、`alpha=p/100`：

| UI | 显示与编辑 | 证据 |
|---|---|---|
| KO-T$ | 完整头赏金 T；输入直接改 T | `0234/ij.java:48,184–190` |
| KO-P$ | 立即现金部分 P=T×alpha；输入 P 反推 T=P/alpha | `0234/ij.java:49,196–201` |
| Instant(%) | 显示 `100*progressiveFactor`；编辑写 `input/100`，范围0..100 | `0317/ip.java:37–38,56–57,69` |
| alpha=0 | KO-P$ 显示0，禁止编辑；KO-T$仍可编辑 | `0234/ij.java:196–201` |

例如 Instant=50%、KO-T=40，则 KO-P=20；改 KO-P=30 会令 KO-T=60。之后 Instant 改25%，保留 T=60，P 显示15。两列不是两份独立赏金。

`Off/KO/PKO` 是 `0317/ip.java:7–8` 中的模式：

- Off：无赏金。
- KO：使用统一 `KO Size($)`，普通非渐进赏金。
- PKO：使用各座头赏金和 Instant。`oP.isIndividualBountyUsed()Z` 仅 PKO 返回 true（`0742/oP.java:141`）。

切换为 KO 仅显示 KO Size 行；切换为 PKO 仅显示 Instant 行；这两行使用 **隐藏行** 规则，不只是禁用编辑（`0317/ip.java:62–70`；`0221/gt.java:162–175` 的 `hideRowIndexes/showRowIndexes`）。座位 KO 列在不可用时标题/内容为空、编辑禁止，源码没有缩掉这两列宽度（`0234/ij.java:63–75,184–201,230–237`）。切换模式不清除 `ii` 中已有各座赏金；从模式切回来会再次显示。联动回调见 `0311/in.java:164–177`、`0102/jJ.java:90–95,120–121`。

## 3. 奖金金额、百分比、总奖金与 Places Paid

**原版只编辑奖表的 Prize($) 列。百分比、Places Paid、Prizes($) 全部只读。**

- `0314/it.java:17` 的 `isEditable(II)Z` 仅列0返回 true。
- `0317/ip.java:63–64` 对 Places Paid、Prizes($) 明确设置 editable=false；它们的 getter 分别调用 `getNumberPrizes()`、`getStructureTotal()`（同文件27–30）。没有这两行的 setter。
- 百分比 `100*getPrize(rank)/getStructureTotal()`，格式 `0.0#`（`0315/iu.java:17`，`0835/pM.java:9`）；总奖金只包含常规名次奖，不包括赏金（`0317/ip.java:12`）。

奖表底层是按名次的**分段值表** `TreeMap<rank, amount>`，不是彼此独立的每名输入：

1. 显式填写 rank 的金额>=0，调用 `oP.setStructure(ID)V`；清空或输入 `..` 删除该名次的显式值。首行不允许清空（`0315/iu.java:21–29`；`0316/is.java:11–18`）。
2. 位于最后显式名次以内的隐式行继承最近的较低名次值，金额列显示 `..`，百分比仍显示该实际金额占比。最后显式名次之后显示为空、奖金0（`iu.java:11–18`；`0742/oP.java:84–101`）。
3. 若最后键为 L，最后值>0，则 Paid=L；最后值为0，则 Paid=L−1（`oP.java:104–106`）。因此新增/删除末尾名次或放置末尾零是改变付奖人数的实际入口。若末端已有0，再往更远名次填0会被忽略（`oP.java:65`）；删除末端键会退回前一显式键定义的长度，不会无限向后继承。例如下方第二个例子删除 rank8 的0，Paid 会由7变5。
4. 总奖金是展开 Paid 个名次金额的和。修改一个档位会改变该档直到下一档的所有名次金额与所有百分比，不会自动保持总奖金或同比调整其它档位（`oP.java:84–114`）。
5. 与前一档数值相同的中间显式档可删除；**最后显式键保留**，以保存长度边界。`checkStructure(TreeMap,I)V` 在修改点及相邻 rank 检查（`oP.java:15–22,63–78`）。已用原 JAR `javap` 复核：该方法 pc43/57 调用 `Double.doubleValue()`、pc60 `dcmpl`，是数值比较，不能误读反编译 `(Double)==(Double)` 为对象身份比较。
6. 页级验证要求至少一份名次奖、后名次奖金不能大于前名次。报错而不是自动排序修正（`oP.java:185–201`）。

可独立复现例：

| 显式 rank→金额 | 展开奖金 | Paid | Prizes($) |
|---|---|---:|---:|
| 1→50, 2→30, 3→20, 4→0 | 50,30,20 | 3 | 100 |
| 1→100, 2→60, 5→30, 8→0 | 100,60,60,60,30,30,30 | 7 | 370 |
| 上一行清空 rank2 | 100,100,100,100,30,30,30 | 7 | 490 |

Clear Prizes 重置 `{1:100}`、Off、Instant50%、统一赏金0；不清除 `totalChips`（`0742/oP.java:145–152`；按钮 `0311/in.java:108–114`）。Total Chips 允许留空或正数，使用筹码转换器；是赛事筹码总量，和 Prizes($) 完全不同。

## 4. Calculation Mode 的两层选项

`0247/hN.java:17` 有三行：Hand Mode / Equity Model / Model Options。

| 项目 | 原版选项/行为 | 证据 |
|---|---|---|
| Hand Mode | Engine=Enumerated 或 Monte Carlo；Advanced Betting；Monte Carlo 的 Max Players 可2..10，枚举模式隐藏此输入、实际上限3 | `0238/hL.java:7–8,44–48`；`0256/hM.java:10–11`；`0098/jL.java:13–20` |
| Equity Model | ChipEV in Big Blinds；Malmuth-Harville ICM；Future Game Simulation FGS；Multi Table (MTSNG/MTT) ICM | `0102/jJ.java:29–31`；实际构造 `0099/jK.java:44–46` |
| ChipEV options | Regular/Raked；Rake(%) 0<=x<100；Cap($) 以raw/100转换；Preflop Rake=No Flop No Drop / GG Network / Full | `0254/hP.java:8–10,40–72`；`0065/jx.java:42–67` |
| ICM options | 无额外 options，显示 `-`；奖金在当前页 | `0064/jC.java:34–55`；`0247/hN.java:45–50` |
| FGS options | Auto Depth、Depth、More Options、Increase Blinds、At Depth、下一档SB/BB/Antes；手动 Depth/At Depth 1..19；未来BB>0、未来SB/ante>=0 | `0241/hR.java:12,76–98`；序列化 `0077/jz.java:73–90` |
| MTT options | Model Options 无附加对话框；通过向导下一页进入 MTT Stacks | `0075/jD.java:20–22,48–55`；`0099/jK.java:148` |

ChipEV 时整个 Prizes group 不可见；ICM/FGS/MTT 可见（`0102/jJ.java:107,120–121`，各 `jw.a()Z`）。这与可选择赏金类型是两个不同控制条件。原 GUI 记住上次选用的 Equity Model 索引（`0247/hN.java:59–62,72`），不能仅凭一张截屏认定某种模型是每次新建的固定默认。

## 5. 外桌筹码入口与生成公式

`0071/jE.java:45–48` 是独立的 **MTT Stacks** 向导页，不是 Hand Setup 第一页的可编辑统计列。界面有 Generate / Manually Edit / Clear / Copy / Paste（同文件93、139、154、169、183）。`0075/jD.java:74–81` 输出 `otherstacks` 和 PKO 的 `otheravgbounty`。

- `otherstacks` 是**界面 chips 浮点值**，没有乘100，也不是 BB。当前桌 raw stacks 在该页先除100；图表才再除以界面 BB（`jE.java:100–102,232–239`）。
- 手工列表每行输入一个正 double，清空删除，提交后按筹码降序插入；编辑框确认还整体降序排序（`0246/hY.java:11–16`；`0239/ia.java:21–40`；`jE.java:141–148`）。
- 粘贴每行一个数，非空行要求 `0<x<=1e12`；不接受额外列。该检查未明确拦截 Java NaN，本次不据此建议产品放行非有限值（`jE.java:185–223`）。Copy 不含当前桌，每个数输出4位小数（169–175）。
- 第一页 Total Chips 本身只存储筹码总量，供 MTT 页初始化/推估；不是填写它就已形成 outside stack 列表（`0317/ip.java:13`；`jE.java:287–295`）。

Generate 对话框（`0245/hS.java:10–17`；`0070/jF.java:18–26`）参数为全赛事总筹码 C、全赛事存活人数 N（含当前桌）、平均筹码 A、Randomize、Auto Shape、Shape。`0242/hT.java:11–27` 中 C 与 A 是二选一锚点：固定 C 时 A=C/N；固定 A 时 C=round(100*A*N)/100。改变 N 依锚点重算另一值。

若当前桌 n 人筹码为 x_i（界面 chips），外桌 m=N−n，生成目标外桌平均：

`A_out = (C − sum(x_i)) / m`。

Shape s<=0 时全部外桌都是 A_out；s>0 时使用 `LogNormalDistribution(1,s)`：Randomize Off 取分位点 `(i+1)/(m+1)`，On 取 m 个随机样本；再令每个 outside stack=`sample_i/mean(samples)*A_out` 并降序排序。因此最终外桌和与 C−当前桌之和一致（`0071/jE.java:100–130`）。Auto Shape 为 `sqrt(mean((log(x_i)−log(A))²))`（`0245/hS.java:128–133`）。手动 Shape 区间0..2；Remaining Players 输入要求大于当前桌人数（`hS.java:93–100`）。

外桌 PKO 可以在统计表的 Other Tables / Avg. Bounty($) 编辑一个平均头赏金。留空恢复当前桌头赏金均值，填值则覆盖；外桌赏金池=该均值×外桌人数（`0257/hU.java:74–89`，`0069/jG.java:9–14`）。不是逐个 outside bounty 列表。

静态边界：hS 的 C/A 正数验证表达式存在单位不直观之处。原字节码私有 `a(Long)Z` pc9–24 确实比较 `raw_C − activeAverageChips/100*n >0`，`a(Double)Z` 类似；不应把它误写成已经严谨验证 `C>sum(activeStacks)`。产品仍应显式验证外桌生成平均为正。本次未操作原 GUI 来确认这些异常输入最后的可见表现。

## 6. 交付边界与 UI 复核建议

本记录提供可直接实现的换算/联动，未修改前端或后端。尚需实机确认的是输入激活键（单击/双击/键盘）、焦点提交时机、依赖 double converter 的可见位数、窗口缩放与菜单定位。原始 NatTable 多处配置 `TextCellEditor(true,true)`，不能仅凭构造参数断言所有操作系统交互完全相同。

建议 root 正在进行的实机验证采用：①编辑座位 BB 再改 BB 盲注，②PKO 中 T/P/Instant 三者连续修改，③奖档末尾写0并清空中间档，④验证 %、Places Paid、Prizes($) 无编辑入口，⑤MTT Next→手工外桌→清空/粘贴。各观察应与本记录的静态事实分开标注。
