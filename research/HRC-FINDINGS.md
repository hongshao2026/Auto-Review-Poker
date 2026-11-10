# HRC 静态研究记录

> 这是首轮8类静态调查的历史记录。后续已扩展到主插件全类索引、核心算法字节码追踪与原始数值方法执行；当前状态见 [INVESTIGATION.md](D:/Users/Shao/Documents/ChatGPT/REA/INVESTIGATION.md) 和 [原始字节码验证](D:/Users/Shao/Documents/ChatGPT/REA/research/HRC-BYTECODE-VALIDATION.md)。下文“本次没有运行”的范围仅指首轮调查。

研究日期：2026-11-04（Asia/Shanghai）。目标是为独立实现的翻前研究工具提炼行为要求。本次没有运行 HRC，没有修改安装目录，也没有把 HRC 类、数据文件、图标或反编译代码放入实现。

## 结论

本机 HRC 是 Eclipse RCP / OSGi Java 应用。翻前树配置有清晰的脚本接口，可观察到加注尺寸、跟注限制、位置例外和全下规则。界面存在 Monte Carlo CFR 求解配置，另有标记为 CFR+ 的 169 类手牌求解器。以上足以确定一个独立研究实现的模块边界，但不足以恢复 HRC v4 的完整算法或证明数值等价。

最关键的模型差异：允许非全下跟注之后，翻后如何继续直接决定翻前范围。HRC 的现代模式使用抽象翻后树；若研究实现采用翻前结束后直接跑公共牌至摊牌，应明确称为「翻后过牌到底模型」。它可以用于算法实验，但不能据此宣称获得与 HRC 相同的深筹码跟注范围。

## 工件身份与证据

| 项目 | 结果 |
|---|---|
| 目标 | `D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar` |
| SHA-256 | `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43` |
| REA | 6.8.0，先检查会话为空，再打开目标、摘要检查、导出、关闭 |
| Java 类 | 986 个；所有 class major version 均为 65，即 Java 21 |
| Manifest | Bundle version 4.1.0.202603231401；OSGi JavaSE 21；构建 JDK 声明为 26，不能据此把运行要求写成 JDK 26 |
| 本次反编译 | 8 个选定类；Vineflower 1.12.0，静态读取，不执行目标类 |
| REA 存档 | `analysis/hrc-static/rea-evidence.json`，3 个证据记录，2,974,587 字节 |

REA 库存证据 ID：`ev_8207ff047fc3bb720fea2e38938583d55b935a040c250d25c83aa61270277631`。

REA 工件检查父证据 ID：`ev_5bd5997f323b6d08e8db9cbd0664e7ac46d81dcfe90391a0c3e422e8debc5d42`。

REA 摘要投影 ID：`ev_1260e2f1574a6f8f41bcac56948a15ac13fa067c597710da83ec21fbb43442b1`。

库存为 ZIP central-directory 范围完整；1104 个 occurrence，1103 个唯一图节点，无已发现完整性矛盾。REA 报告存在名称大小写折叠冲突。因此选定类按 ZIP ordinal 分目录保存，避免 Windows 默认不区分大小写导致覆盖。库存完整不等于运行时分析完整。

## 模块与入口地图

| 功能 | 证据锚点 | 证据所能支持的结论 |
|---|---|---|
| 应用启动 | `plugin.xml:11`；`selected/0114/decompiled/Application.java:11` | 启动 Eclipse Workbench；未执行入口 |
| 插件生命周期 | `META-INF/MANIFEST.MF` 主节 | Activator 为 `net.holdemresources.calculator.Activator` |
| 新手牌向导 | `plugin.xml` newWizards；`internal/jK.class` 常量 | Hand Setup 映射 jK；存在 handdata、eqmodel、engine、treeconfig 配置键 |
| 树配置界面 | `selected/0103/decompiled/jP.java:440` | basic、scripted、ui 模式；UI 配置分别存 preflop / postflop |
| 脚本桥接 | `selected/0682/decompiled/qu.java:29` | GraalJS 调用 canFlatCallPreflop 和 getSizingsPreflop，传入 qp 决策上下文 |
| 上下文接口 | `api-signatures.txt`；`selected/0669/decompiled/qp.java` | 提供玩家、位置、有效筹码、底池、下注计数、行动历史和尺寸换算 |
| 范围视图 | `plugin.xml:33` | Range 视图映射 iX；Table 映射 jo；Quick Graph 映射 ix，大小写有意义 |
| 范围编辑/锁定 | `plugin.xml` handlers | editrange→fh，lockrange→fj，frequencylockrange→fi；未追踪其全部行为 |
| 计算命令 | `plugin.xml` handlers；`selected/0521/decompiled/ew.java:113` | 同一计算命令绑定条件不同的 em / ew；ew 是 Monte Carlo 计算界面 |
| 范围剪贴板 | `selected/0527/decompiled/fm.java:46` | 分配 169 个 float 权重；表明存在 169 类翻前范围表示，不证明全部内部状态都只有 169 类 |
| 传统求解候选 | `selected/0994/decompiled/rw.java:26`、`:135` | 169 类数组、regret 累积，返回算法名 CFR+；不能把它直接等同于 v4 Monte Carlo 实现 |
| 预计算数据依赖 | Manifest Require-Bundle；常量池引用 HandEval2Way / HandEval3Way | 存在 holdem preflopdata 依赖；本次未读取其专有数据表 |

## 翻前配置语义

以下以随 JAR 提供的 `net/holdemresources/scripting/treescripts/scripts/preflop/preflop_general.js`、`preflop_simple.js` 和 API 签名为本地静态证据。官方 [树配置说明](https://www.holdemresources.net/docs/tree-config/) 为公开交叉验证。

- 尺寸最终表达为 raise-to 总额；允许以 bb、相对前次 raise-to 倍数、底池比例和有效筹码全下定义。
- 一个决策可配置多个尺寸；开池隔离加注可按 limper 数量调整，squeeze 可按 flat caller 数量调整。
- 开池区分普通位置、按钮、SB、BB，以及 BB 对只剩 SB 的场景；再加注区分 IP/OOP 与盲位对手。
- 简单配置按 open / 3-bet / 4-bet / 5-bet 分层；随包高级脚本在更深层默认只返回全下。这个默认不是无限完整尺寸空间。
- 非全下尺寸达到配置比例时归并至有效筹码全下；低 SPR 可额外增加全下。随包脚本用大于等于阈值比较，文档自然语言较简略。
- limps / flats 数量按下注层次限制；最近一次 raise 之后单独计数。可额外允许 SB 补齐、关闭行动的跟注，并限制此前未入池玩家冷跟 3-bet 及更深加注。
- 盲注计作翻前第一个 bet；因此 open raise 后为第二个 bet。玩家索引按翻前行动顺序固定，跨街保持不变。
- 脚本与规则引擎职责分离：脚本给尺寸和允许 flat 的条件；合法动作顺序、最小加注和有效筹码上界由建树器约束。公开 [ITreeBuildingScript API](https://www.holdemresources.net/s/updatesites/hrc/latest/scripting/javadoc/net/holdemresources/scripting/treescripts/api/ITreeBuildingScript.html) 明确这一点。

## 求解器模型：已知、推断与未知

**静态已知。** ew 的界面文本明确写有 Monte Carlo CFR，以及 HRC 4 default / HRC 3 legacy 两个选项；文案称 v4 更侧重实际到达的线路。cU 的文字声明 Monte Carlo 支持最多 10 名 active players，并考虑 card bunching。这些是工件中的产品声明，未通过本次运行实验验证。rw 的算法名是 CFR+；它与 Monte Carlo v4 的精确调用关系未建立。

**公开资料。** 官方 [Monte Carlo sampling](https://www.holdemresources.net/docs/monte-carlo-sampling/) 解释：CI 统计近期翻前策略变动；可中止、保存、继续，可选子树求解和节点锁定。CI 是收敛启发指标，不能替代 exploitability 或误差界。官方 [v3 发布说明](https://www.holdemresources.net/blog/2023-hrc-v3-release/) 说明翻后模型建立真实的抽象博弈树，而非单一静态 equity-realization 系数。

**推断。** 模块适合拆成规则状态、尺寸策略、公共行动树、私有手牌信息集、叶子收益、采样求解、展示与持久化。但这是独立实现的设计判断，并非已完整恢复的 HRC 类图。

**未知。** v4 具体采样估计器、探索策略、regret 折扣、剪枝阈值、抽象桶生成算法、全部范围文件格式、精确 ICM/KO 细节、所有边池和短全下重新开放规则、运行性能与数值误差均未验证。反编译存在同名字段/方法和缺失类型上下文，不能把可读输出当作可编译原始源码。

## 可重现性与边界

- `analysis/hrc-static/scan_class_constants.py`：只读取 ZIP 与 class 常量池，生成 class-constants.json 与 class-keyword-hits.json；完整记录成员名、ordinal、SHA-256、major version。
- `analysis/hrc-static/decompile_selected.py`：仅提取和反编译 8 个指定类；具体命令、输入/输出目录和返回码存 decompilation-index.json。每类各有日志。
- `analysis/hrc-static/jar-members.txt`、`api-signatures.txt`、选定脚本、plugin.xml 与 Manifest 是研究证据；不属于产品实现，不应打包发布。
- 没有做行为回归对比，不能声称克隆完成、与 HRC 数值相同或达到 HRC 精度。
- 研究清单状态：模块入口地图「部分回答」；树配置语义「已回答到脚本/API 层」；求解模型「部分回答」；独立行为规格「已形成」，见 BEHAVIOR-SPEC.md。

