"""Rebuild chance cache and compare independent FGS with isolated original math.

Read-only original resources are local research inputs; only the probe executes
original classes. Independent production code receives no original utilities.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_fgs import (Calculator, ChanceTables, Config, Context,
    ThresholdSolver, _RESULTS, allin_outcome, forced_state, next_context, ordinary_terminal)

PLUGINS = Path("D:/Program Files/HRC/plugins")
JAVA = Path("D:/Tools/REA-Research/jdk-21.0.13+9/bin/java.exe")
ZIG = Path("D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe")


def cases():
    result = []
    def add(name, stacks, prizes=(100,60,20), **options):
        heads = options.pop("bounties", ())
        skip = options.pop("skip_sb", False)
        result.append((name, Context(tuple(stacks), tuple(heads), skip_sb=skip),
                       Config(tuple(prizes), 100, 50, max_seconds=180, **options)))
    for depth in (0,1,2,3):
        add(f"hu_depth{depth}", (1000,1000), (100,50), depth=depth)
    for depth in (0,1,2):
        add(f"three_depth{depth}", (1000,800,1200), depth=depth)
    add("three_short_bb", (250,120,70))
    add("three_short_sb", (250,30,200))
    add("three_depth3way_zero", (1000,800,1200), depth=2, depth3way=0)
    add("four_regular_ante", (400,600,800,1000), ante=10, depth=0)
    add("four_moving_button", (400,600,800,1000), moving_button=True)
    add("four_skip_sb", (400,600,800,1000), skip_sb=True)
    add("three_bb_ante_first", (250,120,70), ante=100, ante_type="BB_ANTE_FIRST")
    add("three_bb_blind_first", (250,120,70), ante=100, ante_type="BB_BLIND_FIRST")
    for straddle in ("SINGLE", "DOUBLE", "BUTTON"):
        add(f"four_straddle_{straddle.lower()}", (400,600,800,1000), straddle=straddle)
    add("hu_next_level", (1000,1000), (100,50), depth=2, next_level_at=1, next_level=(200,100,10))
    add("three_next_level", (1000,800,1200), next_level_at=1, next_level=(200,100,25))
    add("hu_fixed_ko", (1000,1000), (100,50), bounty_mode="FIXED", bounties=(20,20))
    add("hu_pko_depth2", (700,1300), (100,50), depth=2, bounty_mode="PROGRESSIVE", bounties=(20,80), immediate_fraction=.5)
    add("three_fixed_ko", (1000,800,1200), bounty_mode="FIXED", bounties=(20,20,20))
    for alpha in (0,.5,1):
        add(f"three_pko_alpha{alpha}", (1000,800,1200), bounty_mode="PROGRESSIVE", bounties=(20,50,80), immediate_fraction=alpha)
    add("three_pko_short_bbante", (250,120,70), ante=100, ante_type="BB_ANTE_FIRST", bounty_mode="PROGRESSIVE", bounties=(20,50,80), immediate_fraction=.5)
    add("three_equal_prizes", (1000,800,1200), (100,100,100))
    add("three_zero_prizes", (1000,800,1200), (0,), depth=0)
    add("six_depth0", (400,600,800,1000,900,700), depth=0)
    add("nine_depth0", (400,600,800,1000,900,700,500,1100,1200), depth=0)
    return result


def row(name, context, config):
    def vector(values): return ",".join(map(str,values))
    return "\t".join([name,vector(context.stacks),vector(config.payouts),vector((config.big_blind,config.small_blind,config.ante)),
        str(config.depth),str(config.depth3way),str(context.skip_sb).lower(),str(config.moving_button).lower(),
        str(["REGULAR","BB_ANTE_FIRST","BB_BLIND_FIRST"].index(config.ante_type)),str(["OFF","SINGLE","DOUBLE","BUTTON"].index(config.straddle)),
        str(config.next_level_at if config.next_level_at is not None else -1),vector(config.next_level or ()),
        str(["NONE","FIXED","PROGRESSIVE"].index(config.bounty_mode)),vector(context.bounties),str(config.immediate_fraction)])


def max_error(a,b):
    if len(a)!=len(b):return float("inf")
    return max((abs(x-y) for x,y in zip(a,b)),default=0.0)


def run():
    out = ROOT / "analysis/hrc-deep/fgs/validation"
    out.mkdir(parents=True,exist_ok=True)
    inputs = cases()
    tsv = out / "inputs.tsv"
    tsv.write_text("\n".join(row(*case) for case in inputs)+"\n",encoding="utf-8")
    tables = ChanceTables.from_installation(PLUGINS)
    chance_file = out / "chance-cache.bin"
    tables.write(chance_file)
    java_command = [str(JAVA),"-Xmx2g","-cp",str(out),"OriginalFgsProbe",str(PLUGINS),str(tsv)]
    subprocess.run([str(JAVA.with_name("javac.exe")),"-d",str(out),str(ROOT/"scripts/java/OriginalFgsProbe.java")],check=True,capture_output=True,text=True)
    original = subprocess.run(java_command,check=True,capture_output=True,text=True,timeout=180)
    (out/"original.jsonl").write_text(original.stdout,encoding="utf-8")
    records = [json.loads(line) for line in original.stdout.splitlines()]
    java = {r["id"]:r for r in records if r["kind"]=="fgs"}
    java_outcomes = {(r["id"],tuple(r["participants"]),r["result"]):r for r in records if r["kind"]=="outcome"}
    exe = out/"fgs_probe.exe"
    compile_command = [str(ZIG),"c++","-std=c++17","-O3","-ffp-contract=off",str(ROOT/"scripts/native/fgs_probe.cpp"),"-o",str(exe)]
    compiled = subprocess.run(compile_command,capture_output=True,text=True,timeout=180)
    if compiled.returncode:raise RuntimeError(compiled.stderr)
    native = subprocess.run([str(exe),str(chance_file),str(tsv)],check=True,capture_output=True,text=True,timeout=180)
    (out/"native.jsonl").write_text(native.stdout,encoding="utf-8")
    native_records = [json.loads(line) for line in native.stdout.splitlines()]
    cpp = {r["id"]:r for r in native_records if r["kind"]=="fgs"}
    cpp_outcomes = {(r["id"],tuple(r["participants"]),r["result"]):r for r in native_records if r["kind"]=="outcome"}
    chance_checks = []
    for r in records:
        if r["kind"]=="chance_hash":
            digest = hashlib.sha256(getattr(tables,r["name"]).tobytes()).hexdigest()
            chance_checks.append({**r,"independent_sha256":digest,"passed":digest==r["sha256"]})
    summaries, failures, python_outputs = [], [], []
    discrete_fields = ("stacks","winner_masks","tied","next_stacks","mapping","next_skip_sb")
    for name,context,config in inputs:
        solver = Calculator(config,tables)
        begin=time.perf_counter()
        py_values=solver.equities(context)
        py_seconds=time.perf_counter()-begin
        py_error=max_error(py_values,java[name]["values"])
        cpp_error=max_error(cpp[name]["values"],java[name]["values"])
        outcome_error=0.0;outcome_count=0;utilities={}
        for key,reference in java_outcomes.items():
            if key[0]!=name:continue
            _,participants,result=key
            outcome=allin_outcome(context,config,participants,_RESULTS[len(participants)][result])
            ordinary,_,heads=ordinary_terminal(context,config,outcome)
            child,order=next_context(context,outcome,config,heads)
            mapping=[-1]*len(context.stacks)
            for i,original_seat in enumerate(order):mapping[original_seat]=i
            computed={"stacks":list(outcome.stacks),"winner_masks":list(outcome.winner_masks),"tied":outcome.tied_award,
                "next_stacks":list(child.stacks),"mapping":mapping,"next_skip_sb":child.skip_sb,"next_bounties":list(child.bounties),
                "ordinary_values":ordinary,"fgs_values":solver.terminal(context,outcome)}
            python_outputs.append({"id":name,"participants":participants,"result":result,**computed})
            for label,observed in (("python",computed),("native",cpp_outcomes[key])):
                for field in discrete_fields:
                    if observed[field]!=reference[field]:failures.append({"id":name,"participants":participants,"result":result,"implementation":label,"field":field,"original":reference[field],"observed":observed[field]})
                for field in ("ordinary_values","fgs_values","next_bounties"):
                    error=max_error(observed[field],reference[field]);outcome_error=max(outcome_error,error)
                    if error>1e-8:failures.append({"id":name,"participants":participants,"result":result,"implementation":label,"field":field,"error":error})
            if participants not in utilities:utilities[participants]=[[0.0]*len(_RESULTS[len(participants)]) for _ in context.stacks]
            for player,value in enumerate(ordinary):utilities[participants][player][result]=value
            outcome_count+=1
        # Direct iteration traces for 2..4 players; larger native cases retain
        # full independent root and every participant/outcome comparison.
        threshold_differences=[];threshold_ev_error=0.0
        if len(context.stacks)<=4:
            remaining,posted,_,_=forced_state(context,config)
            threshold=ThresholdSolver(tables,utilities,remaining,posted)
            trace={r["iteration"]:r for r in records if r["kind"]=="threshold" and r["id"]==name}
            for iteration in range(201):
                if iteration in trace:
                    snapshot=trace[iteration]
                    threshold_ev_error=max(threshold_ev_error,max_error([threshold.value(i) for i in range(len(context.stacks))],snapshot["values"]))
                    n=len(context.stacks)
                    expected={**{(a,):snapshot["push"][a] for a in range(n)},
                        **{(a,b):snapshot["call"][a][b-a-1] for a in range(n) for b in range(a+1,n)},
                        **{(a,b,c):snapshot["overcall"][a][b-a-1][c-b-1] for a in range(n) for b in range(a+1,n) for c in range(b+1,n)}}
                    diff={str(k):[expected[k],v] for k,v in threshold.thresholds.items() if expected[k]!=v}
                    if diff:threshold_differences.append({"iteration":iteration,"differences":diff})
                if iteration<200:threshold.sweep()
        summary=dict(id=name,context=asdict(context),config=asdict(config),original=java[name]["values"],python=py_values,native=cpp[name]["values"],
            python_error=py_error,native_error=cpp_error,terminal_outcomes=outcome_count,max_outcome_error=outcome_error,
            python_seconds=py_seconds,native_nanoseconds=cpp[name]["nanoseconds"],native_states=cpp[name]["states"],native_sweeps=cpp[name]["sweeps"],
            threshold_ev_error=threshold_ev_error,threshold_index_differences=threshold_differences,
            passed=max(py_error,cpp_error,outcome_error,threshold_ev_error)<=1e-8 and not any(f["id"]==name for f in failures))
        summaries.append(summary)
        print(f"{name}: {'PASS' if summary['passed'] else 'FAIL'}, error={max(py_error,cpp_error,outcome_error):.3g}, outcomes={outcome_count}, python={py_seconds:.2f}s",flush=True)
    python_file=out/"python-outcomes.jsonl"
    python_file.write_text("\n".join(json.dumps(r) for r in python_outputs)+"\n",encoding="utf-8")
    controls=[r for r in native_records if r["kind"]=="control"]
    report={"scope":"Original kX/qI FGS and chance accumulation; independent live stacks, settlement, rotation, ICM/KO/PKO, threshold updates and recursive expected equities. No saved strategy or utility is production input.",
        "cases":summaries,"case_count":len(summaries),"terminal_outcome_count":len(java_outcomes),"chance_tables":chance_checks,
        "native_budget_controls":controls,"failures":failures,
        "passed":all(c["passed"] for c in summaries+chance_checks+controls) and not failures,
        "max_python_error":max(c["python_error"] for c in summaries),"max_native_error":max(c["native_error"] for c in summaries),
        "max_outcome_error":max(c["max_outcome_error"] for c in summaries),
        "artifacts":[r for r in records if r["kind"]=="artifact"],"loaded_classes":[r for r in records if r["kind"]=="class"],
        "resources":tables.provenance,"java_command":java_command,"native_compile_command":compile_command,
        "evidence_hashes":{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (tsv,out/"original.jsonl",out/"native.jsonl",python_file)},
        "source_hashes":{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"preflop_lab/hrc_fgs.py",ROOT/"native/hrc_fgs.hpp",ROOT/"native/hrc_equity.hpp",ROOT/"scripts/java/OriginalFgsProbe.java",ROOT/"scripts/native/fgs_probe.cpp",Path(__file__))}}
    path=ROOT/"reports/hrc-original-fgs-validation.json";path.write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("case_count","terminal_outcome_count","passed","max_python_error","max_native_error","max_outcome_error")},indent=2))
    if not report["passed"]:raise SystemExit(1)


if __name__=="__main__":run()
