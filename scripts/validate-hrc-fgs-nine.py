"""Bounded nine-player depth-one original/C++ FGS regression.

The Python reference's settlement and chance-table construction are already
covered separately; avoid repeating its much slower 414-state recursion here.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_fgs import ChanceTables


def run():
    plugins=Path("D:/Program Files/HRC/plugins")
    java=Path("D:/Tools/REA-Research/jdk-21.0.13+9/bin/java.exe")
    zig=Path("D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe")
    out=ROOT/"analysis/hrc-deep/fgs/nine-validation";out.mkdir(parents=True,exist_ok=True)
    tsv=out/"inputs.tsv"
    tsv.write_text("nine_depth1\t400,600,800,1000,900,700,500,1100,1200\t100,60,20\t100,50,0\t1\t1\tfalse\tfalse\t0\t0\t-1\t\t0\t\t1\n",encoding="utf-8")
    cache=out/"chance-cache.bin";tables=ChanceTables.from_installation(plugins);tables.write(cache)
    subprocess.run([str(java.with_name("javac.exe")),"-d",str(out),str(ROOT/"scripts/java/OriginalFgsProbe.java")],check=True,capture_output=True,text=True)
    command=[str(java),"-Xmx2g","-cp",str(out),"OriginalFgsProbe",str(plugins),str(tsv)]
    original=subprocess.run(command,check=True,capture_output=True,text=True,timeout=180)
    (out/"original.jsonl").write_text(original.stdout,encoding="utf-8")
    exe=out/"fgs_probe.exe"
    compile_command=[str(zig),"c++","-std=c++17","-O3","-ffp-contract=off",str(ROOT/"scripts/native/fgs_probe.cpp"),"-o",str(exe)]
    compiled=subprocess.run(compile_command,capture_output=True,text=True,timeout=180)
    if compiled.returncode:raise RuntimeError(compiled.stderr)
    native=subprocess.run([str(exe),str(cache),str(tsv)],check=True,capture_output=True,text=True,timeout=180)
    (out/"native.jsonl").write_text(native.stdout,encoding="utf-8")
    j=[json.loads(line) for line in original.stdout.splitlines()];c=[json.loads(line) for line in native.stdout.splitlines()]
    jr=next(x for x in j if x["kind"]=="fgs");cr=next(x for x in c if x["kind"]=="fgs")
    root_error=max(abs(a-b) for a,b in zip(jr["values"],cr["values"]))
    jo={(tuple(x["participants"]),x["result"]):x for x in j if x["kind"]=="outcome"}
    failures=[];maximum=0
    for row in c:
        if row["kind"]!="outcome":continue
        expected=jo[tuple(row["participants"]),row["result"]]
        for field in ("stacks","winner_masks","tied","next_stacks","mapping","next_skip_sb","next_bounties"):
            if row[field]!=expected[field]:failures.append({"participants":row["participants"],"result":row["result"],"field":field})
        for field in ("ordinary_values","fgs_values"):
            error=max(abs(a-b) for a,b in zip(row[field],expected[field]));maximum=max(maximum,error)
            if error>1e-8:failures.append({"participants":row["participants"],"result":row["result"],"field":field,"error":error})
    controls=[x for x in c if x["kind"]=="control"]
    sources=[ROOT/"native/hrc_fgs.hpp",ROOT/"native/hrc_equity.hpp",ROOT/"preflop_lab/hrc_fgs.py",ROOT/"scripts/java/OriginalFgsProbe.java",ROOT/"scripts/native/fgs_probe.cpp",Path(__file__)]
    report={"scope":"Nine-player, depth-one FGS; original kX versus independent C++ full recursion and all 1209 root participant/showdown outcomes. Python recursive FGS not run for this large case.",
        "input_tsv":tsv.read_text(),"original":jr,"native":cr,"root_error":root_error,"max_outcome_error":maximum,
        "outcome_count":len(jo),"failures":failures,"native_budget_controls":controls,
        "passed":root_error<=1e-8 and maximum<=1e-8 and not failures and all(r["passed"] for r in controls),
        "resources":tables.provenance,"artifacts":[r for r in j if r["kind"]=="artifact"],"loaded_classes":[r for r in j if r["kind"]=="class"],
        "java_command":command,"native_compile_command":compile_command,
        "evidence_hashes":{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (tsv,out/"original.jsonl",out/"native.jsonl")},
        "source_hashes":{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (ROOT/"reports/hrc-original-fgs-nine-validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({key:report[key] for key in ("passed","outcome_count","root_error","max_outcome_error")},indent=2))
    if not report["passed"]:raise SystemExit(1)


if __name__=="__main__":run()
