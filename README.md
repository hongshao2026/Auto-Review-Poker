# HRC / REA 研究环境

安装日期：2026-11-04（Asia/Shanghai）。用途：HRC 代码结构与算法的学术研究。现已完成工具安装、REA 静态调查，并实现独立的本地翻前研究应用。

## 先运行应用

克隆后，先按 [Python 环境设置](APP-README.md#启动) 安装依赖。可以用 `python -m pytest -q tests/test_core.py tests/test_server.py` 运行本地冒烟测试。HRC 对照与性能复现实验依赖本机 HRC 资源、存档或采样报告，需要按各实验的说明准备。

需要从代码求解翻牌、转牌或河牌时，可使用 [本地翻后 Solver](postflop_lab/README.md)。它提供 Windows 命令行、Python API、ChipEV、ICM 和 Pio 预设导入。

双击 **Start-Preflop-Lab.cmd**，或打开已运行的 [翻前研究台](http://127.0.0.1:8765)。支持有限尺寸的加注、跟注、全下决策树、169 类手牌抽样策略，以及 chip EV / ICM。

续局采用翻前结束后过牌到摊牌；没有翻后权益实现模型，不等同于 HRC 的深筹码解。使用步骤、实现范围与验证见 [APP-README.md](APP-README.md)。静态证据见 [HRC-FINDINGS.md](research/HRC-FINDINGS.md)。

## 已安装

| 组件 | 版本 | 用途 |
| --- | --- | --- |
| REA | 6.8.0 | Codex MCP 连接、证据记录、二进制分析工作流 |
| REA 官方 skill | version 49 | reverse-engineer-anything 及配套参考文档 |
| REA-Prompts | commit ccb02b89721dd7d466beb17004a89d6bc25f5b02 | 8 个研究提示技能 |
| Node.js | 24.22.2 | REA 专用运行时 |
| Eclipse Temurin JDK | 21.0.13+9 | Java 编译、字节码检查和反编译运行时 |
| Vineflower | 1.12.0 | Java 21 类文件反编译，主要 Java 工具 |
| CFR | 0.152 | 第二种 Java 反编译结果，供交叉检查 |
| Ghidra | 12.1.4 | PE / DLL 静态分析与原生代码反编译 |

大型工具位置：`D:\Tools\REA-Research`。当前工作目录：`D:\Users\Shao\Documents\ChatGPT\REA`。现有全局 Node.js 未被升级，研究命令使用单独的便携版。原有 Python 和 Git 继续使用。

8 个提示技能位于 `C:\Users\Shao\.codex\skills`：

- reap-00-install-and-verify
- reap-01-getting-started
- reap-02-feature-tracing-any-program
- reap-03-native-binary-exploration
- reap-10-vulnerability-research
- reap-15-version-comparison-and-crash-work
- reap-16-long-running-investigations
- reap-prompt-writing-tips

从指定仓库安装后，为这 8 个 SKILL.md 的 description 字段加了 YAML 引号；上游未加引号的冒号会导致解析失败。正文保持原样。完整上游仓库保存在 `external/REA-Prompts`。

官方技能由 REA 安装器放在 `C:\Users\Shao\.agents\skills\reverse-engineer-anything`。新技能在后续轮次可被发现；本会话的 REA MCP 工具已经自动加载并成功调用，无需为这次接入再重启。

## 验证结果

- `rea doctor --client codex --provider ghidra --json`：所选 Codex + Ghidra 范围 `healthy: true`。
- 独立 MCP 握手：服务器 `rea 6.8.0`，返回 229 个工具定义。
- 当前 Codex 会话：实际调用 `inspect_analysis_settings` 成功，确认已连接。
- Java：自编 Java 21 record 经 javac 编译、javap 检查，Vineflower 和 CFR 均成功反编译。
- 原生分析：REA 调用 Ghidra 静态读取本机 `C:\Python313\python.exe`，得到 x86_64 PE、119 个已识别过程、81 个已定义字符串。未运行该程序作为分析目标。
- Codex 配置：比较备份与新配置后，确认改动仅限 REA 连接。

`environment_healthy: false` 是全环境诊断值，包含未配置的可选引擎。当前选定的 Codex + Ghidra 范围已经通过。229 是服务器公布的工具定义数量；Android、IDA、Frida 等工具各有额外依赖。本次按静态研究需要安装，npm 安装使用 `--omit=optional --ignore-scripts`。REA 对 Windows Ghidra 的原生分析支持目前标为实验性；Java JAR 优先使用 Vineflower / CFR。

验证数据保存在 `reports/`：`portable-tools.json`、`installed-skills.json`、`rea-setup-plan.json`、`rea-setup-result.json`、`rea-doctor-after.json`、`rea-mcp-tools.json`、`java-verification.json`、`rea-native-smoke.json` 和 `verification-summary.json`。

## 使用入口

在 PowerShell 中运行：

```powershell
Set-Location 'D:\Users\Shao\Documents\ChatGPT\REA'
. .\Activate-Research.ps1
rea doctor --client codex --provider ghidra --json
```

这个激活脚本只调整当前 PowerShell 会话的运行环境，并提供 `rea`、`vineflower`、`cfr`、`ghidra` 命令。

打开 Ghidra 图形界面：双击本目录的 `Start-Ghidra.cmd`，或者在激活环境后运行 `ghidra`。

可重复验证 Java 工具：

```powershell
python .\scripts\verify-java-tools.py
```

## HRC 文件识别

安装位置：`D:\Program Files\HRC`。

主插件：`D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar`。

这是 Java / Eclipse RCP 结构。主插件内发现 986 个类文件，均为 class major version 65（Java 21）。目录同时含数据插件和原生库。哈希、清单和插件 manifest 见 `reports/hrc-installation-inventory.json`。这些是安装文件证据，不等于已恢复原始源码或已理解求解算法。

后续静态研究已经梳理主插件、界面入口、脚本建树语义和求解器标签，详见 `research/HRC-FINDINGS.md`。HRC v4 的精确采样、抽象与剪枝算法仍属未知；本项目的研究引擎按公开方法独立实现。

## 配置与回退

REA 连接配置：`C:\Users\Shao\.codex\config.toml` 中的 `[mcp_servers.rea]`，通过绝对路径启动 D 盘的 Node.js 和 REA，并指定 JAVA_HOME / GHIDRA_INSTALL_DIR。

原配置备份：`C:\Users\Shao\.codex\config.toml.rea.backup`。之后若有其他配置变化，回退时应只处理 REA 区块，不宜覆盖整份配置。

安装用版本、下载 URL、校验摘要保存在 `reports/portable-tools.json`；npm 锁文件位于 `D:\Tools\REA-Research\rea\package-lock.json`。不要移动 D 盘工具目录，否则需要更新连接配置与激活脚本。

研究工作目录已迁移到 D 盘；应用虚拟环境、结果和分析输出都保存在当前目录。旧安装报告中的 C 盘工作路径是安装时记录，不能作为当前启动路径。

## 官方来源

- [REA-Prompts](https://github.com/JoasASantos/REA-Prompts)
- [REA 安装与支持范围](https://rea.tools/get-started/)
- [REA 源码](https://github.com/morluto/rea)
- [Node.js 24.22.2](https://nodejs.org/dist/v24.22.2/)
- [Temurin JDK](https://adoptium.net/temurin/releases/?version=21)
- [Vineflower 1.12.0](https://github.com/Vineflower/vineflower/releases/tag/1.12.0)
- [CFR](https://www.benf.org/other/cfr/)
- [Ghidra 12.1.4](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build)
