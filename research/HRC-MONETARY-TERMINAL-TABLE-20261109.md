# ICM / MTT shared terminal payoff tables

Implemented on 2026-11-09. All values are calculated independently from our terminal states, prize model and bounty configuration. Original HRC saved leaf values and strategies are not inputs.

The native solver now constructs immutable terminal payoff tables for local ICM and MTT ICM, including fixed KO and progressive KO. Workers share the values and retain private per-deal pointer caches. Raked games and FGS keep their existing evaluation paths. A table exceeding the existing memory allowance falls back to the previous evaluator.

## Correctness and memory

The table retains the existing paid-order prefix winner signature, nested sidepot checks, merged pot awards and exact odd-chip recipient. For monetary utility it reconstructs final stacks and the last covering pot's elimination winner masks, then runs the existing independent equity calculator and subtracts its original baseline. Table construction does not touch RNG, regret stores or sample counters.

The complete user bubble tree contains 66,467 terminals. Its table has 501,515 outcome rows and uses **34,224,104 bytes (32.64 MiB)** including table metadata. Exhaustive live-seat rank assignments made **2,617,125 queries with zero bitwise mismatches** against the prior production settlement path. RNG and sample counters remained unchanged.

The new monetary table suite passed 10 tests, covering ICM/MTT, KO/PKO, ties, sidepots, tight memory refusal, exact single-thread training checkpoints with the table enabled/disabled, and selected-subtree resume against the frozen previous executable. An additional 158 relevant regression tests passed.

Evidence:

- `reports/hrc-monetary-table-real-bubble-validation-20261109.json`
- `reports/hrc-monetary-table-tests-20261109.xml`
- `reports/hrc-monetary-table-regression-20261109.xml`
- `tests/test_hrc_monetary_terminal_table.py`

## Matched 20-worker throughput

Both versions resumed the same immutable mature checkpoint at 1,732,181,250 cumulative samples, with the exact same input binary, seed 43, EP path `[0]`, 20 workers and 8 GiB budget. Each invocation performed another 5,000,000 successful subtree cycles. CI was disabled to measure fixed work. Runs were sequential in old/new/new/old order; compilation was outside timing. Source checkpoint hashes remained unchanged.

| Run | Total process wall time | Training phase | Table preparation |
|---|---:|---:|---:|
| Old A | 88.750 s | 86.257 s | 0.014 s |
| New A | 30.067 s | 4.551 s | 23.252 s |
| New B | 29.413 s | 4.118 s | 23.068 s |
| Old B | 83.706 s | 81.244 s | 0.010 s |

Mean total wall time fell from **86.228 s to 29.740 s: 2.899× faster**, including loading, construction and saves. Mean training-phase time fell from **83.750 s to 4.335 s: 19.322× faster**. New runs performed zero runtime terminal settlements; the old A run performed 55,980,354.

Peak working set was about 1.546 GiB old and 1.597 GiB new. The new peak includes construction before worker scratch caches are released. Its roughly 23-second serial preparation is now a visible cold-start cost; short-run wall speedup must not be described using training-only speedup.

Full evidence, commands, executable hashes, CPU and memory measurements are in `reports/hrc-monetary-table-benchmark-20261109.json` and `.research-cache/monetary-table-benchmark-20261109/`.

These are measurements of our two kernels. They do not establish a new measured speed ratio against the original HRC desktop program or a time-to-CI improvement.

## CI10 validation

The prior kernel finished the user's independent EP solve at **CI 9.97742491475**, cumulative sample count **1,844,016,750**. Its formal computation took 21,601.044 s plus 1,446.929 s across two invocations; the first invocation hit its former six-hour safety cap. The initialization took another 259.433 s. Pauses between invocations are excluded.

That final strategy's uniform-combo raise frequency was 31.5329%, versus the supplied HRC save's 31.4145%. Uniform-combo weighted hand total variation was 0.00229872. These weights are not conditional reach weights, and the independent frozen UTG prefix differs from the original HRC strategy.

The optimized kernel was then started from the **same original 10-million-sample independent initialization**, with the same EP selection, 20 workers and CI target 10. It has no hard time stop. Application job: `2a1837784df843b5ac81031b7e0a89d0`. Completed results are saved by the normal application pipeline. Its actual CI-target time must be read from the completed summary; it is not extrapolated from the fixed-work benchmark.

The running job confirmed both `terminal_tables=true` and `terminal_pointer_cache=true`, the expected 34,224,104-byte table and EP native root 1.

### Completed optimized CI10 result

The first optimized job was stopped on request at CI 17.1772052982 after 605.55 seconds of application wall time. It was resumed as job `a649bb63d04344a2b591382aa29dec70`, which finished normally with `stop_reason=ci_target`, CI **9.85632172964**, and **2,005,302,250 cumulative samples**. The continuation took 654.19 seconds of application wall time.

The two effective invocations together took **1,259.74 seconds (20m 59.74s)**, including their loading, table preparation and saves. Their native training timers sum to **1,193.8749248 seconds (19m 53.87s)**. Compared with the old kernel's native formal training total of 23,047.9732163 seconds, this is **19.305x** using the same native timer boundaries; sample counts and asynchronous trajectories differ. The earlier approximately 18x user-facing comparison included optimized application setup and was conservative, with different timing boundaries.

Both comparisons start from the same previously generated independent 10-million-sample initialization, which originally took 259.4328005 seconds. This is not a fresh measurement of optimized initialization. Original HRC desktop runtime was not remeasured by this test.

The completed optimized checkpoint is `.research-cache/runs/91504bf5f41e43028c2ed1ce912df1cd/checkpoint.bin`. The next fixed-work optimization audit uses that immutable own checkpoint, with CI disabled, as described in `research/HRC-BUBBLE-OPTIMIZATION-ROUND2-20261109.md`.
