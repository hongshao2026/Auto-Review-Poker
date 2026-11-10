# HRC 功能对齐矩阵与验收边界

更新：2026-11-05。对照对象为本机 HRC `4.1.0.202603231401`，不是对未来版本或所有插件的保证。本文件记录用户可使用的功能、独立实现与原版证据之间的差距，不能用“已读懂代码”代替“已经实现”，也不能用少量数值探针代替端到端等价。

**当前结论：已有四街独立训练、锦标赛收益链路与独立 Simple 建树器，尚未完整对齐 HRC。** 八人 15BB 和九人 20BB 的原版/独立求解均已完成固定预算对照，但逐手牌混合策略仍有差异。锦标赛 ICM/MTT/KO/PKO、FGS 阈值模型、约束存储、CI、抽水与静态 BF/RP 已有独立实现和各自有限域证据。八人 ICM PKO 的真实 60m 对照已完成，BTN 逐手 TV 为 4.3081 个百分点，仍不能宣称策略等价。新增控制表单的浏览器验收与后端数值验收分开记录。现有 `e0873922bdca438ba02e226571cf3569` 八人 seed43 任务、检查点及图表保留；当前 8765 服务不为本批开发重启。

## 状态与证据口径

- **implemented**：独立应用已有可执行路径；“partial”表示只覆盖指定模型或配置。
- **verified**：列明原始字节码、真实 HRC GUI/保存、独立 oracle、浏览器或回归测试，说明各自证明什么。
- **missing**：用户功能、模型分支、输入域或验收证据尚缺。开发中不是 verified。

页面区分四种模式：自定义简化模型（2–6 人、翻后过牌至摊牌）；固定 ChipEV 对照（2/8/9 人已登记树）；锦标赛研究（固定树，奖金/外桌/赏金可编辑）；自定义原生四街树（2–10 人、独立 Simple/General 规则、固定本机翻后桶）。自定义原生与完整存档已通过真实 HTTP 训练/恢复/续跑；新增控制表单待集中浏览器验收。固定预设不受影响。

**本批功能验收进展：** 8766 测试服务上，ICM/MTT × none/KO/PKO 六组合各1,000样本，根与前五人fold后的BTN均返回169类数据；有样本行的频率归一、金额相对EV有限、没有ChipEV参考混入，导出配置一致。纯赏金 `[0]`、6类非法输入拒绝、100→200累计续跑新建任务且源任务保持100、历史17条含原seed43均通过。见 [HTTP报告](../reports/hrc-tournament-http-ui-contract.json) 和 [复跑脚本](../analysis/hrc-tournament-ui/http_contract_check.py)。这是接口功能验证，1,000样本不能用来比较均衡精度；真实浏览器已检查 MTT PKO 的 BTN、金额 EV 与无参考矩阵，见 [截图](../reports/ui/hrc-tournament-mtt-pko.png)。

## 收益、锦标赛与赏金

| 功能 | implemented | verified | missing / 验收条件 |
|---|---|---|---|
| 无抽水 ChipEV | 有：简化模型及原生四街固定树 | [八人](HRC-8MAX-15BB-BTN.md)、[九人](HRC-NATIVE-COMPARISON.md)真实存档/策略对照；[HU LP](HRC-HU-INDEPENDENT-BENCHMARK.md)另有最佳回应检验 | 多人未证明均衡等价；每类策略仍可能明显不同 |
| 普通 ICM | 有：简化及原生奖金收益链路 | [原始 kW 41 例](../reports/hrc-original-icm-validation.json)与[终局权益143例](../reports/hrc-original-bounty-validation.json)含普通ICM；六组合功能测试 | 更广实际训练配置的同源GUI/保存对照；不能把数学子过程等价推为策略等价 |
| 同手多人淘汰与名次奖金 | 有：原生终局权益按开局筹码定淘汰名次 | [原始终局权益143例](../reports/hrc-original-bounty-validation.json)使用显式finalChips/killerSets；最大数值误差1.14e-13 | 此探针不调用原版结算或MTT；结算→击杀→权益全链仍按具体场景验收 |
| MTT ICM / 外桌筹码 | 有：原生MTT及外桌输入 | [原始MTT72例](../reports/hrc-original-mtt-validation.json)，含100外桌阈值分支，native最大误差1.14e-13 | 仅正存活筹码、有限输入域；不同淘汰/大场/实际GUI完整场景需另验 |
| 固定 KO | 有：固定及自定义原生收益配置 | [原始终局权益143例](../reports/hrc-original-bounty-validation.json)含KO、显式击杀集合及守恒；HTTP六组合 | 更广边池实际击杀、原版GUI/训练端到端场景；此数学探针不执行原版settlement |
| PKO | 有：逐人完整赏金及即时支付比例 | [原始终局权益143例](../reports/hrc-original-bounty-validation.json)、六组合HTTP；[八人60m真实训练对照](HRC-8MAX-15BB-PKO.md)，树4786节点语义一致 | BTN逐手TV 4.3081 pp，单独种子不是置信区间；不同策略环境EV差不能当loss |
| 未来赏金权益 | 有：按筹码占比分剩余池 | 原始终局权益探针含对应剩余池；UI模型说明明确 | 不是未来每次击杀完整博弈，不称精确未来击杀概率 |
| FGS 与盲注增长 | partial：ICM可带KO/PKO的固定排序推/跟/过跟阈值递归；深度、下一盲注与工作预算已接入 | [原始31例/2399终局](../reports/hrc-original-fgs-validation.json)、[九人深1/1209终局](../reports/hrc-original-fgs-nine-validation.json)、[取消与缓存预算](../reports/hrc-fgs-controls-validation.json)；有限域金额误差≤5.69e-14 | 不支持MTT组合；每手最多三人对抗，平分分支停止递归；不是完整未来树均衡。新表单浏览器待验 |
| 抽水现金局 | 有：custom+ChipEV，NFND/GG/full，比例与同单位cap | [原版1240输入](../reports/hrc-original-rake-validation.json)及[生产Engine1240输入](../reports/hrc-native-rake-integration-validation.json)，含92个原版域拒绝；数值误差0；3模式API保存续跑 | 合成终局不全是可达行动序列；实际发牌另验。新UI待浏览器；不用于锦标赛奖金/赏金 |
| EV 展示与单位 | 有：ChipEV用BB；奖金用通用relative_ev与奖金单位 | ChipEV存档/GUI对照；六组合HTTP及MTT PKO真实页面 | HRC可按桌权益百分比显示，金额单位不同；相对首行动不是绝对锦标赛权益 |
| 泡沫因子 / 风险溢价 | 有：按任务配置计算与JSON导出，行对列矩阵 | [27场景/990有向对/1980原始权益](../reports/hrc-original-bubble-validation.json)，BF误差3.78e-15；公式字节码已审 | 原版eC/D GUI未执行；MTT另用已验权益器。静态无盲注/dead money，FGS任务也不模拟未来；新UI待浏览器 |

官方已说明 KO/PKO 适用于奖金模型，PKO 有完整赏金/即时支付部分的输入选择；这里先采用完整赏金输入，禁止将两种金额混用。[KO/PKO 说明](https://www.holdemresources.net/blog/hrc-1v4-update-knockout-bounty/)、[v4 发布说明](https://www.holdemresources.net/blog/2024-hrc-v4-release/)。公开旧文中的外桌平均赏金假设不替代本机源码及当前明确传入的外桌金额契约。

## 座位、行动树与结算

| 功能 | implemented | verified | missing / 验收条件 |
|---|---|---|---|
| 2–10 座位 / 自定义栈 | 有：独立Simple建树器及表单 | [原版943上下文/160配置](../reports/hrc-original-tree-builder-validation.json)、5个真实完整树；[HTTP2/3/6/10人](../reports/hrc-custom-native-http-ui-contract.json) | 任意配置不是逐一验证；起始范围暂all，不等范围仍缺；新表单浏览器待验 |
| SB/BB 与普通 ante | 有：原生可配置，与筹码同单位且最多4位小数 | [原版建树探针](../reports/hrc-original-tree-builder-validation.json)与[HTTP异BB单位](../reports/hrc-custom-native-http-ui-contract.json) | 原版有限短栈/ante域；结果按配置BB换算，浏览器待验 |
| BB ante、skip SB、moving button | 有：BB ante两优先级、skip SB、moving button表单及配置 | [原版Simple探针](../reports/hrc-original-tree-builder-validation.json)、[HTTP](../reports/hrc-custom-native-http-ui-contract.json)；[General研究](../reports/hrc-original-general-builder-validation.json)含2857 moving-button成对上下文；[生产配置训练测试](../tests/test_hrc_custom.py) | moving button影响未来手演化，本手拓扑不因此改变；新UI浏览器待验，非穷举 |
| 单/双/BTN straddle | 有：独立建树与新表单 | [原版建树边界探针](../reports/hrc-original-tree-builder-validation.json)含三种straddle | 至少3人；跨街/短栈输入域仅有限探针，非穷举 |
| Fold/check/call/raise/shove | 有：独立Simple候选生成与状态转移 | [原版建树](../reports/hrc-original-tree-builder-validation.json)：HU5、8人4786、9人6629/12193、PKO4786节点及行动一致 | 任意通用/自定义脚本仍缺；lB低级step越界不能当合法候选证明 |
| 最小加注、短全下重开、有效栈上限 | 有：独立Simple规则；验证范围有限 | [原始8例](../reports/hrc-original-tree-validation.json)与[943建树上下文](../reports/hrc-original-tree-builder-validation.json) | 更多组合/长短全下链覆盖，不能据有限集合宣称所有状态等价 |
| 主池/边池、退还、并列、奇数筹码 | 有无抽水路径 | [原始7例](../reports/hrc-original-settlement-validation.json) +独立结算测试；原版finalChips与potDetails奇数筹码有返回差异 | 覆盖更广投入/折叠/并列组合；只记录返回差异，不能推断UI商业后果 |
| 最大累计参与人数 | 有：原生2–10参数，新UI可编辑 | 原版建树上下文、固定完整树及自定义HTTP | 到上限后强制fold；不能按当前未fold人数重置；新UI浏览器待验 |
| 翻前 simple/general 尺寸 | 有：按街Simple/General选择；Simple常用字段、General完整JSON | [Simple及5整树](../reports/hrc-original-tree-builder-validation.json)、[General 5714上下文/270配置/38设置](../reports/hrc-original-general-builder-validation.json)、[真实PKO生产训练测试](../tests/test_hrc_custom.py)、[7个UI状态回归](../reports/ui-tree-policy-state-validation.json) | General新UI浏览器待验，任意完整树数值不全；探针执行固定哈希脚本，产品不执行用户JS |
| 翻后 geo、flop cbet/donk、SPR全下、末街 | 有：独立Simple规则、常用表单与完整JSON | [原版建树及5整树](../reports/hrc-original-tree-builder-validation.json)、自定义HTTP；General设置另有纯上下文研究 | 广泛节点/内存域仍待验证；不代表动态抽象；新表单浏览器待验 |
| 创建后动态加/改/裁剪行动 | missing | v4公开列出动态行动编辑；静态handlers | 修改后节点身份、策略失效/保留政策、撤销与重算；不能沿用旧收益假称更新完成 |
| 脚本化建树 | partial：声明式Simple JSON独立生成；内置General独立函数已有研究证据 | 原版固定脚本为规格证据，Simple候选与General上下文已对照 | 任意用户脚本、沙箱与诊断未实现；不把JSON编辑器称JavaScript执行器 |

## 牌、抽象、范围与求解控制

| 功能 | implemented | verified | missing / 验收条件 |
|---|---|---|---|
| 发牌、blockers、七牌排名 | 有：独立 C++ 发牌和位评估 | [独立牌/抽象](../analysis/hrc-desktop/INDEPENDENT-CARDS-ABSTRACTION.md)：30,008牌评估对照；原始7牌探针2,318例 | 不等范围/固定board子树需另验；未穷举所有七牌 |
| 固定1024/256/256桶 | 有：读本机已安装资源，不调用原版solver | 三profile5,400同牌样本、canonical board全数组、1,326 preflop类一致 | 专有数据仍是本机依赖；不是独立生成抽象或全部27profile均验证 |
| 其他桶规模 / 抽象训练 | missing | 64flop已有全域映射证据 | 其余profile兼容与数值；独立聚类训练目标、距离、采样和稳定性 |
| 动态perfect/strict/balanced/relaxed | partial：独立动态key及按玩家映射、native lookup；尚非网页用户功能 | [原版216 key/53映射](../reports/hrc-original-dynamic-validation.json)，含41668224映射比对；[native53例/53411280查询](../reports/hrc-original-dynamic-native-validation.json)无差异 | 训练入口、范围/board/subtree工作流和可移植存档尚需产品验收；纯映射探针不等于动态子局策略等价 |
| 指定公共牌、runout、combo细节 | missing；当前后街只展示桶 | UI明确桶不对应固定169起手牌 | board过滤、冲突牌阻断、每组合显示；不能以桶矩阵冒充专用翻后分析 |
| 起始范围输入 | 简化模式支持加权范围；固定预设all | 范围解析与未采样行为已测 | 原生任意范围、弃牌范围bunching、范围导入格式与权重联合分布 |
| 节点逐手牌/桶锁定 | 有：翻前169锁及后街27/31桶锁；格式25拒绝；表单与JSON | [原版121锁例](../reports/hrc-original-policy-validation.json)、[27/31生产201步](../reports/hrc-original-extended-store-native-validation.json)逐位一致；真实API训练/保存/迁移 | 新UI待浏览器；任意整树策略等价未证明。非空约束禁用旧原版reference，special虚拟fold不可锁 |
| 整体行动频率锁/edge | 有：各街format63、targets/edges、观测聚合 | [原版24序列/864快照](../reports/hrc-original-policy-validation.json)，锁+频率174814比较误差≤1.43e-14；API真实训练 | 单线程CAS成功语义；合成更新不代替整树收敛。不能同节点同时频率与逐桶锁；新UI待浏览器 |
| 子树定向采样 | missing | 原版作用域与上游冻结有[官方解释](https://www.holdemresources.net/docs/monte-carlo-sampling/) | 保留上游策略/card removal、只更新所选范围；进度计数语义与完整树区别 |
| 专用翻后子局 | missing | 原版从翻前复制范围/权益/结构，后续独立；[官方说明](https://www.holdemresources.net/docs/postflop/) | 固定board、bunching、独立配置、动态抽象、未来runout和锁限制 |
| v4抽样与遗憾更新 | 有：独立单线程限定路径 | [嵌套遍历](../reports/hrc-original-nested-traversal-validation.json)200例、3,200快照；固定预算多人实际对照 | 不同模型/锁/格式/子树路径；不复现多线程调度；有限预算差异仍存在 |
| v3/旧阈值后端/FGS子求解 | partial：产品v3/v4选择，FGS独立阈值路径 | 原始小链路52项、v3实际API与FGS原始数值报告 | 任意历史后端/配置不全；不能以v4路径代替所有求解后端 |
| 采样预算、种子、取消、部分结果 | 有：累计样本、时间/CI目标、硬时间预算；目标OR、显式停止原因 | 原生60m任务、取消/资源上限回归；新控制已接API与UI | 新停止目标UI待浏览器；并行worker配置未提供；预算完成不等于收敛 |
| 继续采样 / reset regret / reset strategy | 有：新任务续跑；两个累计量10⁻²⁰重置；显式reject/preserve/reset格式迁移 | 同RNG/数组续跑、[HTTP完整存档恢复后100→200](../reports/hrc-custom-native-http-ui-contract.json)、[原版迁移12例](../reports/hrc-original-store-migration-validation.json)、实际锁/格式存档API | 迁移兼容域由后端限制，reset可丢节点累计；累计样本不清零；新UI待浏览器 |
| CI/精度 | 有：近期策略漂移值、窗口历史、停止目标 | [原始216快照](../reports/hrc-original-ci-validation.json)，CI误差5.69e-14；独立记录真实时钟 | 合成1/2/4节点与重建mq窗口；不是统计置信区间、多人可利用度或均衡证书；新UI待浏览器 |
| 策略误差与均衡检验 | partial | HU有限零和游戏LP/BR；八人/九人策略TV/MAE、多种子诊断 | 多人整树可利用度/后街桶误差未认证；不同策略环境EV差不能当loss，两个种子不是CI |

## 保存、恢复、展示与工作流

| 功能 | implemented | verified | missing / 验收条件 |
|---|---|---|---|
| 169策略、样本、相对EV、节点路径 | 有 | 原版GUI数值/保存解码、网页键盘/窄屏/dirty隔离 | 确切区分平均策略/当前遗憾策略、uniform combo加权/真实reach；后街具体combo仍缺 |
| HRC `.hrcz` 读取与规范化比较 | 有研究脚本，不是任意档案产品导入 | [HU](../analysis/hrc-desktop/HU-SAVE-CROSSCHECK.md)、[9人](../analysis/hrc-desktop/NINE-SAVE-CROSSCHECK.md)真实GUI无训练载入另存，格式23/25核心相同 | 锁、subtree、新收益配置、损坏/未知格式和资源缺失；不能承诺全部档兼容 |
| `.hrcv` / JSON完整互操作 | partial：格式静态恢复、研究JSON与CSV导出 | [保存布局](HRC-TREE-PERSISTENCE.md)；实际输出只限已验格式 | Viewer裁树、其他格式27/31/63、原版可读写回放与未知版本策略 |
| 独立可移植保存/恢复 | 有：.plabz含树/模型/身份/计数/完整检查点，可选资源；场景JSON/摘要另列 | [两个真实原生任务HTTP往返](../reports/hrc-custom-native-http-ui-contract.json)，策略精确相同并继续训练；FGS/锁/存储格式API另测 | 非打包资源需匹配本机缓存；本UI报告不冒领全部依赖独立/损坏包域测试；新UI浏览器待验 |
| 旧任务与新草稿隔离 | 有：任务配置不可变；复制结果为草稿与显式迁移 | 原浏览器dirty隔离、MTT PKO页面、HTTP旧seed43保留及导入新任务 | 新约束/自定义/档案的浏览器跨模式交互待验；8765保留 |
| Hand history导入/批量分析/奖金模板 | missing | 本机插件handler、官方产品说明入口 | 房间格式解析、匿名化、数据验证；不属于当前场景JSON导入 |
| 合成hand history / 专用导出 | missing | [v4功能说明](https://www.holdemresources.net/blog/2024-hrc-v4-release/) | 能重建策略抽样事件与第三方tracker互操作；不得只改扩展名 |
| 本地结果分享/Viewer/完整报告 | partial：本地JSON/CSV和研究图 | 已有图与下载验证 | 可移植只读viewer、结果身份/资源依赖说明；外部发布不是本轮默认动作 |

## 第一批 UI/API 契约

`engine="hrc_tournament"` 与原 `hrc_v4_research` 分开；`benchmark` 仍从封存预设选择，不能改筹码/盲注/行动尺寸。`utility` 为 `icm` 或 `mtt_icm`；`payouts` 为常规奖金序列；`other_stacks` 为每位外桌玩家的BB筹码；`bounty.mode` 为 none/ko/pko，`amounts` 与本桌玩家一一对应，`other_amounts` 与外桌筹码一一对应，`immediate_fraction` 表示即时支付占完整赏金比例。

UI 复用现有预设、字段、错误、任务、矩阵组件；只在 `/api/meta.tournament` 提供能力时增加锦标赛组。KO使用单一金额自动展开全场，PKO显示本桌逐人金额与外桌列表。后端仍为规范化/校验权威，UI不得悄悄裁剪奖金、补造外桌人数或替用户变换赏金含义。切换普通ICM时当前提交不包含外桌；草稿隐藏输入可在切回MTT时恢复。

任务结果使用 `job.config` 快照及明确 `utility_unit`，手牌读通用 `relative_ev`，BB只用于ChipEV。没有同配置原版reference便不展示HRC对照；锦标赛EV不和原ChipEV基准混比。首批六模型组合、非法字段和HTTP存档/续跑已验；新控制的浏览器交互、错误、旧任务切回和窄屏/键盘仍需逐项验收。

## 分阶段完成标准

1. **收益链路**：原版纯方法与独立oracle对照 + 同配置GUI/保存对照 + 固定树真实训练。单测通过不替代完整链路。
2. **自由树与全配置**：独立从声明式规则生成2–10人四街树，位置/盲注/ante/straddle/短全下/参与人数/结算规则有边界矩阵；不再依赖原版导出的行动树。
3. **锁、子树、抽象、FGS**：每个功能都有明确状态转移、数值对照和保存恢复，前端不显示无实现开关。
4. **用户工作流**：输入→预览→训练→停止/续跑→查看→可移植保存→恢复可复核；所有金额和近似假设明确；保留版本、资源、配置、计数与种子身份。
5. **最终对齐判断**：逐功能列出误差范围与未覆盖域；即使全部工作流可用，也不以“同预算总开池率接近”证明HRC数值等价。

## 自定义原生与完整存档本批契约

`engine="hrc_custom"` 从参数独立生成 Simple/General 四街树，2–10 人、all 起始范围、固定本机1024/256/256桶。筹码、小盲、大盲、ante、外桌筹码统一为用户输入的基准单位；后端整数筹码为输入×10000，输出筹码按实际大盲换成BB。UI不混用固定预设的BB输入约定。普通/BB ante两优先级、straddle、skip SB、累计参与人数、节点预算和 moving button 可编辑；后者只影响未来手位置演化，不旋转当前手。

常用参数与完整JSON用显式选择器切换。切换前校验当前输入，错误不会覆盖；完整JSON保留常用面板未呈现的Simple字段，不执行JavaScript。翻前/翻后可独立选择General，任一General会隐藏禁用Simple表单，按policy ID只合并本模式默认值；模式往返保留各自草稿。只要关闭翻后下注便注明过牌至摊牌近似。筹码币值/奖金单位显示、旧结果/新草稿隔离复用已有组件。

`/api/meta.persistence` 控制完整存档入口；`can_export_archive` 要求存在完整检查点。`GET /api/jobs/:id/archive?resources=0|1` 由浏览器原生下载.plabz，默认不带约330MB抽象资源，恢复需要匹配本机缓存。`POST /api/import` 接收最多1GiB二进制，返回新任务，不覆盖旧任务或左侧草稿。普通场景JSON与摘要JSON仍保留独立名称；下载已发起不等于下载已完成。此批静态UI审计无发现，真实HTTP原生训练、导出、导入及续跑通过；浏览器验收单独记录，不能由HTTP检查替代。

## 新增控制的验收分层

训练配置使用元数据限制，不把60m写为所有任务永久上限。新增 v3/v4、CI、时间/CI停止目标、FGS、后街存储27/31、逐类锁、频率目标、reset/migration、现金抽水与静态 BF/RP 已接前端。默认无约束/无FGS/无抽水保留既有研究预设；包含新模型或约束的任务不会匹配旧原版参考。

[静态UI审计](../reports/premium-training-controls-ui-audit.json)无发现，仅说明可检查的结构规则；新增交互的实际浏览器验收尚待主线程集中执行。后端原始数值证据、API工作流、页面体验、固定预算策略误差分别列证，不相互代替。当前最主要的产品缺口仍包括原生非all起始范围及bunching、指定board/独立翻后子局、子树定向训练、动态抽象完整接线、动态行动树编辑、hand-history与批量工作流、原版Viewer互操作。不能把本轮新增表单等同于全面完成HRC对齐。


General 与 moving button 已纳入本批集中浏览器验收。固定公共牌子局的入口草案保存在 [DESIGN.md](../DESIGN.md)：从明确源节点创建独立任务，展示board、继承范围、权益/底池与来源身份，并区分原树定向采样。API尚未冻结，不在页面放置无实现入口，矩阵仍将该完整工作流列为缺失。
