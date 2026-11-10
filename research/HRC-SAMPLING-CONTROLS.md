# Original HRC sampling controls and bounded 9-player 40BB observation

This report concerns the installed HRC 4.1 artifact with SHA256
`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`.
The REA staged workflow was reused: existing indexed sources and bytecode were
checked first, followed by scoped Win32 observation of the original GUI. No
product solver code was changed. The original user-owned, unsaved `Hand1` was
retained; the test was a separate hand and two separately named archives.

## What is established

The earlier nominal 60m original archives **did receive a formal Run Nash
Calculation**, with 50m additional fixed samples and both reset options off.
They were not merely new-hand initialization results. Opening the formal command
through the Hand menu is the recorded interaction; do not describe that old
interaction as a literal click on the green toolbar icon. It is also **not**
evidence that those fixed-sample archives had reached CI10.

The new 40BB test received automatic initialization and then a formal
`HRC 4.0 (Default) / Full Tree / Until CI value is reached / 10.0` run, with
both resets off. Its saved root counter grew from **10,000,250** to
**36,955,248**. The progress window was observed at elapsed 41.763 seconds;
the first persisted idle inspection was at 68.764 seconds. The agent sent no
Cancel during this run and observed no error dialog. **The transient numeric CI
and explicit success status were missed. Therefore this is not a verified
CI10 completion time.** No second heavy run was performed to fill that gap.

## Audit trail for earlier formal runs

Line numbers refer to `analysis/hrc-desktop/actions.jsonl` (one JSON event per
line). The screenshots retain the actual custom-table values that Windows
control-text enumeration cannot read.

| Original hand | Formal command | Options evidence | Run confirmation | Save evidence |
|---|---|---|---|---|
| Nine players, 20BB | line 133, `Hand->Run Nash Calculation` | lines 136–137; `screens/36-20bb-add50m.png` | line 138, OK coordinates in the observed dialog | lines 140–142 |
| Eight players, 15BB | line 173, same formal command | line 175; `screens/46-eight15bb-add50m.png` | line 176, OK coordinates in the observed dialog | lines 182–183 |
| Eight players, 15BB, PKO | line 243, same formal command | line 245; `screens/64-pko-run.png` | line 247, explicit observed OK handle 592948 | lines 253–254 |

The fixed-sample field is 50 million in these screenshots. Both reset boxes are
unchecked. Combined with the automatic nominal 10m initialization, this explains
the nominal 60m filenames. Exact saved float32 counters and batched stopping need
not equal the nominal filename exactly. The user-supplied CI10 screenshot is a
different stopping mode and must not be substituted for these old observations.

## Automatic initialization is real sampling, without a 10-second deadline

`analysis/hrc-deep/sources/0110/jN.java:82` calls
`bM.a(null, lV.a, 10000000L, 10000L, monitor)` after opening the new hand.
The exact invoked descriptor is:

```
bM.a(Ljava/lang/ref/WeakReference;Lnet/holdemresources/internal/lZ;JJLorg/eclipse/core/runtime/IProgressMonitor;)Lorg/eclipse/core/runtime/IStatus;
```

Fresh `javap -c -p -s` evidence is retained in
`analysis/hrc-deep/sampling-controls/jN-bytecode.txt:260`: BCI465 loads 10m,
BCI468 loads 10000, and BCI472 invokes the descriptor above.

In `sources/0393/bM.java:253`, the fixed-count stop predicate is
`count > target`. Its exact bytecode is
`sampling-controls/bM-bytecode.txt:1393`, descriptor
`(JJLnet/holdemresources/internal/mq;)Z`, BCI0–9. The second long controls
the periodic `Display.asyncExec` refresh at `bM.java:267`, verified by the
callback's BCI141–188 at `bM-bytecode.txt:1484` onward. It does not occur in
the fixed-count predicate. The progress monitor can separately cancel the job.

Thus **10000L is a UI refresh interval in milliseconds**, not a hard time
limit, polling timeout, or a “10m or 10 seconds, whichever comes first” stop.
This is independently consistent with the actual initialized archive root
counter of 10,000,250. Initialization wall time was not accurately measured in
this session and is not reported as ten seconds.

## Formal controls and their semantics

`sources/0551/ey.java:4–13` gives fresh defaults: algorithm index 0, Full Tree,
CI stopping, target10, fixed-mode sample field50m, reset state0. The handler
clones prior choices across invocations, but clears the reset state after the
run (`sources/0521/ew.java:37–45`). These are default/remembering rules; the
actual run screenshot remains the authority for this session.

| Field | Original behavior | Source anchor |
|---|---|---|
| CFR Algorithm | HRC4 default; HRC3 legacy also offered | `ew.java:115` |
| Scope | Full Tree or Selected Subtree | `ew.java:132` |
| Run Sampling | fixed samples or target CI | `ew.java:149` |
| Samples (mio.) | positive integer, multiplied by one million | `ew.java:96`, `:166` |
| CI Target | finite UI numeric field, validation at least0.01 | `ew.java:177` |
| Reset Regret | full reset of regrets and strategies | `ew.java:19`, `:191` |
| Reset Strategies | partial strategy reset, retaining regret/EV state | `ew.java:20`, `:209` |

Reset Regret selects internal state2. Reset Strategies reads true for any
positive reset state and is disabled while state2 is active. Consequently
checking Reset Regret implies both reset operations. Resets precede the added
sampling; they are not a different solver algorithm.

The CI overload is
`bM.a(Ljava/lang/ref/WeakReference;Lnet/holdemresources/internal/lZ;DJLorg/eclipse/core/runtime/IProgressMonitor;)Lorg/eclipse/core/runtime/IStatus;`.
Its stopping predicate is the cancellation flag or a non-NaN CI **strictly less
than** the target (`bM.java:110`; `sampling-controls/bM-bytecode.txt:1123`,
descriptor `(DJLnet/holdemresources/internal/mq;)Z`, BCI0–38). Reaching equality
alone does not satisfy this predicate. No fixed sample count is substituted for
this mode. CI is a recent-strategy-change convergence indicator, not a
statistical confidence interval, best-response exploitability, or proof of an
exact equilibrium. Existing isolated formula evidence is in
`research/HRC-POLICY-CI.md` and `reports/hrc-original-ci-validation.json`.
Each new worker constructs a fresh CI tracker; old strategy storage can be
retained while CI history restarts.

## Full Tree versus Selected Subtree

The original selected action resolves to its **preceding decision**. Selecting
a button open samples all cases reaching that button decision, including its
fold/call/raise alternatives and their later branches; it does not isolate just
the chosen raise branch. The UI tooltip and dispatch agree
(`ew.java:28–36`, `:54–103`, `:138–146`). Samples that do not reach the selected
decision under preceding strategies are discarded. Rare-reach lines produce a
warning; an unreachable line is rejected. The UI rejects postflop selections
with a request to select an earlier action (`ew.java:54–62`).

Full Tree passes a null selected-root reference. Selected Subtree passes a weak
reference to the selected decision. Existing independent, original-bytecode
scope comparisons are retained in `research/HRC-NATIVE-SAMPLING-SCOPE.md` and
`reports/hrc-original-native-scope-validation.json`. This GUI timing session
only ran Full Tree and adds no new measured subtree throughput claim.

## 9-player 40BB test configuration

The original saved `handdata`, `eqmodel`, and `treeconfig` exactly equal
`.research-cache/deep-tree-optimization-20261106/large-settings.json`. This was
checked from the original archive, rather than inferred from similar visible
labels. Each player has40BB; no ante; maximum four active players; open2.3BB;
3bet2.5x/3.5x; 4bet2.1x/2.5x; 5betallin; flats `[0,1,1,1,0]`; no SB completion;
unraked ChipEV. The retained initial and final archives have identical tree
SHA256 `409708ad8fe26e0c21bcf612784cf3875344bf7bf4064be0da561d456d56c796`.

The original UI reports233,802 nodes, corresponding to the **decision** count.
The actual saved tree has494,055 nodes:233,802 decisions and260,253 terminals.
The UI estimate is2.0GB. Abstract counts are169/1024/256/256; actual resource IDs
are explicit in the original settings:

| Street | Resource ID |
|---|---|
| Flop1024 | `22804b04d3732210b3f28dbaee3a59fbe7ab7a573b679ee68c876760aba76b94` |
| Turn256 | `661d702e82b930222bdd1e7cea3eef35f9306baaad628cec48713091b7e2e398` |
| River256 | `41e796828302d1cb95d18663fc2e1eee65f2831c90b26339a814d285003785a1` |

The CPU is an i5-13600KF,14physical cores/20logical processors. The original
Preferences field was **0 = Automatic**, confirmed without changing it in
`screens/ci40-worker-settings-confirmed.png`. `sources/0687/oc.java:9,30`
resolves that setting to `Runtime.availableProcessors()`; expected20workers
on this machine, not a verified creation trace or an assumed8threads. This
cannot be used as a controlled comparison against an8-worker independent run.

Before formal Run the entire HRC process working set was13,347,426,304bytes;
its peak so far was13,905,559,552bytes. These include the user hand, test hand,
application and previously loaded resources. They are **not** an isolated peak
for this tree. The original sampling throughput text was not captured and no
precise hands-per-second number is claimed.

## Retained timing evidence and limits

The formal OK action at `actions.jsonl:408` was sent only to the observed,
enabled OK control owned by original PID38284. Start UTC was
2026-11-06T04:46:51.903323Z. The live initialized state was used directly,
without reload, reset, or production-engine policy input.

| Observation | UTC / elapsed | Evidence |
|---|---|---|
| Formal options before OK | before start | `screens/ci40-formal-run-controls.png` and corresponding controls JSON |
| Formal OK | 04:46:51.903323Z /0s | `ci40-formal-start.json`, action408 |
| Sampling window enumerated | 04:47:33.666366Z /41.763043s | action409 |
| No operations visible | 04:48:00.667736Z /68.764413s | action410; `ci40-formal-poll-60-controls.json` |
| Independent result saved | after sampling | `screens/ci40-final-saved.png`; actions414–418 |

An earlier one-off Win32 enumeration at approximately59.03seconds also showed
no progress window, but was not saved as a separate durable observation. The
machine-readable report uses the persisted41.763/68.764second endpoints.
Windows enumeration time is not the solver's exact termination timestamp.
The progress observer blocked while sampling, so initial/final CI and its
trajectory are null. The window disappearing without our cancellation is
consistent with normal completion but cannot distinguish it conclusively from
an unobserved error or other stop. Accordingly the CI10 completion-time field
is null and `ci_target_reached_verified` is false. This is a bounded observation
of formal sampling, not a CI10 benchmark and not a lower bound proving that
CI10 needs more than three minutes.

Archives, settings, state, screen hashes and exact event references are in
`reports/hrc-original-40bb-ci-timing.json`. Reproduce that report with:

```
.venv/Scripts/python.exe scripts/report-hrc-original-ci-timing.py
```

This reporting script only reads retained archives/logs, checks root index and
format, verifies tree/config identity, and streams file hashes. It does not
start HRC or perform training. The optional polling helper
`analysis/hrc-desktop/observe-ci40-run.py` was prepared after the missed
transient text but **was not run**; it supplies no evidence for this observation.
