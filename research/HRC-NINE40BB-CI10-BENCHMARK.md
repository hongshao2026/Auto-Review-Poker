# Original HRC nine-player 40BB CI10 benchmark, 2026-11-06

The original HRC run **did not reach CI < 10 within the declared one-hour
safety bound**. The final original numeric CI was **156.114432399059**.
Cancel was posted at 3600.253 seconds; the original was observed idle by
3602.259 seconds. The target-achievement duration remains **null**. This
establishes a one-hour non-completion observation for this particular stochastic
run, not an estimated number of hours needed to finish.

The complete machine-readable record is
`reports/hrc-nine40bb-ci10-original-20261106.json`; regenerate it with
`.venv/Scripts/python.exe scripts/report-hrc-ci-benchmark.py`. That script only
reads retained evidence. It does not start HRC or sampling.

## Controlled configuration and starting state

Original installed artifact SHA256:
`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`.
The CPU is an Intel i5-13600KF, with 14 physical cores and 20 logical processors.
Original PID 34604 was restarted normally after changing the worker preference
from Automatic (0) to 8. A narrowly scoped runtime read of the original `oc`
worker field verified **8**, beyond merely inspecting the preference text.

The formal dialog was HRC 4.0 (Default), Full Tree, Until CI value is reached,
target 10.0; Reset Regret and Reset Strategies were both unchecked. Screenshot:
`analysis/hrc-desktop/screens/ci10-eight-workers-ready-dialog.png`.

The original loaded only
`analysis/hrc-desktop/nine40bb-large-ci-initial-20261106.hrcz`, SHA256
`bd2928a90e3ce9450eb8ed1dff89b5c60d0d29b02a8956fa034b31f09c55003a`.
Its saved float32 root counter is 10,000,250. This was a reload of the previously
initialized archive, with float32 save quantization. That initialization used the
previous Automatic setting, expected 20 workers. The timed formal run used 8.
Initialization, archive loading, restart and instrumentation preparation are
excluded from the measured formal interval. Therefore this is not an identical
RNG/initial-storage match to an independently initialized native solver.

The archive settings equal
`.research-cache/deep-tree-optimization-20261106/large-settings.json`: nine
40BB stacks, no ante, unraked ChipEV, max active four, open 2.3BB, 3bet
2.5x/3.5x, 4bet 2.1x/2.5x, 5bet all-in, flats `[0,1,1,1,0]`, no SB completion.
The saved tree has 494,055 total nodes, including 233,802 decisions and
260,253 terminals. Abstraction counts are 169/1024/256/256; exact resource
identifiers are retained in the report's configuration/settings.

## Actual observation

The observed original OK control was posted at **09:24:26.523 UTC**. The
independent native benchmark had already exited; no native training, Java
compilation, target attach or explicit GC was performed during this interval.
The complete original CI series contains 203 checkpoints, not OCR estimates.

| Observation | Wall seconds from OK | Original run samples | Original CI |
|---|---:|---:|---:|
| First CI | 16.137 | 4,799,750 | 1243.5446646765615 |
| Second CI | 70.390 | 20,774,750 | 910.841913638195 |
| Final CI | 3601.022 | 987,374,750 | 156.114432399059 |

The last CI was emitted while the original settled the normal Cancel request,
roughly 0.77 seconds after that request. The final GUI text retained before idle
was `CI: 156.67 [0.265mio h/s, 987.1 m] ETA: 110.3h`; it was one displayed
checkpoint behind the final exact constructor record. These values are not
contradictory. The ETA is the original's extrapolation, **not measured completion
time**. The final snapshot count divided by elapsed wall time is approximately
0.274 million samples/second; it is not a separately instrumented solver-only
throughput figure.

Whole-process CPU time increased by 28,840.203125 seconds. Wall time is not
CPU time. No original method-boundary wall timer was installed. The maximum
one-second-sampled working set was 7,775,977,472 bytes; process lifetime peak
working set at the end was 7,789,199,360 bytes. The memory figures include the
JVM, resources and application. Windows PagefileUsage here is process commit,
not measured paging I/O.

Raw evidence directory:
`analysis/hrc-desktop/ci10-original-run-20261106/`.

* `original-ci.jsonl`: original CI arguments and timestamps.
* `win32-observations.jsonl`: one-second cached window text and process counters,
  explicit OK/Cancel events, and idle evidence.
* `observation-result.json`: terminal observer result, cancellation true,
  target reached false.
* `progress-dpi-aware-confirmation.png` and `progress-near-1h-dpi-aware.png`:
  correctly scoped original progress screenshots. The first automatic screenshot
  used virtualized DPI coordinates and is not relied on.

## CI meaning and observation boundary

Existing source and bytecode evidence establish that the fourth argument of
`net.holdemresources.internal.mr.<init>(IJJD)V` is the smoothed original
`mq.a:D`, used directly by the stopping predicate and formatted to two decimals
for display. There is no additional display scaling. `bM.java:110` and
`analysis/hrc-deep/sampling-controls/bM-bytecode.txt:1123` establish the strict
comparison. `mq.java:31–45` and `lT.java:30–40` select all preflop decision
nodes for a preflop Full Tree root; there is no visited-count/reach filter.

The observation agent appends a call immediately before RETURN in that one
constructor. It records the already calculated four arguments and does not
change original fields, returns, solver updates, selection or stop logic.
Each CI checkpoint adds a small file write; one-second Win32 polling and this
nonzero instrumentation overhead are disclosed and not subtracted. The
isolated self-test checked unchanged constructor fields, and an actual OSGi
class-loader link check used one detached synthetic record before sampling;
that synthetic record is excluded from the trajectory.

Build identity, original/transformed class hashes, exact observation-agent
hashes and the runtime worker count are in the report and
`analysis/hrc-deep/ci-runtime-observer/build-manifest.json`.

CI measures recent policy change. It is not a statistical confidence interval,
exploitability measurement or proof that every hand's EV is accurate. A fresh
worker restarts CI history even when retaining strategy storage. Initial 10m
sampling is real training, but its `10000L` argument is a UI refresh interval,
not a ten-second hard stop; see `research/HRC-SAMPLING-CONTROLS.md`.

## Saved result and cleanup

The partial trained result was saved to the new unique file
`analysis/hrc-desktop/nine40bb-large-ci10-partial-1h-eightthreads-20261106.hrcz`.
SHA256: `e16b516528cc5ad2c3f8e70551be19699b3c06fccd6a0d9885bcb302123146bd`.
Its five core ZIP members are present, and the saved root float32 counter is
997,427,520. That counter includes the initial state and rounding; it is not
the exact formal run-loop count. The source archive SHA is unchanged.

Settings are identical, and all 494,055 original/final tree records are byte
identical when aligned by node ID. The physical record order changed on saving,
so raw gametree hashes differ. The shared canonical ID-order hash is
`ca11c2394b159bbdc8914f40596c4a4c0b80e6bd59fe65a295a05f949e64b163`.
Evidence: `initial-final-tree-identity.json` and `final-archive.json` in the
run directory. This verifies original-to-original preservation. The coordinator's
separate audit, `reports/hrc-nine40bb-topology-equivalence-20261106.json`, also
paired all 494,055 nodes and 260,253 terminals across engines with zero
differences on the compared training fields. It covers actor/street/children,
action kinds, bucket counts, special flags and terminal funds/fold masks. The
compact omits intermediate action amounts/forced sequences, so that audit is
not proof of every intermediate bet representation, identical policies or
identical CI trajectories. Its limitations are retained in the benchmark report.

After idle and saving, the v1 agent logged removal, but a later continuation
preflight found a retained transformer. The original unqualified removal claim
is withdrawn: see `research/HRC-CI-OBSERVATION-CLEANUP-ERRATUM.md`. Normal exit
of PID34604 before the next run cleared all its instrumentation state. This
cleanup correction does not change the retained one-hour CI values. Thread
preference was restored
to 0 and verified by reopening Preferences. This takes effect at the next
restart; the current process still has the previously initialized 8-worker
setting. The owned test document was closed and normal GC requested only after
measurement. Working set then fell to approximately 2.63GB.

The user's previously unsaved Hand1 was preserved before the restart in the
independent file
`analysis/hrc-desktop/user-Hand1-preserved-before-thread-restart-20261106.hrcz`.
No original user-named file was overwritten. After the coordinator completed
the memory-intensive audit, the backup was loaded through File -> Load Hand,
without initialization or Run. The UI again shows the user's 2BB-open hand and
`No operations to display`; screenshot:
`analysis/hrc-desktop/screens/ci10-user-Hand1-restored.png`.
The backup SHA256 is
`4ecdaf75f86d5a8f8dc2cb28ac7163fd45b792783609e862dcf04085d7b4dfb7`.
Operational status and exact cleanup actions are in `operation-state.json` and
`cleanup.json` in the run directory. No sampling remains active.

This is one original run stopped at its explicitly retained safety limit.
Neither a CI10 completion duration nor a matched-to-CI10 speedup can be claimed.
