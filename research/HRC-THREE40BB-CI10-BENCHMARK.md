# Original HRC 3-player 40BB full-tree CI10 benchmark

The original HRC reached **CI 9.992620692282749** after **469.152 seconds
(7 minutes 49.152 seconds)** from the formal Run OK action. It then stopped
automatically; GUI idle was confirmed at 471.214 seconds. No Cancel was sent.
This is an observed CI10 completion, unlike the earlier incomplete nine-player
run. It does not establish exploitability or accuracy of every hand's EV.

The machine-readable record is
`reports/hrc-three40bb-ci10-original-20261107.json`. Regenerate it without
running HRC using `.venv/Scripts/python.exe scripts/report-hrc-three40bb-ci.py`.
Raw evidence is under
`analysis/hrc-desktop/three40bb-ci10-original-20261107-run/`.

## Configuration and comparable scope

Three players (BU/SB/BB), each 40BB; no ante; unraked ChipEV; maximum active
players three. Open 2.3BB, 3bet 2.5x/3.5x, 4bet 2.1x/2.5x, 5bet all-in;
flats `[0,1,1,1,0]`; no SB completion; all-in threshold 90%. Postflop geo 66%
and all-in SPR 5, Limited donks, with original 169/1024/256/256 abstractions.
Exact settings and resource identifiers are in
`analysis/hrc-desktop/three40bb-wide-settings-20261107.json`.

The original formal Run dialog was HRC 4.0 (Default), Full Tree, Until CI value
is reached, 10.0, with both Reset Regret and Reset Strategies unchecked.
The screenshot is `analysis/hrc-desktop/screens/three40-formal-run-configured.png`.
The original runtime worker field verified eight workers. Hardware is the
Intel i5-13600KF, 14 physical cores/20 logical processors. The independent
engine did not train concurrently; its CPU slot began after original cleanup.

The saved original tree contains 3,964 nodes, 1,786 decisions and 2,178 terminal
nodes. The independent settings/tree audit paired all nodes and terminal
settlement inputs with zero differences in compared fields:
`reports/hrc-three40bb-topology-equivalence-20261107.json`. This is structural
evidence, not proof of matching policies or training dynamics. Original saved
strategy and leaf values are validation evidence and are not used to initialize
independent training.

## Initialization and formal timing

Normal New Hand initialization was observed in original PID24968. It performed
the nominal 10m samples; the saved root float32 counter is **10,000,250**.
The last active initialization observation was at 5.541s, the first idle
observation at 6.043s, and the second idle confirmation at 6.544s. Thus the
Finish-to-idle observation is approximately six seconds, including tree setup;
it is not an instrumented sampling-only duration. CPU time increased by
47.015625s. Initialization was not artificially capped at ten seconds.

Before formal sampling, a strict observation-agent raw-class identity guard
rejected a same-JVM retransformation after the JVM reordered `mr` method
records. Read-only bytecode evidence retained the identical constructor and
method instructions, but the guard was **not relaxed**. Instead, HRC was exited
normally and restarted with eight workers. PID41348 loaded the saved initial
archive; the existing tested v2 observer was installed once before first `mr`
load and passed its strict hash and original OSGi-loader link check.

Consequently, the formal run **reloaded original float32 saved storage** rather
than continuing the untouched in-memory initialization state. The initialization
was not repeated, regrets/strategies were not reset, and this boundary is
explicit when comparing with an independently initialized engine. Restart,
archive I/O and observation preparation are excluded from formal timing.

| Formal observation | Seconds from OK | Original run-loop samples | Original CI |
|---|---:|---:|---:|
| OK posted, 2026-11-06 17:11:21.365 UTC | 0 | — | — |
| First original CI checkpoint | 15.165 | 28,999,750 | 75.87100203846033 |
| First checkpoint below target | 469.152 | 946,599,750 | 9.992620692282749 |
| Confirmed GUI idle | 471.214 | — | — |

There are 31 real CI records. The exact values come from the original
`mr.<init>(IJJD)V` arguments, not OCR or an independent CI recomputation.
The detached synthetic link-check record (index -1/time 0) is excluded.
The fourth argument is the original smoothed CI used by its strict `<10`
stopping predicate. Earlier static/bytecode evidence is documented in
`research/HRC-SAMPLING-CONTROLS.md`.

Whole-process CPU time increased by 3,743.578125s; this differs from wall time.
The final CI sample count divided by formal wall time is about **2.018 million
samples/second**, including original CI checking overhead. The maximum
one-second-observed working set was 1,708,134,400 bytes. Only the three-player
test document was loaded during formal measurement. No method-boundary timer
or paging-I/O measurement is claimed. Observation overhead consists of a small
append per CI checkpoint and one-second Win32 polling; it is not subtracted.

The observer was launched with explicit `--seconds inf`, so it had no timed
Cancel. The original stopped on its own target condition. No heavy parsing,
Java compilation, attach or explicit GC occurred during formal sampling.

## Archives, preservation and cleanup

Initial archive:
`analysis/hrc-desktop/three40bb-wide-initial-20261107.hrcz`

* SHA256 `f1766896951a0b8b67ac107cf85913ea805200c71474ef00f2f0a61edc9ac536`
* Root counter float32: 10,000,250.

Final archive:
`analysis/hrc-desktop/three40bb-wide-ci10-final-20261107.hrcz`

* SHA256 `cece665313847f8c3cb87f50bf8c9682c27bd4a25cb0ccd437457d5b89333ccd`
* Root counter float32: 956,605,504.

Both are 6,909,319 bytes. The saved root counter is rounded float32 and includes
initialization; it must not be treated as the exact additional run-loop count.
The source initial archive hash remains unchanged. Settings match exactly, and
all 3,964 tree records match byte-for-byte when aligned by node ID. Physical
record order differs after reload/save, so raw tree hashes differ. Shared
canonical node-ID-order SHA256:
`7910182fcbec0e40132731344ce598938f0a1ca117388d9841605857a0a52ddd`.
See `initial-final-identity.json` in the evidence directory.

The v2 observer was removed after idle and saving; its event records
`remove_returned_true: true`. Thread preference was restored to Automatic (0),
effective on the next restart. The current JVM remains initialized for eight
workers but is idle. Normal GC ran only after timing. The final three-player
document remains displayed, and the CPU slot was released for independent
measurement.

The user-requested switch from nine players to three was preserved separately:
`analysis/hrc-desktop/partial-stopped-for-three40bb-20261107.hrcz`, SHA256
`6e5c52aff715630604f2e4fb7f72b769e94d3ba0ebe5f217bd19d539cb97448e`.
The nine-player process was already idle when this task began; no cancellation
by this task caused that earlier stop, and it is not labeled a CI10 completion.
Its source/working archives and the user's earlier Hand1 backup are retained.

This is one stochastic run. Accuracy conclusions require the independent
per-hand strategy/EV comparison and should retain initial-storage, random-stream
and scheduling differences. A matched CI threshold alone is not proof of
identical equilibrium accuracy.
