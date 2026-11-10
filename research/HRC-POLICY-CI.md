# Bucket locks, frequency constraints, and recent-policy-drift CI

The independent modules are `native/hrc_policy.hpp`, `native/hrc_ci.hpp`, and the
Python reference `preflop_lab/hrc_policy.py`. They execute no HRC code. The separate
verification probe loads a small allowlist of original classes from the local
HRC JAR into a platform-parent class loader. It does not start the application,
a worker, a license initializer, OSGi, or a GUI. No saved policy is an input.

The pinned JAR SHA256 is
`25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`.
All loaded class hashes appear in the machine-readable reports. The Java probe
selects methods by full JVM descriptors, including the return type.

## Evidence and scope

| Claim | Original method | Retained evidence |
|---|---|---|
| Lock composition, residual mass, threshold and tie ordering | `mx.a([DI[Z[DDIZ)[D` | `analysis/hrc-deep/policy/mx-bytecode.txt:431`; decompiled `sources/0019/mx.java:169` |
| Training uses raw regrets, display uses raw averages | `my.a(IZ[DI)V`, `my.a(I)[D` | `policy/my-bytecode.txt:78`, `:263`; `sources/0017/my.java:43`, `:92` |
| Lock edits clamp and rescale other locked actions | `my.a(I[D)Lnet/holdemresources/internal/my;` | `policy/my-bytecode.txt:477`; `sources/0017/my.java:163` |
| Lock toggle captures composed display | `my.a(IZ)Lnet/holdemresources/internal/mx;` | `policy/my-bytecode.txt:426`; `sources/0017/my.java:151` |
| Locked wrapper delegates storage update unchanged | `my.a(Lnet/holdemresources/internal/ma;[DIIDD)V` | `policy/my-bytecode.txt:403`; `sources/0017/my.java:141` |
| Frequency store format, cache and update | `mz.<init>(II[D[DI)V`, `mz.a(Lnet/holdemresources/internal/ma;[DIIDD)V` | `policy/mz-bytecode.txt:95`, `:568`; update BCI99–235 and238–524 |
| Frequency argmax selection | `mz.a(IZ[DI)V` | `policy/mz-bytecode.txt:894`; `sources/0025/mz.java:245` |
| Frequency reset, cache flush and sync | `mz.a(ZZ)V`, `mz.a()V`, `mz.b()V` | `policy/mz-bytecode.txt:1021`, `:231`, `:282` |
| Relative EV and display normalization | `mt.b(I)[D`, `mt.a(I)[D` | `policy/mt-bytecode.txt:132`, `:96` |
| CI selected nodes and initial snapshots | `mq.<init>(Lnet/holdemresources/internal/mf;)V` | `policy/mq-bytecode.txt:47`; `sources/0030/mq.java:31` |
| CI drift, smoothing, speed, retention | `mq.a(J)Z` | `policy/mq-bytecode.txt:133`, BCI130–310,355–570 |
| CI target progress helper | `mq.a(DLnet/holdemresources/internal/mr;)D` | `policy/mq-bytecode.txt:420`; `sources/0030/mq.java:113` |
| New worker creates a fresh CI tracker | `mn.<init>(Lnet/holdemresources/internal/qb;Lnet/holdemresources/internal/mf;Lnet/holdemresources/internal/lZ;Ljava/util/function/BooleanSupplier;)V` | `policy/mn-bytecode.txt:56`; `sources/0034/mn.java:53` |

Paths in this table are relative to `analysis/hrc-deep/` unless written in full.
These are facts from the pinned artifact, not claims about other HRC releases.

## Bucket locks

`BucketLocks(actions, buckets, rows)` uses action-major rows. An empty row is
unlocked. A nonempty row contains one probability per bucket. Call `compose`
only while `active()` is true; with no locks use the underlying store's normal
normalization. Pass raw bucket regret values for training, raw average values
for display. Underlying storage updates continue unchanged.

Let the locked mass be `m`, and let `x` be the supplied raw values. If every
action is locked, the original returns the locked values directly. If only one
action is unlocked, it receives `1-m`. With at least two unlocked actions:

* Display assigns residual mass proportionally to positive unlocked raw values.
* Training with exactly one positive locked action uses threshold
  `theta = -sum_locked(x[a]*lock[a]/(1-lock[a]))` and weights
  `max(x[a]-theta,0)` for unlocked actions.
* Training with multiple positive locked actions gives all residual mass to the
  first maximal unlocked raw value. Equal values retain the first action.
* Zero residual positive weight gives the mass to the first unlocked action.

`edit(action, values)` clamps finite inputs to `[0,1]`. If total locked mass
exceeds one after an edit, other locked actions are scaled proportionally while
the edited action is preserved. `lock_current` captures the caller's current
composed display values; `unlock` removes one row. These are state operations,
not special learning updates.

The original allows fully locked mass below one and returns that mass without
normalizing it. The math module retains this behavior. A public application
should reject an underfilled fully locked distribution as invalid input.

The original special/check branch overwrites action0's supplied lock value
without adjusting its lock flag or locked mass. Locking that virtual fold can
produce NaN, a deficient sum, or an `IllegalStateException` depending on the
branch. The independent helper preserves the numerical behavior and throws on
the same final sum check. Integration should reject locks on the virtual fold
of a special node. It must not silently reinterpret this as an ordinary fold.

`my` unwraps an existing `mz` when locks are attached. Simultaneously composing
both features is therefore not original behavior. Our modules expose both
primitives, but the application should select one mode per node, or explicitly
implement the original conversion when switching modes.

## Frequency/edge store

`FrequencyStore(buckets, actions, targets, edges, underlying_format=23)` models
format63. Targets may be NaN (unconstrained); Python also accepts `None`. Manual
edges must be finite. Finite targets must be in `[0,1]`, with total at most one.
The input boundary is stricter than arbitrary malformed original storage.

With `K` actions and `H` buckets the raw double layout is:

```
raw[0]                        cached update counter
raw[1:1+K]                    cached shared action averages
r = 1+K + bucket*(2*K+1)
raw[r:r+K]                    R (regret/relative-payoff accumulators)
raw[r+K]                      D (counterfactual weight sum)
raw[r+K+1:r+2*K+1]             A (bucket average accumulators)
```

The actual update counter, shared average adders, edge adders, cached edges,
global minimum and maximum payoff are separate state. They must all be saved
and restored for a numerical checkpoint; `raw` alone is insufficient. Live
training uses double precision. Original archive serialization narrows values
to floats; the independent checkpoint need not introduce that loss.

For input strategy `p`, action values `Q`, weight `w`, and reach marker `z`:

```
if w <= 0: return
V = sum(p[a]*Q[a] where p[a] > 0)
updates += 1
t = cached_counter + 1
if refresh(t): cached_counter = t = updates
R[a] += w*(Q[a]-V)
D    += w
A[a] += t*p[a]
```

This differs from `mE`; do not apply the ordinary `mE` update first. The caller
supplies `refresh(x)` implementing original `ma.a(D)Z`:
`nextInt() % floor(sqrt(x)) == 0`. Its RNG draw must occur even when the divisor
is one.

For `z > 0`, a second draw invokes `refresh(sqrt(t))`. All action payoffs update
global extrema, including zero-probability actions. For each constrained action:

```
span = max(maximum-minimum, 0)
edge_sum[a] += span * (z / t**(1/sqrt(2))) * (target[a]-p[a])
if second_refresh: cached_edge[a] = edge_sum[a]
shared_sum[a] += z*t*p[a]       # all actions, constrained or not
```

The original minimum starts at positive `Float.MAX_VALUE`, and maximum at
positive `Float.MIN_VALUE` (`2**-149`), not negative infinity. All-negative
payoff fixtures verify this easily missed detail. `z=0` updates bucket R/D/A
but not extrema, shared averages or edges.

Training chooses the first maximum of `relativeEV[a]+cached_edge[a]`, where
`relativeEV[a]=(R[a]-R[0])/D`. If `D<=0`, relative EV is NaN, so selection stays
at action0 (action1 for special nodes). Display remains positive-normalized
bucket A; empty A displays uniform probabilities. Shared aggregate display
flushes counters/edges first, then normalizes the shared averages. It is not
the unweighted mean of bucket displays.

`flush()` synchronizes cached counter, shared averages and cached edges from
actual sums. `reset(regret,average)` uses original `1e-20` scaling, not zeroing:
regret reset also resets count, extrema and constrained cached edges; manual
unconstrained edges remain. Average reset scales bucket and shared A. The
resulting cache sync order is part of the retained probe comparison.

The header implements sequential numerical semantics with successful weak CAS.
It does not emulate races or spurious CAS failures. A shared parallel caller
must provide synchronization. Changing worker scheduling or cache flush timing
can change learning trajectories even when these formulas match.

## CI snapshots and time

`hrc_ci::Tracker` receives already-selected snapshots, each containing node
update count and a flat bucket-by-action display policy. It deliberately does
not access a tree, store, or wall clock. The caller must flush the underlying
store before taking each snapshot, just as original `mq` does.

Original node selection is a pruned traversal. For a preflop root, include only
preflop decision nodes. For another root street, include decision nodes on that
street whose store supports capability bit2; prune when the predicate fails.
The module expects a stable selected set and shape. A reset in counts requires
`restart`, rather than silently taking the square root of a negative delta.

For node `i`, count increment `d_i`, and displayed policies `P` and `Pold`:

```
distance_i = 0.5 * sum_bucket,action(abs(P-Pold))
weighted_distance = sum(sqrt(d_i)*distance_i) / sum(sqrt(d_i))
raw_CI = sqrt(weighted_distance * selected_node_count / sum(d_i) * 1e8)
```

Buckets receive equal weight. There is no 6/4/12 combination multiplicity, hand
reach, EV error, confidence probability or best-response computation in this
statistic. It should be labeled recent policy drift, not exploitability or a
statistical confidence interval.

The first positive-progress record uses raw CI. Later records use
`alpha=min(previous_record.ordinal*.05,.75)` and
`CI=alpha*oldCI+(1-alpha)*rawCI`. A poll with no count increase still advances
snapshot state and last poll time, but creates no CI record. Speed after the
first record is sample delta divided by elapsed milliseconds since the last
poll, then multiplied by 1000 for samples/second.

Retain at least three records. Remove older first records while their timestamp
is before `now-min((now-first_record_time)*.75,7200000)`. The minimum poll
interval is 15000ms; the next interval is `max(15000, measured_poll_work_ms*50)`.
Time is caller-provided; the pure module uses one logical timestamp for the
formula, whereas original code reads wall time several times. Original
wall-clock jitter is measured separately in the comparison report.

`progress(target, reference)` preserves the original exponent `-1.7` helper.
It returns zero without a reference or if the current CI exceeds reference CI,
one after reaching the target, otherwise the original power-law expression
clamped below at zero. `first_record` remains available after history trimming.
Each new original `mn` creates a new `mq`; therefore continuing a numerical
checkpoint in a new worker restarts CI history rather than restoring a prior
worker's recent-drift trajectory.

## Reproduction and result

```
.venv\Scripts\python.exe scripts/validate-hrc-policy.py
.venv\Scripts\python.exe scripts/validate-hrc-ci.py
.venv\Scripts\python.exe -m pytest tests/test_hrc_policy.py tests/test_hrc_ci.py -q
```

`reports/hrc-original-policy-validation.json` records 121 lock cases, including
capture/unlock, and 24 frequency cases containing 864 successive snapshots.
The initial 120-case run compared 174,786 scalar values with maximum absolute
error `1.42e-14`; the current report contains the exact expanded count and hashes.
Every snapshot compares raw storage, cached and actual edges, shared sums,
update counts, payoff extrema, ordinary/special training strategy, display and
relative EV against both native and Python implementations.

`reports/hrc-original-ci-validation.json` records 216 snapshots on 1/2/4-node
synthetic graphs. It verifies CI, progress helper, smoothing, retention across
hours, zero-progress polls, and new-tracker restarts. Private timestamp fields
and immutable history records are rebased only within the test fixture, so
hours of retention can be exercised without waiting hours. Original method
bytecode, policies and counts are unchanged. Maximum CI error is below `1.2e-13`;
the latest run's timing jitter and rate difference are in the report.

These original-bytecode reports verify the standalone numeric modules. Their
production integration is now exercised separately by
`tests/test_hrc_native_features.py` and `tests/test_hrc_checkpoint.py`: locks and
frequency stores participate in actual traversal, CI can stop an actual run,
and complete numeric state survives checkpoint restore. The portable binary
protocol, explicit migration rules, formats27/31, limits and cancellation
semantics are documented in `research/HRC-NATIVE-CONTROLS.md`. Standalone proof
counts above should not be confused with the separate integration tests.
