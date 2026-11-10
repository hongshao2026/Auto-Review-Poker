# Static abstraction lookup and lazy caches, 2026-11-08

This is a read-only audit of the installed HRC 4.1 JAR, SHA-256 `25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43`. Evidence is in `analysis/hrc-deep/round3-abstraction-20261108/`, including `evidence.json`, selected source snapshots and fresh `javap -p -c -s` output. The installed Eclipse Collections JAR has SHA-256 `66a68713b950183831f621278bb6da674f82ca8a2d5bbe312556e9c5ff19610c`. No target code was executed and no performance test was run for this audit.

## Observed original call chain

1. `lV.<init>(oj,[J,[I,Z,ma)` allocates a four-street cache and fills preflop classes. `lV.a(II)I` checks whether the selected street's array is null, calls `oj.a(I[J[I)[I` once if needed, then returns `[street][player]`. Thus the first decision on a street fills **all dealt players' buckets**, not only its actor. See `sources/0029/lV.java:52`, `:63`, `:68`. The cache belongs to the deal context, not to a node or shared worker store. Its rank cache is also lazy, but evaluates all players together (`:71`).
2. The static adapter `ok.a(I[J[I)[I` checks four board-history entries and calls its street's `oi.a([I[J)[I`. See `sources/0871/ok.java:26`. This is separate from dynamic, player-specific abstractions.
3. `ol.a([I[J)[I` canonicalizes the selected street's board **once for the whole batch**, obtains a board row with `LongIntHashMap.getIfAbsent(JI)I`, and looks up each suit-remapped combo in `short[row * 1326 + combo]`. See `sources/0889/ol.java:64`–`:76`; saved `0889/bytecode.txt:146`, bytecode offsets 36 (`getIfAbsent`) and 69 (`saload`). No per-player board hash, compressed-column popcount or search occurs here.
4. `ls.a(I[I)I` uses precomputed high/low cards, remaps their suits, and returns `maxCard*(maxCard-1)/2 + minCard`. See `sources/0708/ls.java:33`. It does not use a 24-permutation combo lookup table.
5. `og.b(J)[I` sorts the four suit rank-vectors to construct a suit map; `og.a(J[I)J` produces the canonical mask. See `sources/0895/og.java:134`, `:161`. The sort in `b` is a selection sort with strict comparisons; do not infer stable equal-key permutation identity from the canonical mask alone.

## Observed row index and resource layout

`lo.<clinit>` enumerates boards, canonicalizes and deduplicates them, sorts canonical masks, and assigns consecutive row numbers. `lo.a([J)LongIntHashMap` inserts `(mask, ordinal)` and calls `compact()`. See `sources/0704/lo.java:17`, `:41`, `:51`–`:63`. This is a normal hash index, **not a perfect hash, combinadic direct row formula, or binary search**.

The installed `LongIntHashMap` uses separate primitive `long[] keys` and `int[] values` (`LongIntHashMap.javap.txt:27`, `:30`, allocation at `:2830`). `getIfAbsent(JI)I` at `:1831` selects its fast path when there are no removed sentinels. `fastGetIfAbsent` at `:1914` first tries up to four consecutive array slots, beginning with the low key bits masked by `capacity-1`; a miss goes to a second mixed probe (`:2680`) and then a double-hash sequence (`:2741`). Empty/removed keys are 0/1. Canonical postflop boards have neither value. Reads are ordinary primitive array accesses; the map is constructed before lookup and this reader does not mutate it. `compact()` rehashes, with normal insert/load-factor growth still applied: do not infer its final capacity just from the first requested power of two.

`oh.a(InputStream, int, String)ol` reads and hashes the decompressed resource, expands each legal-hole-only row into **1326 signed shorts**, fills colliding hole positions with -1, validates row count/end-of-file/digest, then constructs `ol`. See `sources/0872/oh.java:11`, `:18`, `:24`–`:37`, `:41`, `:53`. The decompiler's `byte var10` is misleading; bytecode has an integer byte-offset local. The SHA identity and compressed resource schema are unchanged by the in-memory expansion.

`oe.a(of)oi` caches loaded abstractions by digest in a synchronized map of `SoftReference<oi>`; a miss opens the resource through Brotli and `oh`, then saves the reference. See `sources/0892/oe.java:19`, `:26`–`:39`. This is whole-profile loading/cache reuse, not per-board row loading. There is no evidence of disk I/O or decompression in the training `ol` lookup. Soft references may be cleared under memory pressure; active `ok`/`ol` references still retain a loaded table. The cache's separate contains/get/load operations are not one atomic load-once transaction.

## Comparison with our frozen baseline

`native/hrc_cards.hpp:138` stores compressed legal columns, with 16-bit flop and 8-bit turn/river values. Board rows use `std::unordered_map<uint64_t,uint32_t>` (`:142`). `prepare_bucket_row` (`:177`) canonicalizes and hashes once, and `bucket_from_row` (`:184`) remaps suits then computes the legal-only column using two popcounts (`:109`). `Engine::hand` at `native/hrc_research_solver.cpp:356` already caches this row once per deal/street and fills each actor lazily. **It is incorrect to describe our implementation as hashing the board at every decision.**

Payload-only sizes for the currently used 1024/256/256 profiles (bytes; excludes indices, containers and load temporaries):

| Street | Rows | Current legal columns | Current width | Current bytes | Full 1326, same width | Original signed shorts |
|---|---:|---:|---:|---:|---:|---:|
| Flop | 1,755 | 1,176 | 2 | 4,127,760 | 4,654,260 | 4,654,260 |
| Turn | 16,432 | 1,128 | 1 | 18,535,296 | 21,788,832 | 43,577,664 |
| River | 134,459 | 1,081 | 1 | 145,350,179 | 178,292,634 | 356,585,268 |
| Total | | | | 168,013,235 | 204,735,726 | 404,817,192 |

Keeping our narrow widths while expanding columns adds 36,722,491 bytes, about 35.02 MiB. An 8-bit table cannot encode both all 256 bucket IDs and a -1 sentinel: retain an explicit board/hole collision check, or use another validity representation. Do not silently map bucket 255 to invalid.

The measured profile has 197,196,804 `hand` calls for 5,000,000 three-player deals (39.44 calls/deal). Since a deal can fill at most 3 streets × 3 actors, at least 77.18% of calls reuse a previously available entry; row preparation occurs at most three times/deal. These are **bounds from call counts and code**, not measured phase subdivisions. The 9.97 empty-clock-adjusted worker-wall seconds do not establish that board hashing dominates this phase. Split future timing into cache-hit, first-row preparation and actor fill before attributing that estimate to a component.

## Independent optimization conditions

* A flat, immutable primitive board-row index is a directly supported engineering direction. Build from our verified canonical board files, preserve exact mask-to-row mappings and absent-key errors, use a mixed hash suitable for structured card masks, keep occupancy bounded, and include capacities plus temporary board arrays in memory budgeting. No original hash constants or implementation are needed. This changes no chance sampling or RNG calls. Speed still requires A/B evidence.
* Full 1326-column tables remove compressed-column popcounts at the cost above. Preserve row order, suit mapping, all bucket IDs and blocker rejection. Test all resource rows/valid columns and representative physical suit permutations; our prior exhaustive 64-bucket flop oracle does not prove equivalence for every turn/river profile.
* Eagerly filling a street for all players matches the original `lV` strategy. It simplifies the repeated cache-hit path but may perform unnecessary work for seats never queried, especially larger/fold-heavy games. Compare it separately at three and nine players. Dynamic/player-specific tables must retain their own valid-seat rules.
* A narrower hot cache-hit path is plausible, but removing per-node bucket-range validation is safe only after validating all node/actor/street bucket bounds at load time. Otherwise malformed/imported topology can produce a silent out-of-range access. Preserve the slow checked path for unsupported/dynamic layouts.

No speedup, universal HRC equivalence, perfect-hash implementation or exact runtime allocation/collision distribution has been established by this static audit. In particular, the different equal-suit tie permutation should not be changed casually; retain established mappings and use original resource/oracle tests when altering canonicalization.

## Provenance separation and production review follow-up

The retained REA export is `analysis/hrc-deep/round3-storage-20261108-rea-evidence.json`, SHA-256 `812a2a4cbb062055fc1ba4b75385a76e553ab27104b368bf9000d5736aec4116`. It identifies the same original JAR listed above and contains three records: artifact inventory (`ev_8207ff047fc3bb720fea2e38938583d55b935a040c250d25c83aa61270277631`), artifact inspection (`ev_5bd5997f323b6d08e8db9cbd0664e7ac46d81dcfe90391a0c3e422e8debc5d42`), and a derived summary view. Its providers are the REA safe artifact graph and analysis-view projection. The summary reports 1,104 ZIP entry occurrences, 1,103 graph nodes and no inventory integrity contradictions. These are container-inventory results, not Java method analysis, JIT observations or proof of complete application understanding.

The method-level evidence in this report was produced separately through shell `javap -p -c -s`, together with the earlier ordinal-organized Vineflower output. It must not be attributed to REA or JEB decompilation. The identity links, record identifiers, production header hashes and test source hashes are collected in `analysis/hrc-deep/round3-abstraction-20261108/provenance-summary.json`. No shared REA target was opened or changed for this worker's audit.

Following the parent's A/B selection and integration, a read-only review of production `native/hrc_flat_board_map.hpp` and `native/hrc_cards.hpp` found no issue in the currently used construct → move into street → publish → immutable lookup lifecycle. In particular, half occupancy guarantees a terminating empty slot for missing-key probes, duplicate inserts preserve the prior value, capacity arithmetic rejects overflow before allocation, and reserve allocates both arrays in locals before publishing them. The loader retains row ordering/card-count checks and bucket-domain validation. The main solver's preflight estimate now includes power-of-two key/value arrays plus board-file temporaries, replacing the earlier generic `6 * boardsBytes` term. This is a bounded code review, not a proof of every possible use of the container.

Persistent verification is now in `scripts/native/flat_board_map_probe.cpp` and `tests/test_hrc_flat_board_map.py`. The probe directly includes the production header; it does not require the isolated frozen baseline to remain available. Its independent row oracle is `std::unordered_map`; its bucket oracle reads selected raw u16 rows and enumerates legal hole pairs in ascending card-combo order, without calling our compressed-column formula to calculate expected values. All 11 tests passed:

* 64 deliberately colliding entries wrapping past the last slot; 10,000 absent keys; duplicate/sentinel/capacity/overflow rejection; move preservation; 80,000 concurrent immutable reads.
* All 152,646 installed canonical board keys map to their exact resource row.
* 256 sampled rows per street, 768 total, cover all legal holes within those rows: 866,560 bucket values match the raw resources.
* Actual map array/container bytes are 7,127,208, below the 7,127,592-byte map budget. The checked array/loader-temporary bound is 176,249,331 bytes, below the production resource reservation of 176,394,763. These are accounting bounds, not process working-set measurements.
* Synthetic truncated, duplicate, wrong-card-count and out-of-domain resources are rejected; installed resources are neither copied into product code nor modified.

Command: `.venv/Scripts/python.exe -m pytest tests/test_hrc_flat_board_map.py -q`. Result data: `.research-cache/flat-board-map-tests/resource-result.json`. This review changed only the test/probe and evidence notes. No throughput benchmark or training was run in this follow-up; performance conclusions belong to the parent's separately frozen A/B reports. The rejected wide-row and sentinel candidates remain research artifacts and were not added to production by this worker.
