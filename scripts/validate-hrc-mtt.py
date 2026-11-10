"""Compare independent Python/C++ MTT kernels to isolated original lg bytecode.

Only the explicitly audited numerical class allowlist is loaded. Reproduction
requires the user's local reviewed HRC installation; production code does not.
No saved strategies, terminal utilities, GUI, or full HRC solver are loaded.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.mtt_equity import mtt_icm_equities

JAVA = Path(r"D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe")
PLUGINS = Path(r"D:\Program Files\HRC\plugins")
MAIN = PLUGINS / "net.holdemresources.calculator_4.1.0.202603231401.jar"
QUANT = PLUGINS / "net.holdemresources.calculator.mavendependencies_0.2.0/org.jquantlib/jquantlib-0.2.4.jar"
COMMONS = PLUGINS / "org.apache.commons.lang3_3.17.0.jar"


def input_cases():
    result = []
    def add(name, table, prizes, outside=()):
        result.append(dict(id=name, table=list(table), payouts=list(prizes), other=list(outside)))
    add("one_survivor", [10], [100])
    add("one_survivor_old_full_schedule", [10], [100, 50, 20])
    add("smoke", [20, 30, 50], [100, 50, 20], [10, 15])
    add("zero_prizes", [2, 4, 9], [0, 0, 0])
    add("small_equal_prizes", [2, 4, 9], [100, 100, 100])
    add("small_equal_prizes_old_schedule", [2, 4, 9], [100] * 7)
    rng = random.Random(20261105)
    for n in range(2, 9):
        local = [rng.randint(10, 100) for _ in range(n)]
        prizes = sorted([rng.randint(0, 100) for _ in range(n)], reverse=True)
        add(f"small_{n}", local, prizes)
        add(f"small_{n}_outside", local[:2], prizes, local[2:])
    for n in (0, 1, 8, 99, 100, 1000):
        outside = [10 + ((i * 47) % 89) for i in range(n)]
        add(f"field_{n}_top3", [20, 35, 90], [1000, 500, 200], outside)
        add(f"field_{n}_first2", [20, 35, 90], [1000, 500], outside)
        add(f"field_{n}_winner", [20, 35, 90], [1000], outside)
        add(f"field_{n}_equal_paid", [20, 35, 90], [100] * (n + 3), outside)
        add(f"field_{n}_equal_stacks", [50, 50, 50], [1000, 500, 200], [50] * n)
        add(f"field_{n}_extreme", [0.001, 10, 10000], [1000, 500, 200], outside)
        add(f"field_{n}_stepped", [5, 25, 100], ([1000, 700, 500] + [200] * 5 + [100] * 20)[:n + 3], outside)
    add("threshold_99_same_field", [30, 30], [1000, 500, 200], [30] * 99)
    add("threshold_100_same_field", [30], [1000, 500, 200], [30] * 100)
    add("small_scaled_chips", [140, 210, 350], [100, 50, 20], [70, 105])
    add("tiny_unit_stacks", [2e-100, 3e-100, 5e-100], [100, 50, 20], [1e-100, 1.5e-100])
    add("huge_unit_stacks", [2e100, 3e100, 5e100], [100, 50, 20], [1e100, 1.5e100])
    add("large_5000_top3", [20, 35], [1000, 500, 200], [10 + i % 79 for i in range(5000)])
    add("large_1000_tied_tail", [20, 35], [1000, 500] + [100] * 250, [10 + i % 79 for i in range(1000)])
    add("large_100_equal_old_schedule", [20, 35], [100] * 120, [10 + i % 79 for i in range(100)])
    add("ratio_1e12", [0.00001, 10, 10000000], [1000, 500, 200], [30] * 100)
    add("ratio_1e15", [0.00000001, 10, 10000000], [1000, 500, 200], [30] * 100)
    return result


def boundary_cases():
    return [dict(id="unresolvable_total", table=[1, 1e18], payouts=[100, 50], other=[]),
            dict(id="overflowing_total", table=[1e308, 1e308], payouts=[100, 50], other=[]),
            dict(id="zero_stack", table=[0, 10], payouts=[100, 50], other=[])]


def exact_finish_order(stacks, prizes):
    """Independent forward winner selection, not integration or rank polynomial."""
    n = len(stacks)
    values = [0.0] * n
    states = {0: 1.0}
    for prize in prizes[:n]:
        nxt = {}
        for winners, reach in states.items():
            remaining = [p for p in range(n) if not winners & (1 << p)]
            total = math.fsum(stacks[p] for p in remaining)
            for p in remaining:
                probability = reach * stacks[p] / total
                values[p] += prize * probability
                key = winners | (1 << p)
                nxt[key] = nxt.get(key, 0.0) + probability
        states = nxt
    return values


def run():
    out = ROOT / "analysis/hrc-deep/mtt/validation"
    out.mkdir(parents=True, exist_ok=True)
    cases = input_cases()
    boundaries = boundary_cases()
    case_file = out / "inputs.tsv"
    case_file.write_text("".join(c["id"] + "\t" + "\t".join(",".join(map(str, c[key])) for key in ("table", "payouts", "other")) + "\n" for c in cases + boundaries), encoding="utf-8")
    java_command = [str(JAVA), "-cp", str(out), "OriginalMttProbe", str(MAIN), str(QUANT), str(COMMONS), str(case_file)]
    subprocess.run([str(JAVA.with_name("javac.exe")), "-d", str(out), str(ROOT / "scripts/java/OriginalMttProbe.java")], check=True, capture_output=True, text=True)
    original = subprocess.run(java_command, check=True, capture_output=True, text=True, timeout=180)
    (out / "original.jsonl").write_text(original.stdout, encoding="utf-8")
    records = [json.loads(line) for line in original.stdout.splitlines()]
    java_cases = {r["id"]: r for r in records if r["kind"] == "case"}
    zig = Path(r"D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe")
    if not zig.is_file():
        zig = Path(r"D:\Tools\REA-Research\zig-x86_64-windows-0.15.2\zig.exe")
    exe = out / "mtt_equity_probe.exe"
    compile_command = [str(zig), "c++", "-std=c++17", "-O3", "-ffp-contract=off", str(ROOT / "scripts/native/mtt_equity_probe.cpp"), "-o", str(exe)]
    compiled = subprocess.run(compile_command, capture_output=True, text=True, timeout=180)
    if compiled.returncode:
        raise RuntimeError(compiled.stderr)
    native = subprocess.run([str(exe), str(case_file)], check=True, capture_output=True, text=True, timeout=180)
    (out / "native.jsonl").write_text(native.stdout, encoding="utf-8")
    native_cases = {r["id"]: r for r in map(json.loads, native.stdout.splitlines())}
    results = []
    for c in cases:
        j = java_cases[c["id"]]
        cpp = native_cases[c["id"]]
        begin = time.perf_counter()
        py = mtt_icm_equities(c["table"], c["payouts"], c["other"])
        elapsed = time.perf_counter() - begin
        if "error" in j or "error" in cpp:
            results.append({**c, "original": j, "native": cpp, "python": py, "passed": False})
            continue
        error_py = max(abs(a - b) for a, b in zip(j["values"], py))
        error_cpp = max(abs(a - b) for a, b in zip(j["values"], cpp["values"]))
        field = c["table"] + c["other"]
        reference = exact_finish_order(field, c["payouts"])[:len(c["table"])] if len(field) <= 8 else None
        tolerance = 1e-8 + 1e-9 * max(c["payouts"])
        results.append({**c, "outside_count": len(c["other"]), "approximate": len(c["other"]) >= 100,
                        "original": j["values"], "python": py, "native": cpp["values"],
                        "python_seconds": elapsed, "native_nanoseconds": cpp["nanoseconds"], "java_nanoseconds": j["nanoseconds"],
                        "python_max_error": error_py, "native_max_error": error_cpp, "tolerance": tolerance,
                        "exact_finish_order": reference, "original_vs_exact_error": max(abs(a-b) for a,b in zip(j["values"],reference)) if reference else None,
                        "passed": max(error_py,error_cpp) <= tolerance})
    boundary_results = []
    for c in boundaries:
        try:
            py_boundary = {"values": mtt_icm_equities(c["table"], c["payouts"], c["other"])}
        except (ValueError, ArithmeticError) as exc:
            py_boundary = {"error": str(exc)}
        boundary_results.append({**c, "original": java_cases[c["id"]], "python": py_boundary,
                                 "native": native_cases[c["id"]],
                                 "passed": "error" in py_boundary and "error" in native_cases[c["id"]]})
    report = {
        "scope": "MTT lg equity on positive surviving stacks; 14 allowlisted pure numerical classes only. No application, licensing, resources, saved utilities or training executed.",
        "outside_threshold": 100, "case_count": len(results), "passed": all(r["passed"] for r in results + boundary_results),
        "max_python_error": max(r.get("python_max_error", math.inf) for r in results),
        "max_native_error": max(r.get("native_max_error", math.inf) for r in results),
        "java_command": java_command, "native_compile_command": compile_command,
        "artifacts": [r for r in records if r["kind"] == "artifact"],
        "loaded_classes": [r for r in records if r["kind"] == "class"],
        "inputs_sha256": hashlib.sha256(case_file.read_bytes()).hexdigest(),
        "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            ROOT / "preflop_lab/mtt_equity.py", ROOT / "native/hrc_mtt.hpp", ROOT / "scripts/java/OriginalMttProbe.java", ROOT / "scripts/native/mtt_equity_probe.cpp", Path(__file__))},
        "cases": results, "domain_boundaries": boundary_results,
    }
    report_file = ROOT / "reports/hrc-original-mtt-validation.json"
    report_file.parent.mkdir(exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("case_count", "passed", "max_python_error", "max_native_error")}, indent=2))
    for r in results:
        if not r["passed"]:
            print(r["id"], r.get("python_max_error"), r.get("native_max_error"))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
