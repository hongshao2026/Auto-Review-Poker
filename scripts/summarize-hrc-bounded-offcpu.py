"""Strict off-CPU accounting of a retained common-training trace interval.

No thread start is invented. This consumes the existing schema-2 cache only,
never reruns WPR/tracerpt or a solver. An explicit coordinated CPU window is
required because parsing and symbolizing the retained trace is substantial.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".research-cache/cpu-round4-20261108/nine-etw"
CPU_REPORT = ROOT / "reports/hrc-round4-nine-cpu-stacks-20261108.json"
TICKS = 10_000_000
TRAIN_TOKENS = ("Engine::vector", "Engine::scalar", "ParallelTrainer::adaptive_work",
                "ParallelTrainer::work", "Engine::step")
TRAIN_FUNCTION = re.compile("(?:"+"|".join(map(re.escape, TRAIN_TOKENS))+")(?![A-Za-z0-9_])")
WAIT_NAMES = {31: "WrDispatchInt", 32: "WrPreempted", 33: "WrYieldExecution",
              34: "WrFastMutex", 35: "WrGuardedMutex", 36: "WrRundown"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clipped(start, end, low, high):
    return max(0, min(end, high) - max(start, low))


def cpu_intervals(switches, tids):
    """Independently account running intervals from every logical CPU stream."""
    last, first, own_runs = {}, {}, defaultdict(list)
    mismatches, same_thread = [], 0
    for when, cpu, new, old, state, reason in switches:
        first.setdefault(cpu, when)
        if cpu in last:
            previous, current = last[cpu]
            if current != old:
                mismatches.append((when, cpu, current, old))
            require(when >= previous, "CPU event timestamps decreased")
            if current in tids and when > previous:
                own_runs[current].append((previous, when, cpu))
        last[cpu] = when, new
        same_thread += old == new
    require(not mismatches, f"CSwitch continuity failed: {len(mismatches)}; {mismatches[:5]}")
    # An individual thread cannot run on two logical CPUs simultaneously.
    for tid, intervals in own_runs.items():
        intervals.sort()
        end = -1
        for start, stop, cpu in intervals:
            require(start >= end, f"Thread {tid} has overlapping CPU residency")
            end = stop
    return first, last, own_runs, same_thread


def own_off_intervals(events, tid, start_running=None, low=None):
    """Pair independent outgoing/incoming events, retaining wait metadata.

    Equal-timestamp CPU migration is a zero-length transition. Consume ties in
    the order required by the known thread state, rather than CPU-number order.
    Initial off/on state is unknown and is excluded by the eventual lower bound.
    """
    events.sort(key=lambda x: x[0])
    pending = (low, -1, -1) if start_running is False else None
    seen = start_running is not None
    result = []
    for when, grouped in itertools.groupby(events, key=lambda x: x[0]):
        rows = list(grouped)
        ins = [x for x in rows if x[1] == "in"]
        outs = [x for x in rows if x[1] == "out"]
        # No identity assumption is needed before the first retained transition.
        if not seen and not outs:
            require(len(ins) == 1, f"Thread {tid} has duplicate leading incoming events")
            seen = True
            continue
        while ins or outs:
            if pending is None:
                require(outs, f"Thread {tid} has incoming twice without outgoing at {when}")
                row = outs.pop(0)
                pending = (when, row[2], row[3])
            else:
                require(ins, f"Thread {tid} has outgoing twice without incoming at {when}")
                ins.pop(0)
                result.append((*pending, when))
                pending = None
            seen = True
            # A lone outgoing leaves the thread off CPU until a later group.
            if pending is not None and not ins and not outs:
                break
    return result, pending


def category(functions, tid, main_tid):
    condvar = any("condition_variable::wait" in s or "__libcpp_condvar_wait" in s for s in functions)
    traversal = any(TRAIN_FUNCTION.search(s) for s in functions)
    if condvar and tid != main_tid and any("ParallelTrainer::worker" in s for s in functions) and not traversal:
        return "worker_control_condvar_resume"
    if condvar and tid == main_tid and any("ParallelTrainer::run_adaptive" in s or "ParallelTrainer::run(" in s for s in functions):
        return "coordinator_condvar_resume"
    if any("thread_yield" in s for s in functions):
        return "yield_resume"
    if traversal:
        return "traversal_resume"
    return "other_or_unresolved_resume"


def overlap_histogram(intervals, low, high, main_tid):
    """Association only: overlap of parked-worker and coordinator resume chains."""
    changes = defaultdict(list)
    for tid, start, stop, kind in intervals:
        if kind not in ("worker_control_condvar_resume", "coordinator_condvar_resume"):
            continue
        start, stop = max(start, low), min(stop, high)
        if stop > start:
            changes[start].append((tid, 1))
            changes[stop].append((tid, -1))
    changes.setdefault(low, [])
    changes.setdefault(high, [])
    current, previous, histogram = Counter(), low, Counter()
    for when in sorted(changes):
        workers = sum(v for tid, v in current.items() if tid != main_tid)
        coordinator = current[main_tid] > 0
        histogram[workers, coordinator] += when - previous
        for tid, delta in changes[when]:
            current[tid] += delta
            require(current[tid] in (0, 1), "Overlapping control-resume intervals for one thread")
        previous = when
    require(all(v == 0 for v in current.values()), "Unbalanced control-resume interval sweep")
    return [dict(parked_workers=n, coordinator_wait_associated=coordinator, seconds=ticks/TICKS)
            for (n, coordinator), ticks in sorted(histogram.items()) if ticks]


def self_test():
    switches = [(0, 0, 7, 99, 1, 0), (10, 0, 99, 7, 5, 6),
                (20, 0, 7, 99, 1, 0), (30, 0, 99, 7, 1, 33), (40, 0, 7, 99, 1, 0)]
    _, _, runs, _ = cpu_intervals(switches, {7})
    off, pending = own_off_intervals([(10,"out",5,6), (20,"in",0,0),
                                     (30,"out",1,33), (40,"in",0,0)], 7)
    require(pending is None and sum(clipped(a,b,10,35) for a,b,_ in runs[7]) == 10, "Synthetic on CPU mismatch")
    require(sum(clipped(a,b,10,35) for a,_,_,b in off) == 15, "Synthetic off CPU mismatch")
    migration, pending = own_off_intervals([(0,"in",0,0), (10,"in",0,0),
                                           (10,"out",1,32), (20,"out",5,6), (30,"in",0,0)], 7)
    require(migration == [(10,1,32,10),(20,5,6,30)] and pending is None, "Tie migration mismatch")
    bounded, pending = own_off_intervals([(20,"in",0,0),(30,"out",1,33)], 7, False, 15)
    require(bounded == [(15,-1,-1,20)] and pending == (30,1,33), "Left-clipped off state mismatch")
    require(category(["ParallelTrainer::worker", "std::__1::condition_variable::wait"], 7, 1)
            == "worker_control_condvar_resume", "worker must not match work function token")
    try:
        cpu_intervals([(0,0,7,99,1,0),(10,0,99,8,1,0)], {7})
    except ValueError:
        pass
    else:
        raise ValueError("Broken continuity accepted")
    try:
        own_off_intervals([(0,"out",5,6),(10,"out",5,6)], 7)
    except ValueError:
        pass
    else:
        raise ValueError("Duplicate outgoing accepted")
    return {"synthetic_accounting_ties_and_rejection": True}


def analyze():
    cache = OUT / "parsed-solver-events.json"
    prior = json.loads(CPU_REPORT.read_text())
    require(prior["status"] == "validated_cpu_only", "No validated retained CPU baseline")
    cache_sha = sha(cache)
    require(cache_sha == prior["input_cache_sha256"], "Parsed cache differs from CPU-only evidence")
    p = json.loads(cache.read_text())
    require(p["source_identity"] == prior["trace_identity"], "Trace identity changed")
    require(p["source_identity"]["parser_schema"] == 2, "Unexpected parsed event schema")
    require(p["headers"] and all(int(h["EventsLost"]) == int(h["BuffersLost"]) == 0 for h in p["headers"]), "Lost ETW events")
    require(all(int(h["PerfFreq"]) == TICKS for h in p["headers"]), "QPC frequency must be 10MHz")
    run = json.loads((OUT / "report.json").read_text())
    with (OUT / "sampled/monitor.jsonl").open() as stream:
        first_monitor = json.loads(next(stream))
    initial_tids = list(map(int, first_monitor["thread_cpu_seconds"]))
    require(initial_tids == [55880], f"Unexpected initial process monitor thread identity: {initial_tids}")
    main_tid = initial_tids[0]
    threads = {int(k): v for k,v in p["threads"].items()}
    require(len(threads) == 21 and main_tid in threads and 52036 in threads, "Unexpected retained thread inventory")
    ordered_ends = sorted(threads, key=lambda tid: threads[tid]["end"])
    workers = ordered_ends[:19]
    require(main_tid not in workers and 52036 not in workers, "End-cluster includes main/helper thread")
    cluster = [threads[tid]["end"] for tid in workers]
    require(max(cluster)-min(cluster) <= 1_000_000, "Worker End cluster is not within 100ms")
    require(min(threads[tid]["end"] for tid in (main_tid,52036)) > max(cluster), "Worker End cluster is not separated from main/helper")
    tids = {main_tid, *workers}
    recovered = json.loads((OUT / "recovered-unload-image.json").read_text())
    require(recovered["pid"] == run["native"]["pid"] == prior["pid"], "Recovered image PID mismatch")
    images = recovered["images"]
    name = Path(run["plan"]["build"]["executable_path"]).name.lower()
    own = next(x for x in images if x["path"].replace("\\","/").split("/")[-1].lower() == name)
    require(sha(run["plan"]["build"]["executable_path"]) == prior["executable_sha256"], "Symbol executable identity changed")
    spec = importlib.util.spec_from_file_location("bounded_etw_symbols", ROOT / "scripts/summarize-hrc-etw.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    symbols = module.Symbols(images)
    offset = prior["offset_ticks"]
    stack_at = defaultdict(list)
    for when, qpc, tid, frames in p["stacks"]:
        stack_at[qpc+offset, tid].extend(frames)
    def own_functions(frames):
        return [symbols.resolve(address)["symbol"] for address in frames
                if own["base"] <= address < own["base"]+own["size"]]
    training, matched, all_samples, train_per_tid = [], 0, 0, Counter()
    strict_exclusive, strict_inclusive = Counter(), Counter()
    legacy_training = 0
    for when,cpu,tid,ip in p["samples"]:
        if tid not in threads:
            continue
        all_samples += 1
        frames = stack_at.get((when,tid), [])
        if not frames:
            continue
        matched += 1
        functions = own_functions(frames)
        if any(any(token in function for token in TRAIN_TOKENS) for function in functions):
            legacy_training += 1
        if any(TRAIN_FUNCTION.search(function) for function in functions):
            training.append((when,cpu,tid,ip))
            train_per_tid[tid] += 1
            strict_exclusive[symbols.resolve(ip)["symbol"]] += 1
            strict_inclusive.update(set(functions))
    require(all_samples == prior["all_retained_own_samples"] and matched == prior["matched_own_stacks"], "Exact-stack coverage no longer reproduces CPU baseline")
    require(legacy_training == prior["training_stack_samples"], "Legacy training stack selection no longer reproduces CPU baseline")
    require(len(training) > 1000, "Insufficient strict traversal stack samples")
    require(all(train_per_tid[tid] > 0 for tid in tids) and not train_per_tid[52036], "Worker identity not supported by traversal samples")
    switches = sorted(p["switches"], key=lambda row: row[0])  # stable: preserve equal-time original order
    first_cpu, last_cpu, runs, same_thread = cpu_intervals(switches, tids)
    events, first_out, first_in = defaultdict(list), {}, {}
    for when,cpu,new,old,state,reason in switches:
        if new == old:
            continue
        if old in tids:
            first_out.setdefault(old,when)
            events[old].append((when,"out",state,reason))
        if new in tids:
            first_in.setdefault(new,when)
            events[new].append((when,"in",0,0))
    require(set(first_in) == set(first_out) == tids, "Missing retained incoming/outgoing transition")
    low = max(max(first_cpu.values()), max(first_out.values()), max(first_in.values()), min(row[0] for row in training))
    high = max(row[0] for row in training)
    require(high > low, "No positive common retained training interval")
    require(high < min(threads[tid]["end"] for tid in tids), "Training upper bound overlaps a thread End")
    require(all(when >= high for when,_ in last_cpu.values()), "Some logical CPUs lack a CSwitch bracketing the upper bound")
    bounded_exclusive, bounded_inclusive, bounded_samples = Counter(), Counter(), 0
    for when,cpu,tid,ip in training:
        if low <= when <= high:
            bounded_samples += 1
            bounded_exclusive[symbols.resolve(ip)["symbol"]] += 1
            bounded_inclusive.update(set(own_functions(stack_at.get((when,tid), []))))
    ready = defaultdict(list)
    for when,tid,flag in p["ready"]:
        if tid in tids and not flag & 6:
            ready[tid].append(when)
    for values in ready.values():
        values.sort()
    off_by_tid, reasons, split, resumes, first_frames = Counter(), Counter(), Counter(), Counter(), Counter()
    counts, durations, accounting, associated = Counter(), defaultdict(list), [], []
    exact_resume = 0
    yield_frames, yield_categories = Counter(), Counter()
    for tid in sorted(tids):
        running_at_low = any(start <= low < end for start,end,cpu in runs[tid])
        # Circular ETW buffers start at different timestamps on different CPUs.
        # Their incomplete prefix can contain an apparent second outgoing.
        # Initialize at the common lower bound from independent CPU occupancy;
        # never validate or invent missing prefix transitions. A left-clipped
        # already-off interval has unknown outgoing wait state/reason.
        bounded_events = [row for row in events[tid] if low < row[0] <= high]
        pairs, pending = own_off_intervals(bounded_events, tid, running_at_low, low)
        if pending:
            # Normally after the training boundary. If retained off until high,
            # its occupancy is still independently checked against CPU streams.
            pairs.append((*pending, high))
        for start,state,reason,end in pairs:
            span = clipped(start,end,low,high)
            if not span:
                continue
            off_by_tid[tid] += span
            reasons[state,reason] += span
            if state in (1,3,7):
                split["ready_or_deferred_ready"] += span
            elif state == 5:
                at = bisect.bisect_left(ready[tid],start)
                if at < len(ready[tid]) and ready[tid][at] <= end:
                    wake = ready[tid][at]
                    split["waiting_until_ready_event"] += clipped(start,wake,low,high)
                    split["ready_after_wait"] += clipped(wake,end,low,high)
                else:
                    split["waiting_without_eligible_ready_event"] += span
            else:
                split["other_state_"+str(state)] += span
            functions = own_functions(stack_at.get((end,tid), [])) if end != high or pending is None else []
            exact_resume += bool(functions)
            kind = category(functions,tid,main_tid)
            resumes[kind] += span
            counts[kind] += 1
            durations[kind].append(span/TICKS)
            first_frames[functions[0] if functions else "no_exact_own_resume_frame"] += span
            if reason == 33:
                yield_frames[functions[0] if functions else "no_exact_own_resume_frame"] += span
                yield_categories[kind] += span
            associated.append((tid,start,end,kind))
        on = sum(clipped(start,end,low,high) for start,end,cpu in runs[tid])
        residual = high-low-on-off_by_tid[tid]
        require(residual == 0, f"Thread {tid}: on+off residual {residual} ticks")
        accounting.append(dict(tid=tid,role="main_coordinator_and_worker" if tid==main_tid else "worker",
                               running_seconds=on/TICKS,off_seconds=off_by_tid[tid]/TICKS,
                               wall_seconds=(high-low)/TICKS,residual_ticks=residual))
    require(sum(split.values()) == sum(off_by_tid.values()), "Off-CPU subdivisions do not conserve time")
    hist = overlap_histogram(associated,low,high,main_tid)
    overlap = sum(row["parked_workers"]*row["seconds"] for row in hist if row["coordinator_wait_associated"])
    total_on = sum(row["running_seconds"] for row in accounting)
    require(total_on <= run["native"]["process_cpu_seconds"]+.01, "Retained running time exceeds full process CPU time")
    result = dict(schema="bounded-retained-offcpu-v1",status="validated_bounded_interval",pid=prior["pid"],
                  input_cache_sha256=cache_sha,source_identity=p["source_identity"],
                  executable_sha256=prior["executable_sha256"],script_sha256=sha(__file__),
                  cpu_report_sha256=sha(CPU_REPORT),main_tid=main_tid,worker_tids=workers,
                  excluded_helper_tid=52036,retained_thread_events=threads,
                  identity_basis="Initial monitor singleton main; earliest 19 End short cluster; every selected thread has traversal CPU samples; no fabricated Start",
                  interval=dict(low_ticks=low,high_ticks=high,seconds=(high-low)/TICKS,
                    definition="max(all CPUs first CSwitch, every worker/main first own-out and own-in, first training CPU sample) through last training CPU sample",
                    bounds=dict(first_cpu_switches=first_cpu,first_out=first_out,first_in=first_in,
                                first_training_sample=min(row[0] for row in training),last_training_sample=high)),
                  validation=dict(no_events_lost=True,exact_cpu_stack_coverage=matched/all_samples,
                    legacy_training_stack_samples_reproduced=legacy_training,
                    strict_training_stack_samples=len(training),
                    classification_correction="Function-boundary matching: ParallelTrainer::worker is not ParallelTrainer::work",
                    per_cpu_continuity_mismatches=0,
                    simultaneous_thread_residency_overlaps=0,all_thread_residual_ticks_zero=True,
                    all_cpu_right_bounds_bracket_high=True),
                  on_cpu_seconds=total_on,off_cpu_seconds=sum(off_by_tid.values())/TICKS,
                  off_cpu_subdivisions={k:v/TICKS for k,v in split.items()},
                  off_cpu_state_reasons=[dict(state=s,reason=r,reason_name="left_boundary_unknown" if r == -1 else WAIT_NAMES.get(r,"numeric_reason_"+str(r)),
                    seconds=v/TICKS) for (s,r),v in reasons.most_common()],
                  yield_execution_off_seconds=sum(v for (s,r),v in reasons.items() if r==33)/TICKS,
                  yield_execution_first_own_resume_frames=[dict(symbol=k,seconds=v/TICKS) for k,v in yield_frames.most_common(20)],
                  yield_execution_resume_categories={k:v/TICKS for k,v in yield_categories.items()},
                  thread_accounting=accounting,same_thread_switches_excluded=same_thread,
                  exact_own_resume_intervals=exact_resume,
                  resume_associations=[dict(category=k,seconds=v/TICKS,intervals=counts[k],
                    max_interval_seconds=max(durations[k])) for k,v in resumes.most_common()],
                  first_own_resume_frames=[dict(symbol=k,seconds=v/TICKS) for k,v in first_frames.most_common(30)],
                  parked_worker_overlap_histogram=hist,
                  parked_worker_seconds_overlapping_coordinator_wait_association=overlap,
                  strict_cpu_hotspots=dict(
                    definition="Exact stack contains a traversal/work function with identifier boundary, excluding worker-only control chains",
                    all_retained=dict(samples=len(training),
                        exclusive=[dict(symbol=k,samples=v,percent=100*v/len(training)) for k,v in strict_exclusive.most_common(30)],
                        inclusive=[dict(symbol=k,samples=v,percent=100*v/len(training)) for k,v in strict_inclusive.most_common(30)]),
                    bounded_interval=dict(samples=bounded_samples,
                        exclusive=[dict(symbol=k,samples=v,percent=100*v/bounded_samples) for k,v in bounded_exclusive.most_common(30)],
                        inclusive=[dict(symbol=k,samples=v,percent=100*v/bounded_samples) for k,v in bounded_inclusive.most_common(30)])),
                  limitations=["Only the retained tail common-training interval, not complete process lifecycle or uniformly sampled full training.",
                    "Old CPU-only 30,355 classification is reproduced for provenance, not reused as strict traversal: substring work also matched worker. Strict matching retains 30,340 samples; old report remains unchanged.",
                    "CSwitch StackWalk belongs to incoming TID; exact resume chains are associations, not proof of causal lock, owner or tail barrier.",
                    "Worker control-condvar and coordinator-condvar overlap is a tail-wait candidate; no internal 250-deal block/generation markers were recorded.",
                    "WrYieldExecution is OS reason 33 of the outgoing transition; off time includes ready scheduling delay and is not CPU execution time spent in yield().",
                    "ReadyThread split excludes flags & 6, follows existing parser convention, and records missing eligible Ready events explicitly.",
                    "A thread already off CPU at the common lower bound has unknown outgoing wait state/reason; no inference is made from the incomplete per-CPU prefixes.",
                    "Version-five CSwitch uses previously audited TraceEvent prefix; strict continuity and per-thread accounting are required."])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-window",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--report",type=Path,default=ROOT/"reports/hrc-round4-nine-bounded-offcpu-20261108.json")
    args=parser.parse_args()
    if not args.cpu_window:
        parser.error("Await parent CPU slot; pass --cpu-window only when authorized")
    if args.self_test:
        print(json.dumps(self_test()))
        return
    try:
        checks=self_test()
        result=analyze()
        result["synthetic_tests"]=checks
    except Exception as exc:
        result=dict(schema="bounded-retained-offcpu-v1",status="rejected",
                    error=type(exc).__name__+": "+str(exc),script_sha256=sha(__file__),
                    conclusion="No bounded off-CPU conclusion passed all validation gates")
        args.report.write_text(json.dumps(result,indent=2)+"\n")
        raise
    args.report.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("status","interval","validation","on_cpu_seconds",
          "off_cpu_seconds","yield_execution_off_seconds","resume_associations",
          "parked_worker_seconds_overlapping_coordinator_wait_association")},indent=2))


if __name__=="__main__":
    main()
