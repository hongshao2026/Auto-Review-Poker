# Native build identity and live-service deployment review

Final parent verification: publication completed without restarting port 8769.
Two API jobs observed the same legacy filename; its post-publication SHA equals
the canonical Thin LTO EXE, the new helper preserved the guard, and the old
helper reused it without recompilation. See
`.research-cache/cpu-round4-20261108/live-deployment/report.json`.
The obsolete source comments mentioned below were corrected. The review's
future-invalidation and failure boundaries still apply.

Review date: 2026-11-08. Scope: read-only inspection of the applied `preflop_lab/hrc_native.py`; no compilation, solver execution, API request, cache replacement, or service restart performed by this reviewer. The parent reports that the 13 isolated alias mock tests passed. Those tests are distinct from the still-required live deployment verification.

## Observed implementation

- Lines 45–46 select ordered strict floating-point flags. Zig uses `-O3 -std=c++17 -ffp-contract=off -flto=thin`; the ignored experimental `-flto-jobs` flag is absent.
- Lines 174–184 retain the historical 17-file concatenation only as a compatibility field. The canonical source identity includes relative names, sizes, and hashes of every `.cpp`, `.hpp`, and `.h` below `native`. Inspection of the current quoted local includes found no omitted local dependency. Including unused native sources is conservative and can cause extra rebuilds.
- Lines 136–166 fingerprint the selected compiler binary and version. MSVC also records its linker and environment script. Lines 199–205 include the source inventory, compiler identity, ordered flags, optional profile hash, paths, CPU identifier, and relevant environment in the actual cache key. This does not recursively fingerprint the compiler's standard library or Windows SDK.
- Lines 179–184 capture source bytes; lines 224–226 compile their immutable copy. Later working-tree edits cannot silently alter that build's inputs. Lines 208–215 require matching identity/specification and the actual EXE hash for a cache hit, and reject replacement of an invalid existing canonical artifact.
- Lines 88–133 preserve an existing live alias only after exact identity, complete source inventory, alias path, canonical EXE SHA, and alias EXE SHA checks. The per-identity manifest remains canonical; only the global compatibility stamp may retain the observed legacy key. The function never publishes an alias.

## Failure boundaries

1. **Legacy invalidation remains limited by the old process.** If the observed legacy key equals the current 17-file compatibility key, a later change only to flags, compiler, or a header absent from the old loaded tuple can change the canonical identity while leaving the old key unchanged. Dropping `live_legacy_alias` metadata cannot make that old helper understand the new identity. Such a change requires another controlled alias publication or an eventual normal service restart. This round can deploy safely only with frozen inputs and explicit verification; it is not a general automatic hot-reload guarantee.
2. **Global stamp writes are last-writer-wins across processes.** `_build_lock` is process-local. Unique temporary files and atomic replacement protect JSON integrity, but do not serialize different builders' intent. Avoid concurrent native job launches/builds during publication and its two verification steps. The web service itself can remain running.
3. **Same-identity concurrency fails explicitly.** `compile.lock` acquisition at lines 217–221 requests a retry rather than waiting. A crash may leave a stale lock, or a completed EXE without its manifest if interrupted between lines 247 and 253. These conditions deliberately require recovery; they do not justify overwriting an artifact currently in use.
4. **Current dependency coverage is not future-proof for arbitrary file extensions.** A future local `.inc`, generated file, external include directory, or changed SDK must be included explicitly if it affects the build. No such omitted current local include was identified.
5. Lines 43–44 retain obsolete “proposed/not imported” comments after the block was applied. This is documentation drift, not a build-behavior failure.

## Required no-restart deployment sequence

The parent owns the following actions; this review did not perform them.

1. Finish the selected canonical build and validation. Freeze the exact full named-source inventory, compiler fingerprint, ordered flags, identity manifest, and EXE hash.
2. Run one small normal job through the existing service on port 8769. Observe the actual legacy key, spawned executable path, global stamp, and job exit. Do not infer the running function's tuple from current disk source or older benchmark helpers.
3. Confirm that the observed legacy artifact was generated in this round and that no process is executing its exact path. Recheck the full source inventory against the canonical build. If these checks fail, retain the existing artifact and performance fallback.
4. Back up that inactive legacy artifact and the global stamp to unique paths, recording hashes. Stage a copy of the validated canonical EXE beside the alias and verify its SHA before replacing only this round's inactive legacy file. Preserve the canonical identity folder and its symbols.
5. Publish the global record from the canonical manifest, using the observed old key as `source_sha256`, and retaining the canonical 17-file compatibility digest as `canonical_legacy_source_sha256`. Keep `executable_path` canonical. Add `live_legacy_alias` with schema `hrc-live-legacy-alias-v1`, a unique publication ID, observed key, exact canonical build identity, full source inventory, exact alias path, and equal canonical/alias EXE hashes. Separately record the previous artifact SHA, backups, observed job, and process-use checks.
6. Verify a new-helper cache hit preserves that guarded global alias. Then run a second small job through the old service and verify it launches the observed legacy filename containing the canonical Thin LTO bytes, without rebuilding it. Keep these steps sequential and avoid source/flag edits between them.

Success is established by the two actual runtime verifications and matching byte identities, not merely by the 13 mock tests or the presence of alias metadata. Future deployment changes must repeat the checks where the old helper's cache contract cannot represent the new identity.
