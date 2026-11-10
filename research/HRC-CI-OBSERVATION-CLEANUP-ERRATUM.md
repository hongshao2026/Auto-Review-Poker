# CI observer cleanup correction, 2026-11-07 local time

The v1 observation agent's `removed_and_original_class_restored` event was
insufficient evidence of removal. It called `removeTransformer` on the
Instrumentation argument supplied to the later `agentmain` invocation and did
not check the boolean return. When the same original JVM (PID34604) was prepared
for another run, reinstalling produced one successful transformation followed
by an unexpected-input-hash failure. A previously registered transformer was
still participating. The earlier report's unqualified claim that the hook had
been removed at the first stop must therefore be withdrawn.

Evidence: `analysis/hrc-desktop/ci10-original-long-20261107/agent-events.jsonl`
and `preflight-resolution.json`. The attempted second run had not been started.
No solver settings, policies, counter updates or original JAR were modified by
this issue. The one-hour run's already retained CI argument values are not
invalidated by the later cleanup failure. The v1 sources and binary artifacts
are retained under `analysis/hrc-deep/ci-runtime-observer/`, including
`retained-v1-sources/`.

PID34604 was closed normally, clearing all former JVM instrumentation state.
The current long continuation uses a newly started original HRC PID24968 and
observer v2. V2 retains the Instrumentation owner that registered the
transformer and requires `removeTransformer` to return true. Its isolated
original-class self-test verifies the original constructor fields, exact logged
arguments, successful owner-based removal, and no log from another original
constructor invocation after removal. The test deliberately supplies null as
the later cleanup invocation's Instrumentation argument, proving it uses the
stored owner. Build manifest:
`analysis/hrc-deep/ci-runtime-observer-v2-20261107/build-manifest.json`.

The newly started JVM recorded exactly one transformation, passed the detached
original OSGi-loader link check and emitted its first real run CI at
2026-11-06T16:18:13.563Z. The current active hook is intentionally retained while
the authorized multi-day run continues. Its eventual cleanup must verify the
v2 boolean-success event; the existence of a generic log label alone is not
sufficient.
