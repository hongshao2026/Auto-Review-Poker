# General 建树与 moving button

2026-11-05。生产实现为 `preflop_lab/hrc_general_policy.py` 和 `hrc_tree_builder.py`。
它们读取显式设置，独立选择尺寸、允许跟注及换街；训练和建树不执行 JavaScript，也不读取原策略或叶子权益。

## 接口与当前范围

```python
from preflop_lab.hrc_tree_builder import default_settings, build_tree

settings = default_settings(8, 150000, 10000,
    preflop_policy="general", postflop_policy="general")
settings["handdata"]["movingBu"] = True
tree = build_tree(settings, node_budget=250000)
```

原 HRC 形状配置也可直接提供 `preflop.settings.general`、`postflop.settings.general`。
两街策略可以与 simple 独立混搭；未传新参数时保持原 simple 默认设置和 compact 身份字段。
所有金额仍用内部整数，blinds 的顺序仍为 `[BB,SB,ante]`。节点预算、256步深度、16动作上限、取消及确定性导出保持原有规则。

General 默认15BB的本机完整树生成记录：HU451节点/0.013秒，3人995/0.027秒，6人7113/0.23秒，8人15865/0.60秒。
这些是独立生成耗时与有限性证据；**没有**把它们称为完整原 general 存档拓扑对照，后者尚无桌面fixture。

## movingBu 的精确作用范围

**已证实事实**：当前手的初始发盲、按钮/盲注索引和行动顺序不读取 movingBu。
按钮仍为 HU座位0，其他人数 `n-(skipSB?2:3)`；SB为 skipSB时-1，否则n-2；BB为n-1。
`ky.a:Z` 表示 movingBu，而 `kM.a:Z` 表示 skipSB，两者不能因为混淆同名字段而互换。

原 `kM.a(Lnet/holdemresources/internal/lE;)Lnet/holdemresources/internal/kH;`
在字节码偏移10–24读取 `ky.a:Z`，传入 `lD.<init>([JZZ)V` 后调用轮转；这是本手终局以后创建下一手的路径。
当前手的 `kG.b()I`、`qp.getPlayerIndexButton()I` 仅检查人数和skipSB。
证据见 [kM字节码](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-builder/bytecode/kM.txt:100)、
[kG索引](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-builder/bytecode/kG.txt:31)、
[qp索引](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-builder/bytecode/qp.txt:127)。

独立建树因此接受并保留 movingBu，不凭空改变当前手位置。2857组原方法的true/false配对包含2–10人、不同短栈、三种ante、四种straddle和skipSB，所有当前手上下文相同。
未来多手轮转由已有FGS模块的 moving_button 实现；本批没有把当前手配对测试冒称为再次验证全部FGS轮转。

## 全部38个设置

以下每个键均在原本机脚本动态对照中实际被读取，报告 `uncovered_settings=[]`。
翻前尺寸字符串支持bb、x、%、all-in，以及逐个已有跟注者的加号附加项；逗号或空格分开尺寸。
翻后字符串支持pot百分比（无后缀也按百分比）、g几何hint、e等比分割次数、x最近下注倍数、bb、all-in。
`e` 先按原 `Math.rint` 的偶数舍入处理；0e或舍入到0明确拒绝；g必须正，避免没有意义的几何hint。
翻后空字符串、`none`、`-` 是空尺寸覆盖；null表示按下述继承，不是空列表。

| 翻前键 | 行为 |
|---|---|
| `SIZES_OPEN_OTHERS` | 普通位置首加 |
| `SIZES_OPEN_BU` | 按钮首加 |
| `SIZES_OPEN_SB` | SB首加；HU时覆盖同席BU规则 |
| `SIZES_OPEN_BB` | BB隔离多个剩余玩家 |
| `SIZES_OPEN_BB_VS_SB` | 只有SB未弃牌时的BB隔离，优先于普通BB规则 |
| `SIZES_3BET_IP` | 普通IP三加，以及OOP配置缺省时的回退 |
| `SIZES_3BET_OOP` | 普通OOP三加；null回退IP |
| `SIZES_3BET_BB_VS_SB` | BB对SB三加；null回退普通IP/OOP |
| `SIZES_3BET_BB_VS_OTHER` | BB对其他位置三加；null同上 |
| `SIZES_3BET_SB_VS_BB` | SB对BB隔离的三加；null同上 |
| `SIZES_3BET_SB_VS_OTHER` | SB对其他位置三加；null同上 |
| `SIZES_4BET_IP`, `SIZES_4BET_OOP` | 四加位置分支 |
| `SIZES_5BET_IP`, `SIZES_5BET_OOP` | 五加位置分支；六加及以后只全下 |
| `PREFLOP_ALLIN_THRESHOLD` | 尺寸达到有效全下额指定百分比时改为全下 |
| `PREFLOP_ADD_ALLIN_SPR` | SPR≤阈值附加全下；负数始终附加 |
| `ALLOWED_FLATS_PER_RAISE` | 每下注层已有平跟人数上限 |
| `ALLOW_COLD_CALLS` | 三加及以上，当前街此前未行动者的cold call许可 |
| `ALLOW_FLATS_CLOSING_ACTION` | 结束本轮行动的平跟例外，优先于cold-call禁令 |
| `ALLOW_SB_COMPLETE` | 未加注时已发活盲注者补齐；原脚本不限于名为SB的席位 |

IP/OOP按按钮后面的环形行动顺序比较，不能直接比较座位数字。
closing action要求其他未弃且非全下者已经参与，并且当前街投入不低于当前下注。
原证据为 `qp.isPlayerInPosition(II)Z` 和 `qp.isClosingAction()Z`，见
[qp字节码591](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-builder/bytecode/qp.txt:591)、
[qp字节码449](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-builder/bytecode/qp.txt:449)。

| 翻后键（各有HU/多人两值） | 行为 |
|---|---|
| `POSTFLOP_FLOP_BET`, `POSTFLOP_TURN_BET`, `POSTFLOP_RIVER_BET` | 普通下注；turn/river null沿前街继承 |
| `POSTFLOP_FLOP_RAISE`, `POSTFLOP_TURN_RAISE`, `POSTFLOP_RIVER_RAISE` | 加注；null递归沿前街同类，flop再回退flop bet |
| `POSTFLOP_FLOP_DONK`, `POSTFLOP_TURN_DONK`, `POSTFLOP_RIVER_DONK` | donk；null继承规则同raise |
| `POSTFLOP_LOW_SPR_THRESHOLD` | 所有三类尺寸前优先检查低SPR覆盖 |
| `POSTFLOP_LOW_SPR_BET` | 低SPR默认尺寸 |
| `POSTFLOP_LOW_SPR_RAISE` | 低SPR且已有下注时覆盖；null回退low-SPR bet |
| `POSTFLOP_ADD_ALLIN_SPR` | SPR阈值附加全下；负数始终附加 |
| `POSTFLOP_ALLOW_DONK` | donk许可 |
| `POSTFLOP_ALLOW_DONK_PREV_AGGRESSION` | 本手此前主动加注者的donk例外 |
| `POSTFLOP_MAX_BETS_PER_STREET` | 达到次数时只全下；-1不限 |
| `POSTFLOP_FORCE_CHECKDOWN_AFTER` | 此键按存活且非全下人数索引最后正常下注街，不是HU/多人两值 |

原函数证据：
[preflop_general.js:54](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-scripts/preflop_general.js:54)、
[位置选择:82](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-scripts/preflop_general.js:82)、
[跟注规则:144](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-scripts/preflop_general.js:144)、
[postflop_general.js:47](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-scripts/postflop_general.js:47)、
[postflop分支:119](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/general-scripts/postflop_general.js:119)。
Java数值API为 `qp.sizingsPreflop(Ljava/lang/String;)[J`、`sizingsPostflop(Ljava/lang/String;)[J`、
`getStackPotRatio()D`，保留字节码在 `analysis/hrc-deep/general-builder/bytecode/qp.txt` 第235、258、287行。

## 原方法与脚本对照

主JAR SHA-256仍为 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。
预置preflop脚本SHA为 `50841e520d2eace9730126a9880149ea6004a2c4c1ad57601d4f267887ddf30a`，
postflop为 `93ac409c00866c3d1b7c2353bbb0d2a01a2eda3e2eddb894b7f9642b53025f39`。

`OriginalGeneralContextProbe.java` 使用平台父loader和逐类白名单，只执行已审纯数值/规则类。
原 qp/qw 直接产生位置、closing、SPR、donk、尺寸解析结果；测试适配器把这些结果交给确切hash的本机脚本。
Node VM禁止字符串代码生成和WASM，未提供process、require或文件API；只运行这两个已审资源，不接收任意脚本路径。
此处用V8执行已审JS而非HRC的GraalVM，因此证据称“本机脚本函数对照”，不称整个原HRC脚本引擎已经重建。

`.venv\Scripts\python.exe scripts/validate-hrc-general-builder.py`：270配置、5714上下文、2857 moving配对，
全部原状态字段、位置矩阵、SPR、选择的尺寸、flat许可和换街判定相同；38设置全部被执行读取。
原输出、输入与固定脚本执行结果保存在 `analysis/hrc-deep/general-builder/`，完整哈希/执行命令/失败列表在
[hrc-original-general-builder-validation.json](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-general-builder-validation.json)。

短栈button straddle且skipSB的极端实际配置会产生负SPR和 `minimum>maximum`；原API确实如此。
本实现保留该值，尺寸最终按有效上限钳制，没有用“通常SPR应非负”的假设拒绝原本可生成的状态。
一个具体原验证案例是3席 `[25,25,2000]`、BB100、ante10、skipSB、button straddle：BB起始 minimum400、maximum25。

`pytest tests/test_hrc_tree_builder.py tests/test_hrc_general_builder.py -q`：84项通过。
包含原simple五棵全树、general混搭确定性/四街/守恒、位置优先级、cold-call例外、所有单位、moving保留、
短栈straddle、非法数据和完整原证据覆盖。有限配置对照不意味着已经穷举所有树，更不证明训练策略收敛。
