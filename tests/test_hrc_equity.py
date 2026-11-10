"""Independent terminal ICM/KO/PKO tests, including retained original bytes."""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def build_probe():
    source = ROOT / "scripts/native/equity_probe.cpp"
    header = ROOT / "native/hrc_equity.hpp"
    digest = hashlib.sha256(source.read_bytes() + header.read_bytes()).hexdigest()
    directory = ROOT / "analysis/hrc-native/equity-build"
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "equity_probe.exe"
    stamp = directory / "build.sha256"
    if not executable.exists() or not stamp.exists() or stamp.read_text() != digest:
        zig = Path(r"D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe")
        subprocess.run([str(zig), "c++", "-O3", "-std=c++17", "-ffp-contract=off", str(source), "-o", str(executable)],
                       check=True, capture_output=True, text=True)
        stamp.write_text(digest)
    return executable


@pytest.fixture(scope="module")
def probe():
    return build_probe()


def csv(values):
    return ",".join(map(str, values)) or "-"


def terminal_line(case, opcode="terminal"):
    return "\t".join(map(str, [case["id"], opcode, case.get("mode", 1), case.get("bounty_mode", 0),
                              csv(case["initial"]), csv(case["final"]), csv(case.get("payouts", [])),
                              csv(case.get("bounties", [])), case.get("alpha", 1),
                              csv(case.get("masks", [0] * len(case["initial"]))),
                              csv(case.get("other_stacks", [])), csv(case.get("other_bounties", [])),
                              case.get("chip_unit", 1), case.get("cache_capacity", 17)]))


def run_lines(probe, lines):
    process = subprocess.run([str(probe)], input="\n".join(lines) + "\n", text=True, capture_output=True, check=True)
    result = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(result) == len(lines)
    return result


def permutation_icm(stacks, payouts):
    """Enumerate complete finish orders, independent of subset dynamic programming."""
    result = [0.0] * len(stacks)
    for order in itertools.permutations(range(len(stacks))):
        probability, remaining = 1.0, sum(stacks)
        for i in order:
            probability *= stacks[i] / remaining
            remaining -= stacks[i]
        for place, i in enumerate(order[:len(payouts)]):
            result[i] += probability * payouts[place]
    return result


def oracle(case):
    initial, final = case["initial"], case["final"]
    n = len(initial)
    payouts = case.get("payouts", [])
    bounties = case.get("bounties", [0.0] * n)
    mode = case.get("bounty_mode", 0)
    alpha = case.get("alpha", 1) if mode == 2 else 1
    live = [i for i in range(n) if final[i]]
    dead = [i for i in range(n) if not final[i]]
    outside = case.get("other_stacks", [])
    paid = [0.0] * n
    instant = [0.0] * n
    heads = [bounties[i] if final[i] else 0.0 for i in range(n)]
    for i in dead:
        higher = sum(initial[j] > initial[i] for j in dead)
        tied = sum(initial[j] == initial[i] for j in dead)
        first = len(live) + len(outside) + higher
        paid[i] = sum(payouts[first:first+tied]) / tied
        if mode:
            killers = [j for j in live if case["masks"][i] & (1 << j)]
            for j in killers:
                instant[j] += bounties[i] * alpha / len(killers)
                if mode == 2:
                    heads[j] += bounties[i] * (1-alpha) / len(killers)
    all_stacks = [final[i] for i in live] + outside
    future = [0.0] * n
    prize = permutation_icm(all_stacks, payouts)
    pool = sum(heads)
    if mode == 1:
        pool += len(outside) * bounties[0]
    elif mode == 2:
        pool += sum(case.get("other_bounties", []))
    for j, i in enumerate(live):
        future[i] = prize[j] + pool * final[i] / sum(all_stacks)
    return {"total": [paid[i] + instant[i] + future[i] for i in range(n)],
            "immediate_prizes": paid, "immediate_bounties": instant,
            "remaining_bounties": heads, "future_equities": future}


def fixtures():
    return [
        {"id": "simultaneous_unequal", "initial": [100, 200, 300, 400], "final": [0, 0, 0, 1000], "payouts": [50, 30, 15, 5]},
        {"id": "simultaneous_equal", "initial": [100, 100, 300, 500], "final": [0, 0, 0, 1000], "payouts": [50, 30, 20]},
        {"id": "split_bounty", "initial": [100, 200, 300], "final": [0, 250, 350], "payouts": [70, 30],
         "bounty_mode": 1, "bounties": [12, 12, 12], "masks": [6, 0, 0]},
        {"id": "split_progressive", "initial": [100, 200, 300], "final": [0, 250, 350], "payouts": [70, 30],
         "bounty_mode": 2, "bounties": [20, 40, 80], "alpha": .3, "masks": [6, 0, 0]},
        {"id": "different_sidepot_killers", "initial": [100, 200, 400, 400], "final": [0, 0, 600, 500], "payouts": [70, 20, 10],
         "bounty_mode": 2, "bounties": [10, 70, 30, 40], "alpha": .5, "masks": [8, 4, 0, 0]},
        {"id": "last_survivor_own_head", "initial": [100, 100], "final": [200, 0], "payouts": [70, 30],
         "bounty_mode": 2, "bounties": [10, 90], "alpha": .5, "masks": [0, 1]},
        {"id": "all_rollover", "initial": [100, 100, 100], "final": [0, 150, 150], "payouts": [],
         "bounty_mode": 2, "bounties": [10, 40, 80], "alpha": 0, "masks": [6, 0, 0]},
        {"id": "all_cash", "initial": [100, 100, 100], "final": [0, 150, 150], "payouts": [],
         "bounty_mode": 2, "bounties": [10, 40, 80], "alpha": 1, "masks": [6, 0, 0]},
        {"id": "mtt_prize_rank_offset", "mode": 2, "initial": [100, 100, 100], "final": [0, 0, 300],
         "payouts": [50, 25, 15, 10], "other_stacks": [100, 200]},
        {"id": "mtt_progressive_pool", "mode": 2, "initial": [100, 200, 300], "final": [0, 300, 300],
         "payouts": [50, 25, 15, 10], "other_stacks": [200, 100], "other_bounties": [70, 100],
         "bounty_mode": 2, "bounties": [10, 40, 80], "alpha": .25, "masks": [2, 0, 0]},
    ]


def test_all_retained_original_icm_cases(probe):
    report = json.loads((ROOT / "reports/hrc-original-icm-validation.json").read_text())
    lines = ["\t".join([case["id"], "icm", csv(case["stacks"]), csv(case["prizes"])]) for case in report["cases"]]
    for case, result in zip(report["cases"], run_lines(probe, lines)):
        assert result["total"] == pytest.approx(case["values"], rel=1e-13, abs=1e-10)


@pytest.mark.parametrize("case", fixtures(), ids=lambda c: c["id"])
def test_elimination_and_bounties_against_finish_order_oracle(probe, case):
    result = run_lines(probe, [terminal_line(case)])[0]
    for field, expected in oracle(case).items():
        assert result[field] == pytest.approx(expected, rel=1e-12, abs=1e-10)
    assert result["cache_hits"] == 1
    if case.get("mode") != 2:
        assert sum(result["total"]) == pytest.approx(sum(case["payouts"][:len(case["initial"])]) + sum(case.get("bounties", [])))


def test_random_simultaneous_eliminations_and_seat_permutations(probe):
    rng = random.Random(20261105)
    cases = []
    for n in range(2, 8):
        for variant in range(12):
            initial = [rng.choice([100, 200, 400]) for _ in range(n)]
            live = sorted(rng.sample(range(n), rng.randint(1, n)))
            final, masks = [0]*n, [0]*n
            for i in live:
                final[i] = initial[i]
            for i in set(range(n))-set(live):
                killers = rng.sample(live, min(len(live), rng.randint(1, 2)))
                masks[i] = sum(1 << j for j in killers)
                for j in killers:
                    final[j] += initial[i] // len(killers)
            mode = variant % 3
            case = {"id": f"random_{n}_{variant}", "initial": initial, "final": final, "masks": masks,
                    "payouts": sorted([rng.randint(0, 100) for _ in range(rng.randint(1, n))], reverse=True), "bounty_mode": mode}
            if mode:
                case["bounties"] = [30]*n if mode == 1 else [rng.randint(0, 100) for _ in range(n)]
                case["alpha"] = 1 if mode == 1 else rng.choice([0, .25, .5, 1])
            cases.append(case)
    results = run_lines(probe, [terminal_line(c) for c in cases])
    for case, result in zip(cases, results):
        expected = oracle(case)
        assert result["total"] == pytest.approx(expected["total"], abs=1e-9)
        assert sum(result["total"]) == pytest.approx(sum(case["payouts"]) + sum(case.get("bounties", [])), abs=1e-9)


def test_cache_collision_preserves_correct_values(probe):
    case = {**fixtures()[3], "cache_capacity": 1}
    result = run_lines(probe, [terminal_line(case, "cache")])[0]
    assert result["total"] == pytest.approx(oracle(case)["total"])
    assert (result["cache_hits"], result["cache_misses"], result["cache_collisions"]) == (1, 3, 2)


def test_cache_key_distinguishes_same_chips_with_different_killers(probe):
    case = fixtures()[3]
    result = run_lines(probe, [terminal_line(case, "maskcache")])[0]
    assert result["total"] == pytest.approx(oracle(case)["total"])
    assert result["alternate_total"] == pytest.approx(oracle({**case, "masks": [2, 0, 0]})["total"])
    assert result["alternate_total"] != result["total"]


def test_equity_is_invariant_under_seat_permutations(probe):
    case = fixtures()[4]
    expected = oracle(case)["total"]
    cases = []
    for permutation in itertools.permutations(range(4)):
        old_to_new = {old: new for new, old in enumerate(permutation)}
        masks = [sum(1 << old_to_new[j] for j in range(4) if case["masks"][i] & (1 << j)) for i in permutation]
        cases.append({**case, "id": str(permutation), "initial": [case["initial"][i] for i in permutation],
                      "final": [case["final"][i] for i in permutation], "bounties": [case["bounties"][i] for i in permutation],
                      "masks": masks, "expected": [expected[i] for i in permutation]})
    for case, result in zip(cases, run_lines(probe, [terminal_line(c) for c in cases])):
        assert result["total"] == pytest.approx(case["expected"], abs=1e-10)


@pytest.mark.parametrize('opcode', ['unusedstacks', 'unusedmasks'])
@pytest.mark.parametrize('capacity', [0, 1, 17])
def test_cache_hit_does_not_hide_invalid_unused_seats(probe, opcode, capacity):
    case = {'id': opcode, 'initial': [100, 100], 'final': [150, 50],
            'payouts': [70, 30], 'cache_capacity': capacity}
    result = run_lines(probe, [terminal_line(case, opcode)])[0]
    assert result['error'] == 'Unused seats must be zero'


def test_cache_disabled_and_chip_units(probe):
    case = {"id": "chips", "mode": 0, "initial": [100, 100], "final": [150, 50], "cache_capacity": 0, "chip_unit": .01}
    result = run_lines(probe, [terminal_line(case)])[0]
    assert result["total"] == [1.5, .5]
    assert result["baseline"] == [1, 1]
    assert (result["cache_hits"], result["cache_misses"]) == (0, 2)


@pytest.mark.parametrize("change", [
    {"initial": [0, 100]}, {"initial": [-1, 100]}, {"final": [-1, 201]}, {"final": [0, 0]},
    {"payouts": [10, 20]}, {"payouts": [float("nan")]}, {"payouts": [float("inf")]},
    {"bounty_mode": 1, "bounties": [10, 20]}, {"bounty_mode": 1, "bounties": [10, 10], "alpha": .5},
    {"bounty_mode": 2, "bounties": [10, float("inf")]}, {"alpha": -1}, {"alpha": 1.1}, {"alpha": float("nan")},
    {"masks": [0, 2]}, {"masks": [0, 4]}, {"masks": [2, 1]},
    {"bounty_mode": 2, "bounties": [10, 20], "masks": [0, 0]},
    {"mode": 0, "bounty_mode": 1, "bounties": [10, 10]}, {"other_stacks": [100]},
    {"mode": 2, "other_stacks": [0]}, {"chip_unit": 0}, {"chip_unit": float("inf")},
    {"mode": 7}, {"bounty_mode": 7}, {"cache_capacity": 2**20+1},
])
def test_invalid_domain_fails_explicitly(probe, change):
    case = {"id": "invalid", "initial": [100, 100], "final": [200, 0], "masks": [0, 1], "payouts": [70, 30], **change}
    assert "error" in run_lines(probe, [terminal_line(case)])[0]


def test_extreme_positive_stacks_do_not_overflow_icm(probe):
    rows = run_lines(probe, ["scale\ticm\t1e308,1e308,1e-300\t70,20,10"])
    assert rows[0]["total"] == pytest.approx([45, 45, 10])


def test_original_bounty_probe_results_when_present(probe):
    path = ROOT / "reports/hrc-original-bounty-validation.json"
    if not path.exists():
        pytest.skip("Original bounty-bytecode validation has not run yet")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["passed"]
    results = run_lines(probe, [terminal_line(case["input"]) for case in report["cases"]])
    for case, result in zip(report["cases"], results):
        assert result["total"] == pytest.approx(case["original"]["total"], rel=1e-12, abs=1e-9)
        assert result["immediate_bounties"] == pytest.approx(case["original"]["immediate_bounties"], rel=1e-12, abs=1e-10)
        assert result["remaining_bounties"] == pytest.approx(case["original"]["remaining_bounties"], rel=1e-12, abs=1e-10)
