"""Compare independent C++ terminal utilities with audited original HRC bytes.

Inputs are synthetic settled chip vectors and explicit killer masks. This does
not run HRC's application, a solver job, or its settlement algorithm. The small
allowlisted loader executes original kC/kB/lk/lj/ll/kE/kW and context compaction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import runpy
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(r"D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe")
JAR = Path(r"D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar")
EXPECTED_JAR_SHA = "25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43"


def run():
    helpers = runpy.run_path(str(ROOT / "tests/test_hrc_equity.py"))
    cases = [c for c in helpers["fixtures"]() if c.get("mode", 1) == 1]
    rng = random.Random(20261105)
    for n in range(2, 11):
        for variant in range(15):
            initial = [rng.choice([100, 200, 400, 800]) for _ in range(n)]
            live = sorted(rng.sample(range(n), rng.randint(1, n)))
            final, masks = [0] * n, [0] * n
            for i in live:
                final[i] = initial[i]
            for i in set(range(n)) - set(live):
                killers = rng.sample(live, min(len(live), rng.randint(1, 4)))
                masks[i] = sum(1 << j for j in killers)
                for j in killers:
                    final[j] += initial[i] // len(killers)
                final[killers[0]] += initial[i] % len(killers)
            mode = variant % 3
            case = {"id": f"original_{n}_{variant}", "initial": initial, "final": final, "masks": masks,
                    "payouts": sorted([rng.randint(0, 1000) / 10 for _ in range(rng.randint(0, n))], reverse=True),
                    "bounty_mode": mode}
            if mode:
                case["bounties"] = [12.5] * n if mode == 1 else [rng.randint(0, 1000) / 10 for _ in range(n)]
                case["alpha"] = 1 if mode == 1 else rng.choice([0, .1, .25, .5, .75, 1])
            cases.append(case)
    sha = hashlib.sha256(JAR.read_bytes()).hexdigest()
    if sha != EXPECTED_JAR_SHA:
        raise RuntimeError(f"Unreviewed original JAR: {sha}")
    out = ROOT / "analysis/hrc-deep/probes"
    out.mkdir(parents=True, exist_ok=True)
    inputs = out / "bounty-inputs.tsv"
    lines = [helpers["terminal_line"](case) for case in cases]
    inputs.write_text("\n".join(lines) + "\n", encoding="utf-8")
    classes = ROOT / "analysis/hrc-deep/java-tools"
    classes.mkdir(parents=True, exist_ok=True)
    source = ROOT / "scripts/java/OriginalBountyProbe.java"
    subprocess.run([str(JAVA.with_name("javac.exe")), "-d", str(classes), str(source)], check=True, capture_output=True)
    command = [str(JAVA), "-cp", str(classes), "OriginalBountyProbe", str(JAR), str(inputs)]
    start = time.perf_counter()
    original_run = subprocess.run(command, check=True, capture_output=True, text=True)
    original_seconds = time.perf_counter() - start
    (out / "bounty-original-output.jsonl").write_text(original_run.stdout, encoding="utf-8")
    records = [json.loads(line) for line in original_run.stdout.splitlines()]
    originals = {row["id"]: row for row in records if row["kind"] == "case"}
    executable = helpers["build_probe"]()
    start = time.perf_counter()
    natives = helpers["run_lines"](executable, lines)
    native_seconds = time.perf_counter() - start
    (out / "bounty-independent-output.jsonl").write_text("\n".join(map(json.dumps, natives)) + "\n", encoding="utf-8")
    results = []
    for case, native in zip(cases, natives):
        original = originals[case["id"]]
        fields = ["total", "baseline", "immediate_prizes", "immediate_bounties", "remaining_bounties", "future_equities"]
        errors = {field: max(abs(a-b) for a, b in zip(native[field], original[field])) for field in fields}
        expected_total = sum(case["payouts"]) + sum(case.get("bounties", []))
        conservation_error = abs(sum(native["total"]) - expected_total)
        oracle_error = None
        if sum(s > 0 for s in case["final"]) <= 7:
            independent = helpers["oracle"](case)
            oracle_error = max(abs(a-b) for a, b in zip(native["total"], independent["total"]))
        passed = max(*errors.values(), conservation_error, oracle_error or 0) < 1e-9
        results.append({"input": case, "original": original, "independent": native, "max_errors": errors,
                        "conservation_error": conservation_error, "permutation_oracle_error": oracle_error, "passed": passed})
    report = {
        "artifact": str(JAR), "sha256": sha, "command": command,
        "scope": "Original unmodified local-table terminal ICM/KO/PKO mathematical contexts/evaluators. Synthetic final chip vectors and explicit killer sets; no application, license initialization, solver traversal, MTT, FGS or original settlement invoked.",
        "sources": {
            "kC": "a(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D",
            "kB": ["a(Lnet/holdemresources/internal/kI;Lnet/holdemresources/internal/lE;D)[D", "a(Lnet/holdemresources/internal/kI;Lnet/holdemresources/internal/lE;[DD)[D"],
            "lk": ["a(Lnet/holdemresources/internal/lE;)[D", "a(Lnet/holdemresources/internal/lE;)Lnet/holdemresources/internal/kH;", "b(I)D"],
            "ll": ["a(Lnet/holdemresources/internal/kG;)[D", "a(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D"],
            "static_evidence": "research/HRC-EQUITY-ABSTRACTION.md sections 3-4; analysis/hrc-deep/equity/*/bytecode.txt",
        },
        "loader_audit": "Platform parent; exact JAR SHA pinned; narrow class allowlist. lF is a synthetic immutable original outcome. lc/lD/kH only compact and rotate survivor seat mapping, which is mapped back. ky constructor initializes kz/kA enum constants only. Loaded classes are individually hashed below. No lH method is called; descriptor-only allowance does not execute settlement.",
        "class_hashes": [row for row in records if row["kind"] == "class"],
        "header_sha256": hashlib.sha256((ROOT / "native/hrc_equity.hpp").read_bytes()).hexdigest(),
        "original_probe_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "independent_probe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "case_count": len(cases), "passed": all(r["passed"] for r in results),
        "max_numeric_error": max(max(r["max_errors"].values()) for r in results),
        "max_conservation_error": max(r["conservation_error"] for r in results),
        "original_seconds": original_seconds, "independent_seconds": native_seconds,
        "numerics": "Independent forward subset ICM uses long-double intermediates; original reverse subset ICM uses doubles. Tolerance 1e-9 absolute for these test amounts; not a bit-identical floating point implementation.",
        "cases": results,
    }
    path = ROOT / "reports/hrc-original-bounty-validation.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("case_count", "passed", "max_numeric_error", "max_conservation_error", "original_seconds", "independent_seconds")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
