# 原版 HRC 9 人 40BB 全树持续续算

**状态更新：用户已改为 3 人 40BB 验证，本 9 人任务不再继续。** 切换前确认原版已经空闲，最后记录 CI113.806461、新增 680,549,750 次，未达 CI10。最新原版结果另存为 `analysis/hrc-desktop/partial-stopped-for-three40bb-20261107.hrcz`，保留此前存档。持续监测已结束，v2 观测器卸载返回 true；后文是该 9 人任务当时的配置和记录，不代表当前仍在运行。

用户于 2026-11-07（中国时间）明确选择持续运行到 CI＜10，接受可能数天。

原先的一小时诊断已结束，存档最后 CI 为 156.1144。本次从该原版部分结果的独立工作副本继续，没有重置 regret 或策略。2026-11-07 **00:17:57 +08:00** 通过原版 Nash Calculation 确认运行：HRC 4.0、Full Tree、Until CI value is reached、CI Target 10.0、两项 Reset 均未选，8 个实际 worker。494,055 个节点，233,802 个决策点，9 人均 40BB，ChipEV。

本次正式采样没有自动时长截止，没有后台 Cancel 定时器。工作副本为 `analysis/hrc-desktop/nine40bb-large-ci10-working-20261107.hrcz`；开始时 SHA-256 与原一小时部分结果完全相同。原文件和用户之前的 Hand1 备份均保留。

原 PID 34604 已正常退出。本次原版 PID **24968**，主窗口 **2624894**。重启后的进程仍用 8 个 worker；下一次启动的用户偏好已恢复 Automatic。运行期间没有启动自研大型训练与其争用 CPU。

最初原版记录：续算后 +16.416 秒 CI153.9356，+66.910 秒 CI149.1102，+112.213 秒 CI148.6187。重启会重新开始 CI 测量历史，策略则从原版 float32 存档恢复；因此不能把本次 CI 轨迹当成前一小时无间断的同一条记录。界面 ETA 仍会波动。

## 后台运行及结果保存

持续监测进程来自 `scripts/watch-hrc-ci-longrun.py`。每 5 秒仅检查所选 HRC 窗口并增量读取经过验证的原版 CI 记录。它持有 Windows 系统执行请求，防止空闲自动睡眠，允许显示器关闭；这不能阻止人为休眠、关机或断电。监测不依赖持续占用聊天模型。

只有排除 synthetic/陈旧记录、原版数值 CI 严格小于 10，且原版连续显示空闲后，才标记目标完成。后台进度窗口隐藏时同时参考所选进程 CPU 活动，避免把仍在计算误认成结束。发现其他采样文件时，停止自动认定结果归属，保留证据待核对。

运行中原版 Save/Save As 均被原程序禁用，未测试或启用周期保存。达到目标后监测才请求 Save As；必须先核对保存框的默认文件名与独立工作副本一致，再写入全新结果文件。新存档必须通过 settings/树哈希和节点数核验。遇到其他文档或弹窗时保留状态并报告需要处理，不输入其他文件的保存路径。

预期最终文件：`analysis/hrc-desktop/ci10-original-long-20261107-run/nine40bb-fulltree-ci-below10-final.hrcz`。当前尚未生成，不应将运行状态当作完成结果。

另一个本地等待进程 `scripts/finalize-hrc-ci-longrun.py` 在完成保存或确认空闲后卸载本次观测 hook。它校验实际 JVM 创建时间和 v2 agent/sink 哈希，要求卸载返回 true；不会停止 HRC。观测器 v1 的卸载问题及 v2 自测结果见 `research/HRC-CI-OBSERVATION-CLEANUP-ERRATUM.md`。

## 状态及证据位置

`analysis/hrc-desktop/ci10-original-long-20261107-run/`：

- `status.json`：实时 CI、是否运行、监测心跳及最终保存状态。
- `start.json`、`gui-handoff.json`：正式启动配置、PID、窗口及观测器身份。
- `original-ci.jsonl`：原版 mr 构造参数的直接观测。
- `monitor-events.jsonl`：监测事件；`monitor-stderr.log`：异常输出。
- `finalizer-result.json`：结束后观测器清理结果，尚未结束时不存在。

正常状态是 `monitoring`，最终成功状态是 `completed_and_saved`。`ci_target_reached_save_needs_attention` 表示 CI 已到但保存仍待处理；`idle_without_verified_ci_target` 表示提前空闲且没有确认目标，均不能当作已完成保存。若 HRC 或监测进程意外退出，应读取这些证据再恢复，不能静默宣称仍在运行。

监测判断和文档名绑定测试：9 passed。v2 隔离自测验证原构造字段保持不变、只记录一次、从注册它的 Instrumentation 卸载成功，卸载后的构造不再产生记录。此任务仍在运行，CI＜10 的实际完成时间尚未知。
