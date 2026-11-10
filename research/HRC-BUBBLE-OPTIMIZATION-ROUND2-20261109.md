# EP bubble solve: second optimization audit

This audit follows the completed CI10 solve. All speed measurements compare our kernels; original HRC was not newly timed. The workload is the user's eight-seat, 58-player/57-paid MTT ICM hand, EP after UTG folds, 20 workers, v4, seed 43, and 8 GiB. Every trial resumes the same immutable own checkpoint at 2,005,302,250 samples. No original policies or leaf payoffs are used.

## Measurement

`scripts/benchmark-hrc-bubble-round2.py` runs variants sequentially, reverses their order on the second repeat, fixes the additional successful sampling cycles, and disables CI. It records input/executable SHA256, process wall time, native training time, checkpoint cost, sampled process CPU/memory and traversal counts. Only copies generated inside each exclusive trial directory are removed after hashing; source archives and checkpoints stay unchanged.

Compute throughput subtracts training checkpoint time. Process wall time includes loading and approximately 22 seconds of monetary table setup. These boundaries must stay separate: shortening a loop by 4% does not shorten a 21-minute CI solve by a newly measured 4%, and a one-time setup cost dominates a very short test.

## Findings

- The exploratory thread sweep found no advantage from reducing workers: compute throughput was approximately 0.147m/s at one worker, 1.013m/s at eight, 1.352m/s at twelve, 1.464m/s at sixteen and 1.883m/s at twenty. The machine has 14 physical cores and 20 logical processors. Some early exploratory trials overlapped candidate compilation; only the later sequential confirmation runs are used for acceptance. Training-window CPU usage reached approximately 15.8 logical CPUs in the short twenty-worker trial; whole-process averages are much lower because table construction is serial. This does not establish a memory-bandwidth ceiling.
- Temporary deal allocation and repeated inverse combo arithmetic are avoidable. Each worker now reuses its own output buffer and uses the existing 1,326-combo card lookup. The original sample API remains available. Uniform targets, weighted joint rejection, folded dead cards, board history, budgets, cancellation checks, counters and draw order are preserved. Both mode1/mode2 selected scopes and fixed-board sampling use the buffer.
- A board-reuse hand evaluator passed 2,162,000 exact rank comparisons, including all nine hand categories, but showed no speed improvement in real training. It is not enabled.
- Exact terminal-state deduplication reduced this case's table from 34,224,104 to 5,479,912 bytes (84% smaller), with 52,387 distinct outcome rows instead of 501,515. It passed all 2,617,125 rank/terminal queries without a bit mismatch. Nevertheless, the two 100-million-cycle trials did not improve training or construction time. It remains an experimental memory candidate and is not enabled. Repeated monetary evaluations already benefit from the existing equity cache; counting fewer output rows does not imply proportionally less ICM work.
- Encoding terminal edges to bypass leaf-node metadata achieved only about 0.4% compute throughput difference across two 100-million-cycle observations. This is insufficient evidence of improvement, so it is not enabled.
- An additional pure-strategy normalization shortcut had only a short screening result and is not enabled.

The sampled phase build was approximately 4% slower than its instrumentation-off control. Empty duration observations averaged about 20 ns, and phase measurements include nested work and timing overhead. They helped select experiments but are not additive exclusive CPU percentages or hardware cache-miss measurements.

## Acceptance and remaining work

The accepted change is limited to deal-buffer reuse and combo lookup. The final production executable and exact measurements are in `.research-cache/bubble-round2-20261109/accepted/` and `accepted-confirm/`. `serial-parity/` compares complete single-thread checkpoints, including RNG and learned storage, from the same real hand. The consolidated evidence is `reports/hrc-bubble-optimization-round2-20261109.json`.

The final 100-million-cycle tests ran sequentially in baseline/new/new/baseline order, with no concurrent compilation or test process. Median here is the mean of two observations. Training time includes periodic and final saves; compute time subtracts those saves.

| Boundary | Previous accepted kernel | This accepted kernel | Speed ratio |
|---|---:|---:|---:|
| Compute only | 54.2705 s | 52.2664 s | 1.03834x |
| Native training including saves | 56.3810 s | 54.3808 s | 1.03678x |
| Complete process, including preparation | 80.7647 s | 78.8816 s | 1.02387x |

The final canonical build identity is `c253acd92207f90ccc00f0ed771a27316841b54fb585a016e0d6a88ca5753c89`; executable SHA256 is `a3829ee7a386c59c9c4d5a7990205732237d76ba965fbc951db12dbbc69e1a2a`. Only `native/hrc_chance.hpp` and `native/hrc_research_solver.cpp` changed between accepted kernels; compiler and flags stayed identical. Current native sources match the frozen accepted manifest.

The single-thread real-hand test added 100,000 cycles using each kernel. Both complete 557 MB checkpoints have SHA256 `f46f3b8d8e64d5bcab11b489083e58ba071caac8141a74240062a69ad8c4c440`, including learned storage, exact counters and RNG state. These results validate the numerical path; the final small optimization was not rerun to CI10, and fixed-work speed is not a newly measured CI10 runtime or an original-HRC speed ratio.

The native scope, chance, dynamic-board, parallel resume and monetary table regression selection passed 96 tests. The new chance tests compare every emitted integer/real random draw and all dealt cards against the independent Python sampler while repeatedly changing seat counts, fixed-board prefixes and skipped targets.

No new order-of-magnitude speedup was found in this audit. Checkpoint I/O is only a few percent, twenty workers remain fastest in the sweep, and the largest candidate changes failed confirmation. Further large gains would require evaluating a different parallel update architecture or reducing sampling work at matched solution quality. Per-bucket writer synchronization and batched updates are hypotheses, not confirmed bottlenecks or measured improvements. Such work needs separate convergence and memory-coherency measurements before changing the production algorithm; the current evidence does not establish that CPU or RAM bandwidth is the absolute limit.
