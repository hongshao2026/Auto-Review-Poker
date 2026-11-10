# HRC 建树、下注规则与保存恢复：原始字节码证据

2026-11-04。本报告研究本机 `net.holdemresources.calculator_4.1.0.202603231401.jar`，SHA256 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。结论限定于这个制品。没有运行 HRC 桌面程序、访问授权流程或改变安装目录。

已经确认：脚本输出通过 `mM → mF → lB/lC` 进入有限行动树；`maxactive` 是参与者限制而非简单的当前未弃牌人数；合法候选的尺寸钳制和低级状态变换有区别；完整保存是五个 ZIP 条目的结构/策略快照，Viewer 保存有选择地丢弃策略数据，单独 JSON 只保存配置。主代理隔离调用原始类的8个下注用例、7个边池用例全部满足各自断言；一次下注失败纠正了对低级 `lB.a(long)` 的过度解释，三个边池用例则复现了两种返回数据的奇数筹码归属不一致。

## 1. 证据口径与索引

`analysis/hrc-deep/source-index.json` 保留 JAR 原始 ordinal、大小写、类摘要和反编译源码路径。此报告主要引用 `analysis/hrc-deep/tree/{ordinal}/decompiled/*.java`，同目录 `bytecode.txt` 为 `javap -p -c -s`，`identity.json` 为原始类 SHA256 和工具命令。反编译产生的同名字段、同名不同返回类型、局部变量窄化都不能直接作为 Java 源码重编译；下文用 **字段名:descriptor** 和 **方法名完整 descriptor** 区分。

原始下注实验：[探针源码](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalTreeProbe.java)、[静态初始化审读](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/PROBE-REVIEW.md)、[8/8 实测报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-tree-validation.json)。实验仅初始化允许名单内的原始纯规则类，用 JAR 摘要锁定输入、精确描述符反射、平台类加载器隔离；`mI` 的输入供应器是探针生成的代理，候选和状态计算是原始 HRC 字节码。边池实验见第5节；持久化布局仍为静态证据，尚未执行原始保存/加载函数。60个本分支提取类及源/字节码摘要在 `analysis/hrc-deep/tree/evidence-manifest.json`。

此前 REA inventory/summary 记录在 `analysis/hrc-static/rea-evidence.json`，本次沿用该制品识别，不操作共享 REA 会话。主代理全 JAR 索引的 call ordinal 是访问事件序号，不是字节码偏移；本报告写“偏移”的数字均来自 javap 方法内偏移。

## 2. 从脚本尺寸到树边

`qu.c(Lnet/holdemresources/internal/lB;)Z` 直接调用 JavaScript `canFlatCallPreflop(new qp(context))` 并取 `asBoolean()`；`qu.b(Lnet/holdemresources/internal/lB;)Ljava/util/Collection;` 调用 `getSizingsPreflop`，逐数组元素或单值 `asLong()`。不是把字符串当最终树结构。`qp` 提供盲注、actor、历史、下注次数、minimum、有效全下、pot/geometric 等辅助值。[qu.java:29](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-static/selected/0682/decompiled/qu.java:29)、[qp.java:69](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-static/selected/0669/decompiled/qp.java:69)

`jP.a(Lnet/holdemresources/internal/kG;)Lnet/holdemresources/internal/mF;` 从 hM 取得 cap，选择基本、预设 UI 或脚本 policy，建立 `mM(mI,mH,IntFunction<mK>)` 后交给 `mF`。脚本高级模式使用同时实现翻前/翻后接口的 `qq`。`mM` 的翻前 policy 为 null 时只给 `context.b:J`（有效全下）且不允许普通 flat-call；翻后 policy 为 null 时无翻后尺寸、无继续街的许可。[jP.java:469](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-static/selected/0103/decompiled/jP.java:469)、[mM.java:11](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0044/decompiled/mM.java:11)

实际生成器是 `mF.a()[Lnet/holdemresources/internal/rD;`。当 `lB.a()Z` 为真才读取尺寸：preflop 调 mJ.b(context)，其余街调 mJ.a(context)，每项按 `min(max(requested, minimum), maximum)` 钳制，再排序、去重。对应 javap 主方法偏移144–270；静态 lambda `(JJJ)J` 的0–10就是两次 Math 调用。之后生成 fold/check、符合规则的 call、按升序的 raise 边。因此同一个脚本请求不能绕开此层的 effective cap；短全下 `minimum>maximum` 会被钳制成 maximum。[mF.java:48](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0047/decompiled/mF.java:48)

`canFlatCallPreflop=false` 不能理解为“删除所有 call”：当 call 已达到自己的/有效对手上限，或没有 raise 候选时，生成器会保留 call；普通非全下 call 才经过参与人数和 policy 检查。`mF.a(Lnet/holdemresources/internal/lB;)Lnet/holdemresources/internal/mF;` 在无 actor、policy 允许且尚未 river 时进入下一街，并对零剩余筹码的 actor 自动补 call。[mF.java:27](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0047/decompiled/mF.java:27)、[mF.java:134](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0047/decompiled/mF.java:134)

存在 **check 节点前的 fold 反事实子树**：`mK.a` 不加；`mK.b` 加 fold 后以 check/必要时fold走到river；`mK.c` 加带 `mL` policy 的 fold 子树；`mK.d` 加普通 fold。`mL` 把翻后尺寸映射到最邻近的有效全下或 geometric-hint(0.75)。这些子树不能直接解释成真实玩家面对 check 时的可选 fold 策略；求解端 `mf` 识别第二子节点 action.kind==lz.b（CHECK）并阻止动作0被策略选择。`lz.a/b/c/d` 的 FOLD/CHECK/CALL/RAISE 映射由 `ly` 工厂与显示方法双重确认。[mF.java:91](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0047/decompiled/mF.java:91)、[ly.java:16](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0718/decompiled/ly.java:16)

## 3. 座位、状态与参与者上限

`kG` 默认座位语义：正常 SB=n−2，BB=n−1；三人以上 BTN=n−3，HU BTN=0；skipSB 则 SB=−1、BTN=n−2。`lB` 私有构造器的 actor 扫描采用循环座位顺序：正常翻前起始0，单straddle起始1，双straddle起始2，button straddle起始BTN+1；翻后 HU 从1，其余从n−2，skipSB从n−1；有本街历史从最后 actor+1 开始。扫描排除弃牌、已满足行动和下注条件的座位，遇到当前最后加注者则结束。完整描述符：`<init>(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lC;Ljava/util/List;II)V`。[kG.java:27](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0908/decompiled/kG.java:27)、[lB.java:42](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0695/decompiled/lB.java:42)

`lC` 是 immutable-style 筹码/行动快照，关键字段如下；同名不能省略 descriptor。

| 字段 | 观察到的含义 |
|---|---|
| `a:[J` | 每座位剩余筹码 |
| `b:[J` | 本街投入；fold 时该座位投入移入 c:[J] |
| `c:[J` | 前街/已扫入底池的投入，含已弃牌投入 |
| `a:J` | 单独保留的 BB ante 金额 |
| `a:I` | street，0翻前，1/2/3翻后 |
| `b:I` | 参与者 bitmask；check/call/raise加入，fold不清除，进街不清除 |
| `c:I` | 已弃牌 bitmask |
| `f:I` | 本街循环终止标记：首个check/call可设定，raise替换 |
| `d:I` | 本街 bet count，翻前从1开始，每次raise递增，包括短全下 |
| `e:I` | 最近raise后的call计数，raise归零 |

数据流依据 `lC.a(Lnet/holdemresources/internal/ly;)Lnet/holdemresources/internal/lC;`（字节码文件第263行起）、`a()LlC;`（574行）、`b()LlC;`（605行）；[lC.java:86](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0692/decompiled/lC.java:86)。`lC.a(kG):lC` 支持普通 ante、BB Ante Ante First、BB Ante Blind First、skipSB 与单/双/button straddle。blinds tuple 顺序是 `[BB,SB,ante]`；ky.a()J 的基准 stake 随 straddle 变为 BB/2BB/4BB。[lC.java:199](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0692/decompiled/lC.java:199)

**maxactive 的实质**：在 `mF.a():rD[]`，actor 如果已经在 `b:I` 参与者 mask 中，直接允许；否则统计 `remaining==0 OR participantBit` 的人数，达到 cap 时只返回 fold 边。因此已经参与后再弃牌的人仍占名额，零筹码的座位也被计入。未发生自愿加注前的普通 call 检查还把已匹配当前 bet 的座位（例如 BB）纳入人数；此处有不同于普通入口检查的 guard。这是计算树的参与者限制，不等同于桌上总座位数或当前未弃牌人数。[mF.java:54](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0047/decompiled/mF.java:54)

`hM.a()I` 在 enumerated 分支固定3；Monte Carlo取配置b，默认4。`hL.d()V` 的编辑校验是 `value>1 && value<=10`，故该 UI 的 Monte Carlo maxactive允许2–10；不能由此断言内部所有配置入口都严格执行同一上限。[hM.java:10](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0256/decompiled/hM.java:10)、[hL.java:45](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0238/hL.java:45)

## 4. 最小加注、短全下、重开：原始类实测

`lB.a:J` 是生成器读取的 minimum，`lB.b:J` 是 maximum，`lB.a()Z` 返回 minimum>0。私有构造器在没有足够筹码、当前 bet 已等于有效对手上限、或仅一位未弃牌且有筹码玩家时禁用加注。相关构造器偏移433–507；最大额 `min(actor remaining+street, maximum opponent remaining+street)` 在756–805。

本街 minimum 算法经字节码确认：翻前初值 `(minimum,acceptedRaise)=(2*base,base)`，翻后 `(base,0)`；按历史遍历 RAISE，只有 `raiseTo>=minimum` 才设置 `minimum=2*raiseTo−acceptedRaise`，并以该raiseTo替换 acceptedRaise。短于 minimum 的 raise 不更新这两个变量。若当前 actor 在最后被接受的 raise 起的历史后缀已经行动，minimum设−1。偏移543–596初值、617–659更新、671–739行动后缀检查。[lB.java:109](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0695/decompiled/lB.java:109)

原始探针盲注 `[100,50,0]`、座位 `[BTN,SB,BB]`，筹码 `[2000,400,2000]`。主代理实测结果如下，金额是内部 centichips。

| 路径/输入 | 原始状态与真实候选 |
|---|---|
| 初始BTN；请求150/300/9999 | minimum200、maximum2000；raiseTo200/300/2000 |
| BTN raiseTo300 → SB | minimum500、maximum400、canRaise=true；生成400短全下 |
| SB short shove400 → 尚未行动的BB；请求450/500/600/9999 | minimum500；生成500/600/2000；450确实被提升到500 |
| BB call400 → 原BTN | minimum−1、canRaise=false、没有raise候选 |
| 另一分支BB请求450、低级归一化为500 → BTN | minimum700、重新允许raise |
| 筹码改为[2000,400,1000]，初始请求9999 | mF只生成raiseTo1000 |
| 使用上述真实1000边 | BTN还剩1000，action.allinFlag=true：标志包括有效全下 |
| 同一状态**直接低级调用**lB.a(9999) | 先命中自有筹码上限2000，BTN剩0；不是mF生成的合法候选1000 |

这里的500阈值不是凭字段名字猜测：探针同时读取状态与原始 `mF.a():rD[]` 的实际子边。它反映这个制品的可复现行为；不据此断言所有桌面配置相同或宣布扑克规则缺陷。与常见“当前bet400+最后完整增量200”算法的600结果不同，是独立重建时应明确处理的兼容性问题。

**低级调用的边界**：`lB.a(J)LlB;`（字节码文件第790行）先 `max(request,minimum)`，若达到自身总筹码就直接截到自身总筹码；只有 else 分支再截到有效对手最大额。因此不能把它称为完整合法动作验证器。`lB.a(ly):lB` 主要检查 actor/street 以及CHECK是否合法；真正树的尺寸边界由 mF 先行钳制保证。第一次7例中第7的错误预期已保留在 `analysis/hrc-deep/probes/tree-first-validation.json` 和 `tree-first-output.jsonl`；修正分层理解后8/8通过，没有丢弃反例。

## 5. 边池与筹码结算（原始类7例实测）

核心 `lH.a(Lnet/holdemresources/internal/lK;[ILjava/util/List;Z)Lnet/holdemresources/internal/lF;` 接受终局筹码快照、未弃牌玩家排名、行动历史和是否返回pot明细。`lK` 从 lC 的扫街状态取得剩余/本街/以前贡献、active seats、street、BB ante。[lH.java:86](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0699/decompiled/lH.java:86)

观察到的顺序：先累加每位总投入；若最大投入超过第二大，退还差额（上限是该座位 current contribution）。为未弃牌者构造 lJ，按**排名值降序、贡献升序、seat降序**排列；lJ.compareTo(Ljava/lang/Object;)I 字节码7–24/25–42/43–54分别验证这三层比较。按可获胜者的贡献层级计算可分配池，各座位的投入包括已弃牌资金；单独BB ante只加第一池。平局按整数商分配，余数进入 `var28[首位同分者]`，pot明细 `lG` 记录却把余数传给最后同分者，精确偏移分别749–767和768–789。此差别已由下面的原始类实验复现，但不能直接当成UI错误。[lJ bytecode](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0697/bytecode.txt)、[lH.java:146](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0699/decompiled/lH.java:146)

每层可按 `lH.a(JJLnet/holdemresources/internal/lK;Ljava/util/List;)J` 扣 rake，存在费率/总cap/规则检查；无rake singleton为 `new lH(0.0,0,lI.a)`。同时建立淘汰玩家对应获胜者集合供KO处理。最后显式验证 `原筹码总和 == 返回筹码总和 + rake`，失败抛异常。故边池不是简单把全部底池给单一赢家，也不能从手牌rank推断只有chipEV模型。

主代理已审读并执行 [OriginalSettlementProbe.java](D:/Users/Shao/Documents/ChatGPT/REA/scripts/java/OriginalSettlementProbe.java)，[审计记录](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/SETTLEMENT-PROBE-REVIEW.md)、[7/7断言报告](D:/Users/Shao/Documents/ChatGPT/REA/reports/hrc-original-settlement-validation.json)。探针用真实lC私有纯赋值构造器建立**合成终局快照**，调用真实lK扫街、lH直接rank重载、lF/lG取值；不是声称逐步回放了所有合法下注历史。独立预期按升序贡献阈值分池，与HRC按赢家排序循环不同；无rake，所有tie例的获胜者投入相等。

| 用例：总投入 / rank（大值胜） | lF最终筹码 | lG逐池award合计 | 结论 |
|---|---|---|---|
| [100,200,300] / [3,2,1] | [300,200,100] | 同左 | 多层资金分配符合独立分池 |
| [300,200,100] / [1,3,2] | [100,500,0] | 同左 | 最大投入者输牌仍回收未被跟注100 |
| [100,100,100]，seat2弃牌并剩50；rank[3,2,99] | [300,0,50] | [300,0,0] | 弃牌投入计入池，剩50不属于award |
| [100,100,100] / [2,2,1] | [150,150,0] | 同左 | 无余数平局一致 |
| [100,100,1] / [2,2,1] | [100,101,0] | [101,100,0] | 1 centichip余数的seat归属不同 |
| [100,100,100,1] / [2,2,2,1] | [100,100,101,0] | [101,100,100,0] | 3人平局也复现差异 |
| [100,100]+独立BB ante1 / [2,2] | [100,101] | [101,100] | BB ante奇数池复现差异 |

全部最终筹码符合独立分池预期，全部总筹码守恒。后三例的`pass`明确包含 `detailAgreement=false` 的可证伪断言，**不是声称两种数据一致**。目前只证明原始函数返回的finalChips与potDetails在这些输入上有不同余数归属；未观察桌面UI使用哪条返回路径，也没有证明商业后果、收益偏差或真实资金错误。

## 6. 范围锁定与节点策略保存

`fj.execute` 针对选中 `pc`，只在 `pc.b()I==0`（preflop）翻转 `pc.a(Z)V`；`pf.a(Z)V` 把操作转发给 editor 的 `(lR,actionIndex,bool)`，最终 `mf.a(IZ)V` 以 `mx.a(IZ) Lmx;` 替换存储对象。范围编辑 `mf.a(I[D)V` 同样替换 mx。锁对象是**节点的一条 action 对各bucket的策略值**，不是对某个座位无条件起手概率作锁定。[fj.java:9](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0531/decompiled/fj.java:9)、[pf.java:77](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0844/decompiled/pf.java:77)、[mf bytecode:664](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0013/bytecode.txt:664)

另有 `fi` 的整体频率/edge约束，包装为 `mz`，formatId=63；b:[D存目标频率，NaN代表未锁定；c:[D为edge，底层formatId保存在c:I。序列化头大小 `4+8*(actionCount+1)`：N个float目标、两个float范围值、N个float edge、int32底层formatId，其后底层float策略数据。不要把此约束和上面的逐bucket范围lock混为一谈；求解数学另见 solver 报告。[mz.java:90](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0025/decompiled/mz.java:90)

`pY.a(Lnet/holdemresources/internal/mf;[B)V` 恢复时先解出锁数组，按formatId/actionCount/bucketCount创建 `mx`，再逐 action调用 `mf.a(I[D)V` 和 `mf.a(IZ)V` 重施锁。因此完整保存包括锁定值及锁标志，而不只有界面颜色或最终概率导出。[pY.java:84](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0736/decompiled/pY.java:84)

## 7. `.hrcz` / `.hrcv` / JSON 的具体保存布局

`bS` 的菜单名称分别为 Complete Save / Viewer Save / Hand Config。完整 writer descriptor 为 `(Lnet/holdemresources/internal/mf;Lcom/google/gson/JsonElement;Lcom/google/gson/JsonElement;Lorg/eclipse/core/runtime/IProgressMonitor;Ljava/nio/file/Path;Ljava/util/function/Predicate;Ljava/util/function/Predicate;)V`。它先建立节点ID映射，再在目标目录创建临时文件，ZIP method=0（STORED），ZIP64 Always，完成后非取消才 REPLACE_EXISTING 移动到目标路径。不是 Java ObjectOutputStream；该完整快照链未发现加密步骤。[bS.java:103](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0387/decompiled/bS.java:103)

| ZIP entry | 内容 |
|---|---|
| `settings.json` | pj.a:JsonObject，含handdata、eqmodel、treeconfig、engine等 |
| `state.json` | eqpre/eqpost 数组 |
| `gametree.dat` | 节点ID/父子映射、street/actor、具体动作编码 |
| `nodedata.dat` | 节点策略存储、锁定范围、叶节点向量 |
| `idx.dat` | 每节点结构和数据偏移/长度，供随机访问 |

以下为文件内偏移。`oD.a([BI)S/I/J` 的小端reader已由主代理原始类实验逐字节对照Python `int.from_bytes` 验证。pZ/pY的直接oD writer为小端；调用第三方BitConverter的writer/reader尚未独立执行，其小端布局来自同一格式中与oD读写路径相配套的静态推导，仍待实际保存回放验证。不能把已测oD扩展为已测第三方BitConverter，也不假定ByteBuffer默认字节序。

### `idx.dat`

无文件头，nodeId=n 在 `24*n` 处，24字节一条：+0 int64 treeOffset，+8 int32 treeLength，+12 int64 dataOffset，+20 int32 dataLength。偏移相对于对应 entry 数据起点，不是整个 ZIP 起点。`pZ.a(Ljava/io/OutputStream;[[J[[J)V` 写四项；`qi.a(Ljava/lang/Integer;)[B` seek `idxBase+24*id`；qf分别加treeBase/dataBase。[pZ.java:49](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0738/decompiled/pZ.java:49)、[qi.java:11](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0723/decompiled/qi.java:11)

### `gametree.dat`

文件头 int32 nodeCount，随后每条共同头12字节：+0 int32 nodeId，+4 int32 parentId（根−1），+8 byte类型（1决策/2叶），+9 byte actionSequenceLength，+10两字节childCount（叶写0）。决策类型另有 +12 byte street、+13 byte actor；从+14开始每个动作8字节，再跟childCount个int32 childId。叶类型从+12直接开始动作。排除的child写−1。reader把sequenceLength作为Java signed byte、childCount作为signed short读取，不应把这份实现解读为支持任意无符号长度。

动作64位打包：bits0–3 kind（0fold/1check/2call/3raise），bits4–7保留0；bits8–11 actor，bit12 allinFlag，bits13–15 street，bits16–63 amount。CALL amount是增量，RAISE amount是raise-to。`pX.a(Lnet/holdemresources/internal/lA;)[B` 偏移21–46生成中间标志、52–116映射kind、116–130打包；`qm.a():List` 明确拒绝bits4–7非0，以48位mask恢复amount。[pX.java:6](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0735/decompiled/pX.java:6)、[qm.java:65](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0726/qm.java:65)

树读写的方法为 `pZ.a(Ljava/io/OutputStream;Ljava/util/Map;Lnet/holdemresources/internal/pi;)[[J` 与 `pZ.a(Ljava/io/InputStream;[BLjava/util/function/Function;)Lnet/holdemresources/internal/qm;`。ID显式记录，不能依赖HashMap迭代顺序；reader检查duplicate ID。恢复映射时还比较子节点数和street，发现不同树抛 `Tree structures do not match`。[pZ.java:62](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0738/decompiled/pZ.java:62)、[pZ.java:178](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0738/decompiled/pZ.java:178)

### `nodedata.dat`

文件头 int32映射节点数；每记录32字节头：

| 偏移 | 宽度 | 决策节点 | 叶节点 |
|---|---|---|---|
| +0 | 4 | nodeId | nodeId |
| +4 | 4 | payloadLength，不含32字节头 | 同左 |
| +8 | 4 | 保留0 | 保留0 |
| +12 | 4 | mx.c() formatId | 1024 |
| +16 | 4 | bucketCount | vectorCount |
| +20 | 4 | lockedActionCount | 0 |
| +24 | 8 | 保留0 | 保留0 |

决策payload先逐锁定action写 `int32 actionIndex + bucketCount*float32 weight`，再拼 `mx.a()[B` 的内部数据。叶payload为逐向量float32；每向量宽度恢复为 `payloadLength / 4 / vectorCount`。`pY.a(InputStream,mf,qc,pi):V` 检查节点映射数、节点ID与类型，并拒绝 `payloadLength+32>268435456`；这是看到的检查，不意味着对不可信文件的完整安全证明。writer对于Viewer未选中的节点不会写payload，索引length保持0，但文件头仍按映射节点数写；完整loader与Viewer读取路径因此不能任意互换。[pY.java:19](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0736/decompiled/pY.java:19)、[pY.java:118](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0736/decompiled/pY.java:118)

### 完整恢复、Viewer与配置JSON

完整恢复 `eI.a(Lorg/eclipse/swt/widgets/Shell;Ljava/nio/file/Path;Lorg/eclipse/core/runtime/IProgressMonitor;)Lnet/holdemresources/internal/bM;`：读settings/handdata/eqmodel创建kG；读state equity数组；pZ读具体gametree；qa恢复abstraction/board等；以 `ml.a(null,new qo(kG,root),new mi(kG,...))` 重建mf树；pY灌回策略/锁；创建editor。这条路恢复**已保存的具体树**，不是重新执行尺寸脚本才能恢复核心状态。[eI.java:84](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0539/decompiled/eI.java:84)

Viewer保存 `bR.run(IProgressMonitor):IStatus` 的分支1：树节点predicate为 parent==null 或 parent.street<=selectedRootStreet+1；数据predicate为节点是lR且node.street==selectedRootStreet。所以会保留部分下一街结构，但只存选定街的策略payload。载入时`.hrcv`后缀由eI.execute传布尔给eJ，eJ选择eP。eP取ZIP entry实际dataOffset，用RandomAccessFile和qf按需读；老`index.dat`有qj兼容路径。qf数据缓存1000节点，结构/索引各100000；dataLength==0返回null。[bR.java:25](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0388/decompiled/bR.java:25)、[eP.java:39](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0538/decompiled/eP.java:39)、[qf.java:58](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0733/decompiled/qf.java:58)

独立 `.json` 由 `bS.a(Lnet/holdemresources/internal/bM;Ljava/nio/file/Path;)V` 只写pj.a的Gson JSON，没有state/树/策略。`jS.a(Shell,Path):JsonObject` 对JSON检查handdata，或从ZIP抽settings，然后导入手牌配置流程。`jK` 的scriptfile调用pj.a(String,JsonElement)，实际写入 **pj.b** 元数据；上述save只写 **pj.a**。jP的scripted treeconfig只标 `mode=scripted`，故这条JSON路径不能承诺把外部脚本源码一起带走。完整hrcz因保存具体树仍能重建已建出的行动结构。[bS.java:58](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0387/decompiled/bS.java:58)、[pj.java:36](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/sources/0826/pj.java:36)、[jS.java:28](D:/Users/Shao/Documents/ChatGPT/REA/analysis/hrc-deep/tree/0109/decompiled/jS.java:28)

## 8. 对独立重建的可验证约束

已有本地 Preflop Lab 是另一个研究实现；不能把以上发现自动宣传成已实现功能。下一步有价值的对照目标是：把座位/强制下注/有效cap/短全下的8例作为独立规则回归，显式选择是否兼容HRC的500阈值；分别表示“曾参与”“未弃牌”“零筹码”，避免将maxactive混同table-size；区分策略bucket的动作概率锁、整体频率约束、起始范围；保存结构、策略累加状态、锁和abstraction配置时分别版本化。

目前仍未完成：真实用户生成hrcz/hrcv的读写往返；所有straddle/BB-ante/不同起始street组合；不同贡献额并列获胜者的更多边池情况、非零rake模式；Viewer截树条件在复杂subgame的实际交互；所有mx格式的独立兼容解码。本文没有声称兼容导入完整HRC存档，也没有运行商业软件去验证界面显示。
