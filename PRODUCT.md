# Preflop Lab / 翻前研究台

User goal (2026-11-04): use REA to understand HRC, then build an independent academic research application. User selected a full preflop action tree: raises, calls, shoves and range solving.

Delivery: a local Python application with a browser interface, launched on 127.0.0.1. The solver runs on this computer. No hosted service or publication is part of this desktop research workflow.

Version 1 supports 2–6 seats, configurable stacks/blinds/antes, weighted initial ranges, finite opening/re-raise sizes and shoves, legal action navigation, side pots, chip EV / exact ICM utilities, and sampled regret-minimization ranges. A five-card random board resolves preflop leaves without postflop betting. This check-down continuation is explicit throughout the interface; flat-call results are research outputs, not a claim of HRC equivalence. Original implementation and original UI; HRC is a reference target, not our product name.

Required deliverables: runnable app, tests of settlement and solver behavior, readable evidence/spec, clear model limitations, local launch instructions, and a real solved sample. Unvisited hands/nodes must remain visibly untrained. Do not substitute mock or precomputed cosmetic ranges for actual solver output.

Only user-supplied starting ranges, scenario configuration and our computed results are exposed by the app. Proprietary decompilation stays in the ignored analysis directory and is never served by the app.

2026-11-05 addition: fixed nine-seat 20BB/10BB and heads-up benchmarks now connect an independent native training engine on imported HRC topology and locally installed abstraction data. Four-street training, original-result comparison, cancellation and native checkpoints are separate from the original custom 2–6-seat model. This is a measured reconstruction of selected numerical operations, not a claim that the full HRC product or tree builder has been independently reproduced.
