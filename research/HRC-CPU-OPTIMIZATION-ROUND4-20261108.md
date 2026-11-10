# CPU optimization round 4 — fixed tree and abstractions

This round changes engineering implementation only. It does not remove actions,
reduce buckets, freeze low-probability branches, change sampling equations or use
the original application's policies as training input. GPU work is deferred.

## Frozen baseline

- CPP SHA256: `641453406f885c8a851697eaa27f69636aa8336d41a2091a3f1ffca9a9bdc0b7`
- Executable SHA256: `b47b89ff5a28a5c5913a0d629d6c5925496e41c5918161fc969feae6fc4680d1`
- Nine players, 40BB, same 494,055-node tree, static 1024/256/256 abstraction,
  20 workers, explicit 8GiB native budget, own initial checkpoint at 10m samples.
- Unprofiled run: 102,613,750 new samples in 608.1159291 seconds, including
  32.2410527 seconds of final/periodic checkpoint work (5.3018%).
- Entire process observation: 620.9739626 seconds, 3921.265625 CPU seconds,
  mean 6.3147 logical CPUs, peak working set 6,102,331,392 bytes.
- CI ended at 550.9878. This bounded diagnosis did **not** reach CI10.
  CI and its ETA remain heuristic policy-drift measurements, not accuracy bounds.

Source: `reports/hrc-round4-nine-diagnostic-20261108.json` and its immutable
per-process logs. Wall intervals, training intervals and checkpoint intervals
must not be interchanged when calculating throughput.

## Candidate families

1. Share immutable terminal metadata; retain independent value/epoch and
   monetary caches. Reclaim value caches only after complete pointer-table
   publication. Validate all fallback paths and non-ChipEV modes.
2. Separate ordinary format23 regret storage from average/denominator storage
   at runtime. Preserve canonical checkpoints and format/lock fallback.
3. Load-before-CAS and distinct pause/yield intervals for writer mutexes.
4. Avoid per-bucket temporary allocations in CI snapshots by writing normalized
   policies directly into their final destination.
5. Compiler/LTO/layout experiments, with source, compiler, ordered flags and
   profile identity frozen. No fast-math or changed floating-point association.

Each candidate is isolated under `.research-cache/cpu-round4-20261108/` until
correctness checks and sequential interleaved measurements establish its value.
Serial bitwise equality is necessary; it does not establish parallel policy
quality because asynchronous interleavings differ.

## Measurement controls

Only one training benchmark or build-validation owner at a time. Initial source
checkpoints are hashed before and after. Timing uses frozen executables. The
generic runner records both elapsed time including final save and compute time
excluding measured checkpoints. Large generated trial checkpoints may be hashed
and removed only inside the newly created exclusive trial output directory;
all input checkpoints and earlier evidence are preserved.

No current evidence establishes a CPU or memory-bandwidth hardware ceiling.
Low utilization requires explanation before considering GPU offload.

## Selected implementation

The production kernel now contains shared immutable terminal metadata, private
per-worker mutable caches, safe reclamation after complete ChipEV pointer-table
publication, allocation-free per-bucket CI snapshot normalization, and explicit
Windows process HighQoS. Process priority, affinity, global power plan, sampling
equations, tree, abstraction, checkpoint format and CI formula are unchanged.
HighQoS failure falls back to ordinary scheduling; argv23=0 skips the request.
The flag does not reset a QoS policy inherited from an external parent.

The selected compiler flags are `-O3 -std=c++17 -ffp-contract=off -flto=thin`.
Thin LTO consistently improved both final three-player and nine-player runs.
Fast-math and floating-point reassociation were not enabled.

The old Windows policy was OS-managed (`ControlMask=0, StateMask=0`), which is
not an explicit HighQoS request. The selected process requests execution-speed
control with `ControlMask=1, StateMask=0`. In a separate three-repeat rotated
comparison of the **same b47 executable**, this reduced nine-player compute
time for 5m new samples from 29.4442s to 14.7616s (1.995x). This isolates process
scheduling from code changes. It does not establish that every Windows machine
or foreground/background state has the same gain. See Microsoft's
[SetProcessInformation documentation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation).

## Final rotated fixed-sample measurements

Each row is the median of three trials; case order rotates between trials.
CI tracking is off here. All cases start from the same independent checkpoint
for that scenario and use 20 workers with an 8GiB native budget.

| Workload and variant | Compute, excluding measured saves | Elapsed, including saves | Peak working set |
| --- | ---: | ---: | ---: |
| 3p40BB, +60m, prior b47 | 38.1305s | 38.2576s | 213.3 MiB |
| 3p40BB, +60m, selected combination / plain O3 | 15.9415s | 15.9765s | 199.2 MiB |
| 3p40BB, +60m, selected combination / Thin LTO | 15.4103s | 15.4449s | 199.2 MiB |
| 9p40BB, +5m, prior b47 | 30.4849s | 38.3629s | 5.1717 GiB |
| 9p40BB, +5m, selected combination / plain O3 | 15.3158s | 19.9421s | 3.4699 GiB |
| 9p40BB, +5m, selected combination / Thin LTO | 14.3443s | 18.9427s | 3.4699 GiB |

The selected combination is 2.477x faster including saves on the three-player
fixture, and 2.025x including saves / 2.125x excluding saves on the nine-player
fixture. The nine-player peak working-set reduction is approximately 1.70GiB.
The nine-player run resumes our mature 112,613,750-sample checkpoint. These
figures compare our current and prior kernels, **not HRC versus our kernel**.
The earlier matched HRC20/native20 CI10 comparison remains a separate result.

Reports: `reports/hrc-round4-three-foundation-confirm-20261108.json`,
`reports/hrc-round4-nine-foundation-confirm-20261108.json`, and
`reports/hrc-round4-nine-qos-confirm-20261108.json`.

On the fixed nine-player state, four rotated CI snapshot measurements were
bitwise equal and reduced the snapshot median from 0.512891s to 0.144324s,
3.55x / 71.86% less time. This is the snapshot stage's gain, not a 3.55x gain
for the whole solver. A shorter snapshot can change the existing adaptive poll
cadence; no CI equation or threshold was changed to obtain a speedup.

## Rejected local changes

We measured split regret/average layouts, cached row indices, 192/256-byte hot
metadata layouts, load-before-CAS, shorter/longer lock-yield intervals, private
preparation outside writer locks, 32/64-deal task claims, 100/200ms control
slices, full LTO and function-section variants. None established a sufficiently
consistent additional benefit to adopt. Some materially regressed throughput.

For example, three rotated nine-player trials with explicit HighQoS gave
50/100/200ms control-slice compute medians of 5.23572/5.28385/5.30781 seconds.
The latter two also coarsen time-target and cancellation response. Production
therefore retains the 50ms control target and 250-deal claim size.

The early `nine-structure-screen` had a concurrent research-file scan and is
exploratory only. No adoption decision rests on that screen. The later final
confirmation windows had no concurrent agent builds, tests or solvers.

## Remaining expensive work and limits

The retained pre-change ETW training stacks identify shared strategy reads and
updates as important hotspots. Strict accounting of a common 4.3949025s trace
interval verified CSwitch continuity and per-thread CPU residency; yield and
worker-control associations were measured separately. These are sampled stack
and scheduling associations, not a recoverable-speedup calculation. The trace
does not measure memory bandwidth, LLC misses or the post-change CPU ceiling.

The straightforward synchronization, task-size, layout and index changes above
have now been tested. Further large gains likely require a structural change to
shared-state access or traversal, or hardware-counter evidence that justifies a
new data layout. Batched/local regret updates can change learning semantics and
require renewed convergence validation; simply removing locks is not valid.
There is no evidence here that CPU or RAM bandwidth is already an absolute
limit. GPU work remains deferred as requested.

## Production identity and validation evidence

Accepted executable SHA256:
`bbc2f4e45203fedb1131aa5a311d22ef2a5934ae3da15bd59b07f932e18230a6`.
Build identity:
`cf5732345bb8beec98b0d36d25e4cfe0c5a538d81983350e39374a7a2c6b6093`.
The production executable's `.text` is byte-identical to the timed Thin LTO
candidate; all 53 built-in numeric records are byte-identical to prior b47.
The full named-source snapshot, compiler fingerprint, ordered flags and EXE are
preserved in `.research-cache/cpu-round4-20261108/accepted/`.

The production build cache now includes named source hashes, compiler identity
and ordered flags; compiles immutable captured inputs; checks EXE hashes on
reuse; and never overwrites an active canonical artifact. It does not recursively
hash the compiler's standard library/SDK. Real small-program tests exercise an
included header change, flag change, cache reuse and modified-EXE rejection.
QoS tests compare complete fresh and resumed serial checkpoints, including RNG.
The isolated alias guard's 13 mock tests also passed.

Additional numerical evidence is retained under this round's `sync`, `ci` and
`layout` folders: 324 basic terminal cases, 729 monetary/FGS/rake cases,
epoch/cache fallback checks, complete serial three- and nine-player checkpoint
comparisons, and bitwise CI snapshot comparisons. Parallel scheduling can still
change update interleavings; this is not a proof of identical final strategies,
exploitability or full proprietary implementation equivalence.

## Final acceptance and live service

The complete HRC-related regression run had 869 passes, one skip and one failed
existing scratch-budget probe. Independent review confirmed that the probe
omitted the new 1,920-byte cache refund, rather than finding a production budget
error. The probe now checks the exact refund, one-byte-short peak-budget
refusal without mutation, exact-peak publication and repeated preparation.
All affected probe tests were rerun: 8 passed, 1 skipped. Final unique coverage
is **870 passed, 1 skipped, zero unresolved failures**; the skip is the optional
MSVC SDK smoke test. Both original and rerun JUnit reports are preserved and
their reconciliation is explicit in `reports/hrc-round4-final-20261108.json`.

The existing service on port 8769 was kept running. Two normal 5m-sample API
jobs observed the actual native child path before and after controlled cache
publication. The newly generated inactive legacy EXE and global stamp were
backed up, then the validated canonical Thin LTO bytes were published to that
observed legacy filename. A new-helper cache hit preserved the audited alias;
the old service reused exactly those bytes without rebuilding them. Both API
jobs completed with native HighQoS active. No original HRC installation or
pre-existing user calculation was changed. Evidence and backups are under
`.research-cache/cpu-round4-20261108/live-deployment/`.

This compatibility publication is for the frozen current inputs. A future
compiler/flag/header change still requires re-verification while the old Python
helper remains loaded; it is not a general automatic hot-reload mechanism.

The independent 3p40BB full-tree CI10 acceptance, 20 workers, completed in
**285.6960929s**, at **990,053,000 total / 980,053,000 new samples**, with
**CI 9.9076402**, `ci_target`, `target_reached=true`, and a valid final
checkpoint. Readback after startup confirmed execution-speed control=1/state=0,
normal priority and all 20 logical CPUs still in the affinity mask.
Peak native working set was 209,416,192 bytes; process CPU cost was 4,640.703125s.

The prior native acceptance took 285.7626722s. **End-to-end CI10 time is therefore
essentially unchanged**, despite the fixed-sample improvements measured in
this round. The historical OS-managed process already achieved high CPU use in
that longer run. QoS's measured fixed-sample scheduling gain must not be
presented as a twofold improvement in CI convergence, or as a new HRC win.
No new 9p40BB CI10 completion or extrapolated hours-to-target is claimed.

A read-only post-run comparison against the archived, independently trained
HRC20 result covers all 214 preflop nodes. Selected uniform-combo hand TV errors
are 0.548pp at BTN first-in, 0.726pp at SB after BTN folds, 3.868pp at BB facing
BTN, and 7.396pp at BTN facing SB's first 3bet. The last selected node still has
a 97.41pp maximum individual-hand TV error. These statistics are not downstream
reach weighting, current-profile loss or exploitability. The result does not
establish improved accuracy, nor complete algorithm identity.
See `reports/hrc-round4-three-ci10-strategy-20261108.json` and its figures.
