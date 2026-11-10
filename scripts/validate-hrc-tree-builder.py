"""Compare generated contexts to original lB/lC/mG and full retained topologies."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_tree_builder import _Builder, build_tree, default_settings
from preflop_lab.hrc_tree import parse_gametree, replay_tree

JAVA = Path(r"D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe")
JAR = Path(r"D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar")


def run():
    rng = random.Random(20261105)
    rows, expected, configs = [], {}, []
    for case in range(160):
        n = rng.randint(2, 10)
        stacks = [rng.choice([10, 50, 100, 200, 400, 1000, 2000]) for _ in range(n)]
        settings = default_settings(n, stacks, 100)
        h = settings["handdata"]
        h["anteType"] = ["REGULAR", "BB_ANTE_ANTE_FIRST", "BB_ANTE_BLIND_FIRST"][case % 3]
        h["blinds"][2] = rng.choice([0, 10, 50, 100, 300])
        h["straddleType"] = ["OFF", "SINGLE", "DOUBLE", "BUTTON"][case % 4] if n >= 3 else "OFF"
        h["skipSb"] = bool(case % 2)
        pre = settings["treeconfig"]["preflop"]["settings"]
        pre["PREFLOP_SIZES"] = ["2bb,3bb,all-in", "2x,3x,all-in", "3x,all-in"]
        pre["PREFLOP_ALLIN_THRESHOLD"] = 100
        pre["ALLOWED_FLATS_PER_RAISE"] = [2, 2, 1, 0]
        pre["ALLOW_SB_COMPLETE"] = True
        settings["engine"]["maxactive"] = rng.randint(2, min(6, n))
        builder = _Builder(settings, 250000, None, None, "checkdown")
        context = builder.initial()
        configs.append(settings)
        for step in range(24):
            name = f"case_{case}_step_{step}"
            s = context.state
            actor = builder.actor(context)
            minimum, maximum = builder.limits(context, actor)
            expected[name] = {"actor": -1 if actor is None else actor, "street": s.street,
                "minimum": minimum, "maximum": maximum, "canRaise": minimum > 0,
                "currentBet": s.current_bet, "remaining": list(s.remaining),
                "streetContributions": list(s.street_paid), "previousContributions": list(s.dead_paid),
                "deadMoney": s.dead_money, "betCount": s.bets, "flatCount": s.flats,
                "participantsMask": s.participants, "foldedMask": s.folded,
                "history": [{"kind": a.name, "actor": a.actor, "street": a.street, "amount": a.amount, "allinFlag": a.allin} for a in context.history]}
            if minimum > 0:
                expected[name]["geometric66"] = builder.geometric(context, actor, .66)
                expected[name]["pot50"] = builder.pot_size(context, actor, .5)
            rows.append("\t".join([name, ",".join(map(str, stacks)), ",".join(map(str, h["blinds"])),
                str(["REGULAR", "BB_ANTE_ANTE_FIRST", "BB_ANTE_BLIND_FIRST"].index(h["anteType"])),
                str(["OFF", "SINGLE", "DOUBLE", "BUTTON"].index(h["straddleType"])), str(h["skipSb"]).lower(), str(s.street),
                ",".join(f"{a.street}:{a.kind}:{a.amount}" for a in context.history) or "-"]))
            normalized = builder.normalize(context)
            if normalized != context:
                context = normalized
                continue
            children = builder.children(context)
            if not children: break
            # Bias toward calls/bets so the audit includes actual later streets.
            context = rng.choice(children[1:] if len(children) > 1 and rng.random() < .8 else children)
    out = ROOT / "analysis/hrc-deep/probes"
    inputs = out / "tree-builder-inputs.tsv"
    inputs.write_text("\n".join(rows)+"\n", encoding="utf-8")
    classes = ROOT / "analysis/hrc-deep/java-tools"
    source = ROOT / "scripts/java/OriginalTreeBuilderProbe.java"
    subprocess.run([str(JAVA.with_name("javac.exe")), "-cp", str(classes), "-d", str(classes), str(source)], check=True, capture_output=True)
    command = [str(JAVA), "-cp", str(classes), "OriginalTreeBuilderProbe", str(JAR), str(inputs)]
    process = subprocess.run(command, capture_output=True, text=True)
    (out / "tree-builder-original-output.jsonl").write_text(process.stdout, encoding="utf-8")
    (out / "tree-builder-original-stderr.txt").write_text(process.stderr, encoding="utf-8")
    if process.returncode:
        print(process.stderr[-4000:]); raise SystemExit(process.returncode)
    records = [json.loads(line) for line in process.stdout.splitlines()]
    results = []
    for record in records:
        if record["kind"] != "builder_case": continue
        independent = expected[record["id"]]
        mismatches = {k: {"original": record["actual"].get(k), "independent": v}
                      for k, v in independent.items() if record["actual"].get(k) != v}
        results.append({**record, "independent": independent, "mismatches": mismatches, "passed": not mismatches})
    full = []
    for name, n, stack, pushfold, pko in [
        ("hu10bb-pushfold-10m", 2, 100000, True, False),
        ("eight15bb-raise-call-postflop-60m", 8, 150000, False, False),
        ("nine10bb-raise-call-postflop-initial", 9, 100000, False, False),
        ("nine20bb-raise-call-postflop-60m", 9, 200000, False, False),
        ("eight15bb-pko-50-30-20-initial", 8, 150000, False, True),
    ]:
        path = ROOT / "analysis/hrc-desktop" / f"{name}.hrcz"
        if not path.exists(): continue
        settings = default_settings(n, stack)
        if pushfold:
            settings["treeconfig"]["preflop"]["settings"]["PREFLOP_SIZES"][0] = "all-in"
            settings["treeconfig"]["preflop"]["settings"]["ALLOWED_FLATS_PER_RAISE"][1] = 0
        if pko:
            settings["eqmodel"] = {"id": "icm", "structure": {"bountyType": "PKO", "progressiveFactor": .5, "prizes": {"1": 50, "2": 30, "3": 20}}}
            settings["handdata"]["bounties"] = [10.0]*n
        generated = build_tree(settings)
        with ZipFile(path) as archive: data = archive.read("gametree.dat")
        nodes, root = parse_gametree(data)
        states, _ = replay_tree(nodes, root, generated.rules)
        fields = ["remaining", "contributions", "folded", "street", "current_bet", "next_actor"]
        state_errors = {field: sum(getattr(a, field) != getattr(b, field) for a,b in zip(generated.states, states)) for field in fields}
        full.append({"archive": str(path), "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "nodes": len(nodes), "generated_nodes": len(generated.nodes), "exact_nodes_and_actions": generated.nodes == nodes,
                     "state_mismatches": state_errors, "generation_seconds": generated.validation["seconds"],
                     "passed": generated.nodes == nodes and not any(state_errors.values())})
    report = {"jar_sha256": hashlib.sha256(JAR.read_bytes()).hexdigest(), "command": command,
              "scope": "Original pure lB/lC/mG contexts over synthetic action paths, including antes/straddles/short stacks. Whole-tree comparisons generate from explicit parameters before loading only original gametree for comparison; no saved strategies or leaf utilities are read.",
              "case_count": len(results), "configuration_count": len(configs), "original_bytecode_passed": all(r["passed"] for r in results),
              "whole_trees": full, "passed": all(r["passed"] for r in results+full), "cases": results,
              "class_hashes": [r for r in records if r["kind"] == "class"],
              "builder_sha256": hashlib.sha256((ROOT / "preflop_lab/hrc_tree_builder.py").read_bytes()).hexdigest()}
    path = ROOT / "reports/hrc-original-tree-builder-validation.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["case_count", "configuration_count", "original_bytecode_passed", "whole_trees", "passed"]}, indent=2))
    if not report["passed"]:
        print(json.dumps([{"id": r["id"], "mismatches": r["mismatches"]} for r in results if not r["passed"]][:10], indent=2))
        raise SystemExit(1)


if __name__ == "__main__": run()
