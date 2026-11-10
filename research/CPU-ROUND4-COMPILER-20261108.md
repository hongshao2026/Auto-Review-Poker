# Isolated round 4 compiler and CI snapshot validation

The CPU slot was coordinated with the parent; all compilation and short checks have finished. No production source/build script was modified, no formal solver throughput benchmark was run by this worker, and no toolchain was downloaded or installed.

The frozen accepted executable is SHA-256 `b47b89ff5a28a5c5913a0d629d6c5925496e41c5918161fc969feae6fc4680d1`; main C++ source is `641453406f885c8a851697eaa27f69636aa8336d41a2091a3f1ffca9a9bdc0b7`. All named C++/header hashes are in `.research-cache/cpu-round4-20261108/compiler/source-manifest.json`. Compilation uses installed Zig 0.15.2 / Clang 20.1.2, target `x86_64-unknown-windows-gnu`, preserving `-O3 -std=c++17 -ffp-contract=off` and the GNU/Clang atomic implementation. There is no fast-math or reassociation flag.

## Compiler candidates

| Candidate | Additional flags | Executable SHA-256 | Build seconds |
| --- | --- | --- | ---: |
| Thin LTO | `-flto=thin -flto-jobs=1` | `55cf89b7754501d4d95bf7f8aa12490a855e4981892459a85d4486d722f4b0b4` | 17.19 |
| Full LTO | `-flto=full` | `fc881b049ebcf03d5c6dc541fefcee24f72afb6b62192fe9b26442a42f492be1` | 21.85 |
| Function/data sections | `-ffunction-sections -fdata-sections` | `19ed218ab130b37dccdcde93dc7b00efc0d801b348515b339a1190d2aaac461a` | 11.18 |

Zig warns that **`-flto-jobs=1` is unused**. Thin LTO itself compiled, but this flag did not establish a one-thread link. The other two build logs are empty. These build durations are operational observations, not compiler throughput comparisons. Exact executable paths, build identities, sizes and warnings are in `compiler/ready-candidates.json` and `compiler/variants/*.json`.

Each candidate produced exactly the accepted `--self-test` output and exactly matching single-thread checkpoints for real three-player 40 BB static play (5,000 samples), HU preflop (5,000 samples), and a custom dynamic format-31 fixture (1,000 samples). All nine candidate/case comparisons also matched terminal-call counts. `compiler/validation.json` contains full input/checkpoint hashes. This is a bounded semantic gate; it is not exhaustive validation of all game models, concurrency schedules or long-run numerical trajectories. The parent owns the actual throughput matrix and adoption decision.

Experimental build identity includes named source hashes, executable compiler SHA-256 and version/target, selected toolchain header anchors, environment/CPU identity, exact ordered flags, source/cwd, and profile digest when used. Existing cached executables must match their recorded hash. This prevents a changed flag, compiler, or supplied profile from accidentally reusing a source-only build cache. The toolchain fingerprint is explicit but does not claim a recursive hash of every installed library.

## PGO availability

Local inspection found no matching `llvm-profdata` and no usable Clang-20 GNU profile runtime in the installed Zig distribution. Older Visual Studio profile libraries were not mixed into this toolchain. The actual tiny instrumentation smoke test (`-fprofile-generate=... -fprofile-update=atomic`) failed at link time with `undefined symbol: __llvm_profile_runtime`. The exact command/error is in `compiler/pgo-smoke/result.json`. No `.profraw` profile or instrumented solver was produced. A working PGO pipeline therefore remains unavailable in this tested setup; the result does not imply PGO is impossible with a correctly matched toolchain/runtime.

## Root-owned CI snapshot candidate

The candidate reduces per-bucket allocation by writing normalization results directly into an owning snapshot row. It retains action/bucket/node order, count flushes, normalization arithmetic, lock composition, and frequency-store behavior. Its read-only review is in `compiler/ci-readonly-review.md`; the candidate implementation itself was not changed by this worker.

The real nine-player tree contains 76,928 selected CI nodes. Tree SHA-256 is `94075d849e509e3d0cd721928f0730c565817db14add8dd12fc621c97da299ca`; the saved checkpoint is `ea268fd82f9ff66d749d9b909968ce00c18ff7f0a646201e6020171e416325f2` (2,433,800,748 bytes). The probe checked byte equality of all snapshot policies and counts, plus synthetic formats 23/25/27/31, 2–16 actions, locks and frequency stores.

Four alternating old/new snapshot-creation timings were:

| Version | Measured seconds | Median |
| --- | --- | ---: |
| Previous | 0.517743, 0.512904, 0.512878, 0.507889 | 0.512891 |
| Candidate | 0.145477, 0.145742, 0.142345, 0.143171 | 0.144324 |

This is a 71.86% reduction for snapshot creation/normalization only, approximately 3.55 times faster. It excludes tree/resource loading, checkpoint loading and the full training loop. Frequency-backed nodes still allocate per bucket. The unchanged adaptive CI scheduler uses snapshot duration, so a faster snapshot can also change subsequent wall-clock polling intervals; byte equality of a snapshot does not promise identical wall-clock CI observation times.

Artifacts: `ci/solver.exe` SHA-256 `380e90fe15caaae7b706e8cf336353aa33c6d853e32b0edb19784fa75bd6ff8e`; `ci/probe.exe` SHA-256 `8d49280386b2745fb545b29880133bd4ff526526d4298ea63332c41768a040c5`. Full build/source/compiler identities are in `ci/build-results.json`, and full resource/input identities, original timing order and parity result are in `ci/validation-results.json` and `ci/probe-stdout.jsonl`.
