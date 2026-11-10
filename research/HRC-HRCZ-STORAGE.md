# HRC4 节点存储、原生 checkpoint 与终局向量互通

本轮实现位于 `preflop_lab/hrc_hrcz_storage.py`、`preflop_lab/hrc_hrcz_leaves.py` 和
`native/hrc_hrcz_leaves.cpp`。它们不调用原版求解器；原格式存储探针只在隔离类加载器中运行已审计的数值类。
ZIP 打包、settings/state 映射、gametree 重放与桌面实际打开由上层模块负责，不能仅据本报告宣称所有 `.hrcz` 均可继续求解。

## 原始证据与已验证范围

对象为本机 `net.holdemresources.calculator_4.1.0.202603231401.jar`，SHA256
`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`。
下列行号是 `analysis/hrc-deep/sources/{ordinal}/{class}.java` 的反编译证据；方法描述符用于消除混淆后的重名。

| 类、方法 | 行号 | 直接事实 |
|---|---:|---|
| `pY.a(Lnet/holdemresources/internal/mf;[B)V`，0736 | 84–115 | 32 字节头；锁行位于存储 payload 之前；`mx.a(III[B)Lmx;` 恢复底层；按 action index 升序重放锁 setter |
| `pY.a(Ljava/io/OutputStream;Ljava/util/Map;Lnet/holdemresources/internal/ld;Ljava/util/function/Predicate;)[[J` | 118–210 | 每个节点写格式、桶数、锁定数；终局格式 1024 为向量列表的 float32 逐项编码 |
| `mt.a()[B`，0027 | 118–131 | 序列化前 flush；double 转 float32 后写入 |
| `mE.b()V`，0021 | 42–45 | LongAdder 由 `Math.round(raw[0])` 重建 |
| `mw.a([B)V` / `mw.a()[B`，0018 | 116–149 | format31 分块内存的序列化仍是连续浮点数组 |
| `mz.a([B)V` / `mz.a()[B`，0025 | 95–154 | 63 前缀为 targets、min、max、edges、底层 format；再读写连续 raw；重建 counter/shared/edge adders |
| `my.a(I[D)Lnet/holdemresources/internal/my;`，0017 | 163–186 | clamp 当前锁；合计大于 1 时缩放其他已锁动作；并非整体归一化 |
| `mh.<init>(Lmf;Ljava/util/List;LlK;Lmi;)V`，0040 | 23–55 | 活跃座位按累计投入 `lK.b+lK.c` 降序，同额按 live 序号升序；向量数 `3^(live-1)` |
| `mh.a(Ljava/util/Map;)V` / `mh.c()Ljava/util/List;` | 94–121 | 原始终局 payoff 经过结算/权益映射填入，按 outcome index 顺序存储 |
| `me.a(I[I)[I` / `me.a([I[I[I)I`，0042 | 4–33 | 三进制 outcome index 与 best-so-far 比较序列互转 |
| `lH.a(LlK;[ILjava/util/List;Z)LlE;`，0699 | 89–223 | b+c 是投入，a 是剩余筹码；未被跟注的投入退回、边池、整数余数及淘汰者赢家集合 |

表中简写类描述符 `Lmf;` 等均在 `net/holdemresources/internal/` 包下。
探针通过精确 JAR hash、platform parent、受限白名单类加载；逐类 SHA 在机器报告中。
无 GUI、授权初始化、业务入口、原版训练循环被执行。

`scripts/validate-hrc-hrcz-storage.py` 的 **58 组 / 232 项** 全部通过：
23/25/27/31/63 的原始 raw、加载后的真实 counter、部分/完整锁、原版再序列化字节一致；
包含 4097 桶跨块边界、float32 `.1+.9` 不足 1 与 `.4+.6` 超过 1 的重放差异。
证据：`reports/hrc-original-hrcz-storage-validation.json`、`analysis/hrc-deep/hrcz-storage/`。

## 二进制布局

所有整数与浮点数均 little endian。`nodedata.dat` 以 int32 节点总数开始；记录顺序独立于节点 ID。
每记录头为 `<6iQ>`：`node_id,payload_bytes,reserved0,format,bucket_or_vector_count,locked_action_count,reserved64`。
保留 reserved 字段以便无损重写。每锁行是 `action:int32` 加 H 个 float32；随后为底层 payload。

令 K 为动作数、H 为桶数，R 为遗憾和，A 为平均策略累计量，D 为 EV 分母：

| format | 连续 raw 布局 |
|---|---|
| 23 | `[clock, H * (R[K], D, A[K])]` |
| 25 | `[clock, sharedA[K], H * R[K]]` |
| 27 | `[clock, sharedA[K], H * (R[K], A[K])]` |
| 31 | `[clock, sharedA[K], H * (R[K], D, A[K])]` |
| 63 | 前缀 `targets[K],min,max,edges[K]` float32 + `underlying_format:int32`；raw 同 31 |
| 1024 | `vector_count * player_count` 个绝对权益 float32，非每手牌访问次数或在线均值 |

63 的 underlying 仅允许 23/25/27/31 进入训练。未知格式保持 opaque payload 可往返，但明确禁止训练。
同一街混合不同底层格式也明确标为只读；目前主内核的 storage profile 是按街配置，不能静默转换。
格式 25/63 上的桶锁、非法数值/维度、无法兼容的频率目标等同样报告具体原因。

## 单位、时钟和未知历史

ChipEV 原档使用 GUI 筹码 `internal / 100`。原生训练使用净 BB：
`source_absolute = native_net * (internalBB / 100) + initial_internal_stack / 100`。
奖金、ICM、KO、PKO、MTT、FGS 的比例为 1，偏移是独立计算的对应初始权益。
只缩放 R 与 frequency edge；D/A/clock/target/锁概率不变。
63 的 min/max 必须做仿射变换，不能漏掉 baseline。原始未观测极值 sentinel 保留；
若旧最大值仍卡在 `Float.MIN_VALUE` 而实际历史收益全负，丢掉的负最大值无法重建，转换报告显式记录这一歧义。

导入原档时仍使用 HRSOLV03：`samples=0`、每桶 `visits=0`、root sums=0，随机流明确以新 seed 启动；
raw 保留原档 float32 加载值，内部 `updates=Math.round(raw[0])`。
不可把 updates 置零，否则下一次缓存刷新会清除历史 t 权重。
原档没有原 RNG 状态、真实全局迭代数和逐桶 visits，因此不得推造这些字段。

compact 的 `import_provenance={format:'hrcz',source_sha256,saved_update_counters}` 进入身份。
`import-history.json` 保留未知项说明。原生保存以 `B=updates-sum(visits)` 输出
`imported_updates_baseline`/`history_unknown`；保存 raw float32 counter 的精确来源仍在 compact provenance 中。
reset 清除时钟后 B 可为 0，但来源仍是导入档。导入后 100 次再续至 300 次，与同源连续 300 次的 checkpoint 字节相同，
覆盖六种格式/底层组合；这证明本地分段恢复，**不证明恢复了 HRC 原 RNG 或原并发执行轨迹**。

HRTREE04 flag256 只标识已验证的 HRC float32 来源锁/targets，允许 K×float32 epsilon 的可解释舍入偏差。
普通用户新配置仍保持原严格规则；不额外归一化导入锁。
`runtime_locks` 独立重放原 setter 的 clamp/缩放顺序，而原 payload 保留源字节用于无改动往返。
导出已训练 checkpoint 时用实际 counter、shared adders、edge adders 模拟原 save flush，再量化为 float32；不改原 checkpoint。

## 独立终局生成与真实存档对照

`generate_leaves(compact,resources,output)` 返回 `(records,baseline,metadata)`。
原生 helper 只读取独立重放的状态、规则和 equity 配置；不读取原 fmt1024/payoff。
按 mh/me 排列 rank representatives，调用生产结算与权益模块，再恢复原档绝对单位。
包含 live 零额外投入玩家；不能用 eligible pot layers 的并集替代 live 数。
输出头的终局记录数与真实 leaf 数核对，每次上限 **2,000,000 个向量**；Python 在 native prepare 前预检。
`evaluate_baseline(...)` 返回同单位初始权益，不枚举终局、不加载标准牌桶资源；FGS 仍需其机会数据。

`scripts/validate-hrc-hrcz-leaves.py` 在独立生成后才读取原 payload 作为 oracle：

| 真实原档 | 终局记录 | 向量 | float32 数值 | 结果 |
|---|---:|---:|---:|---|
| HU 10BB push/fold 初始 | 3 | 5 | 10 | 每字节相同 |
| 八人 15BB ChipEV 60m | 2585 | 13289 | 106312 | 每字节相同 |
| 八人 15BB ICM/PKO 50/30/20 初始 | 2585 | 13289 | 106312 | 每字节相同 |
| 合计 | **5173** | **26583** | **212634** | **最大误差 0** |

三份 `state.eqpre` 与独立 baseline 也精确相同。
报告 `reports/hrc-original-hrcz-leaves-validation.json` 保留存档/源文件/程序 hash、两边聚合 payload hash、计数与耗时。
测试另覆盖纯 ICM、固定 KO、PKO 的 HU 胜/平/负已知结果、累计投入与初始筹码次序不同的 me index、预算提前拒绝。
这些真实存档没有 FGS、MTT 或现金 rake；其数学模块有其他原始探针对照，但本报告不把那些等同于真实 `.hrcz` 终局向量实测。

## 复现

```powershell
.venv/Scripts/python.exe scripts/validate-hrc-hrcz-storage.py
.venv/Scripts/python.exe scripts/validate-hrc-hrcz-leaves.py
.venv/Scripts/python.exe -m pytest tests/test_hrc_hrcz_storage.py tests/test_hrc_hrcz_leaves.py -q
```

上述 pytest 本轮 **47 passed**。生成工具的编译缓存按源码 hash 隔离，不覆盖用户原始 HRC 存档。
