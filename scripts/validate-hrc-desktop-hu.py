"""Independent 169-class HU 10bb push/fold minimax benchmark.

No HRC solver/class is executed. Chance probabilities are read from the user's
installed 2wh.dat resource; blockers are independently enumerated and verified.
The resulting LPs, best responses, utilities and comparisons are our own code.
The resource is not copied to the output or bundled in an application.

Run: .venv/Scripts/python.exe scripts/validate-hrc-desktop-hu.py
Optional: --compare path/to/*-decoded.json (repeatable).
Dependency: numpy, scipy (HiGHS linear programming via scipy.optimize.linprog).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import platform
import time
import zipfile

import numpy as np
import scipy
from scipy.optimize import linprog

ROOT = Path(__file__).resolve().parents[1]
RANKS = "23456789TJQKA"
RESOURCE = "net/holdemresources/handevaluation/preflop/hands/data/2wh.dat"
DEFAULT_JAR = Path(r"D:\Program Files\HRC\plugins\net.holdemresources.preflopdata.holdem_1.4.1.jar")


def labels():
    return [RANKS[r] * 2 if r == c else RANKS[max(r, c)] + RANKS[min(r, c)] + ("s" if r > c else "o")
            for r in range(13) for c in range(13)]


def chance_data(path):
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(RESOURCE)
    compact = np.frombuffer(raw, dtype="<f8").reshape(-1, 3)
    assert compact.shape == (14365, 3)
    assert np.isfinite(compact).all() and (compact >= 0).all()
    # Columns in the installed table: tie, first player wins, second wins.
    mass = np.zeros((169, 169, 3))
    k = 0
    for i in range(169):
        for j in range(i + 1):
            mass[i, j] = compact[k]
            mass[j, i] = compact[k, [0, 2, 1]]
            k += 1
    joint = mass.sum(axis=2)
    showdown = mass[:, :, 1] - mass[:, :, 2]
    combos = [[] for _ in range(169)]
    for hi in range(52):
        for lo in range(hi):
            rh, rl = hi // 4, lo // 4
            h = rh * 14 if rh == rl else rh * 13 + rl if hi % 4 == lo % 4 else rl * 13 + rh
            combos[h].append((1 << hi) | (1 << lo))
    counts = np.array([[sum(not (a & b) for a in ac for b in bc) for bc in combos] for ac in combos])
    oracle = counts / (1326 * 1225)
    combo_counts = np.array([len(c) for c in combos])
    errors = {
        "all_28561_joint_pairs_max_abs_error": float(np.max(np.abs(joint - oracle))),
        "total_joint_probability_error": float(abs(joint.sum() - 1)),
        "marginal_combo_frequency_max_abs_error": float(np.max(np.abs(joint.sum(axis=1) - combo_counts / 1326))),
        "showdown_antisymmetry_max_abs_error": float(np.max(np.abs(showdown + showdown.T))),
    }
    assert max(errors.values()) < 1e-12, errors
    # Independent rank-label sanity, not a full equity-table regeneration.
    aa, twos = 168, 0
    aa_equity_vs_22 = float((mass[aa, twos, 1] + .5 * mass[aa, twos, 0]) / joint[aa, twos])
    assert .75 < aa_equity_vs_22 < .90, aa_equity_vs_22
    provenance = {"jar": str(path.resolve()), "jar_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "member": RESOURCE, "resource_sha256": hashlib.sha256(raw).hexdigest(),
                  "bytes": len(raw), "errors": errors, "AA_equity_vs_22": aa_equity_vs_22,
                  "limitation": "Joint frequencies independently verified; all showdown probabilities were not independently enumerated over all boards."}
    return joint, showdown, combo_counts, provenance


def solve_box_game(a, matrix, constant=0.0):
    """max 0<=x<=1 min 0<=y<=1 constant+a*x+x'My, using two separate LPs."""
    n, m = matrix.shape
    options = {"primal_feasibility_tolerance": 1e-10, "dual_feasibility_tolerance": 1e-10}
    # max a'x + sum_j t_j, t_j <= 0, t_j <= (M'x)_j.
    primal = linprog(np.r_[-a, -np.ones(m)], A_ub=np.c_[-matrix.T, np.eye(m)], b_ub=np.zeros(m),
                     bounds=[(0, 1)] * n + [(None, 0)] * m, method="highs-ds", options=options)
    # min sum_i s_i, s_i >= 0, s_i >= a_i+(My)_i.
    dual = linprog(np.r_[np.zeros(m), np.ones(n)], A_ub=np.c_[matrix, -np.eye(n)], b_ub=-a,
                   bounds=[(0, 1)] * m + [(0, None)] * n, method="highs-ds", options=options)
    assert primal.success and dual.success, (primal.message, dual.message)
    x, y = primal.x[:n], dual.x[:m]
    lower, upper = constant - primal.fun, constant + dual.fun
    br = profile(a, matrix, x, y, constant)
    assert abs(upper - lower) < 1e-9 and br["nashconv_bb_per_deal"] < 1e-9, (lower, upper, br)
    return x, y, {"method": "two independent HiGHS dual-simplex LPs",
                  "primal_iterations": primal.nit, "dual_iterations": dual.nit,
                  "lower_bound_bb_per_deal": lower, "upper_bound_bb_per_deal": upper,
                  "primal_dual_gap": upper - lower, "feasibility_tolerance": 1e-10, **br}


def profile(a, matrix, x, y, constant=-.5):
    utility = float(constant + a @ x + x @ matrix @ y)
    sb_br = float(constant + np.maximum(0, a + matrix @ y).sum())
    bb_br = float(constant + a @ x + np.minimum(0, matrix.T @ x).sum())
    return {"sb_ev_bb_per_deal": utility, "bb_ev_bb_per_deal": -utility,
            "sb_best_response_ev_bb_per_deal": sb_br,
            "sb_ev_against_bb_best_response_bb_per_deal": bb_br,
            "sb_unilateral_improvement_bb_per_deal": sb_br - utility,
            "bb_unilateral_improvement_bb_per_deal": utility - bb_br,
            "nashconv_bb_per_deal": sb_br - bb_br,
            "half_nashconv_bb_per_deal": (sb_br - bb_br) / 2,
            "gap_definition": "sum of the two unilateral improvements, ex ante over full joint private-card distribution"}


def self_checks(joint, showdown, a, matrix):
    rng = np.random.default_rng(20261104)
    # Brute-force pure best responses in a separate tiny game validate the LP/BR algebra.
    small_a = np.array([.7, -.4, .2])
    small_m = np.array([[-1.3, .2], [.4, -.7], [-.6, .8]])
    x, y, result = solve_box_game(small_a, small_m, -.13)
    pure_x = [np.array(v) for v in itertools.product([0., 1.], repeat=3)]
    pure_y = [np.array(v) for v in itertools.product([0., 1.], repeat=2)]
    max_x = max(-.13 + small_a @ p + p @ small_m @ y for p in pure_x)
    min_y = min(-.13 + small_a @ x + x @ small_m @ p for p in pure_y)
    assert abs(max_x - min_y) < 1e-10
    # Independent direct terminal sum vs bilinear reduction on random strategies.
    terminal_errors = []
    for _ in range(12):
        x, y = rng.random(169), rng.random(169)
        direct = np.sum(-.5 * joint * (1 - x[:, None])
                        + joint * x[:, None] * (1 - y[None, :])
                        + 10 * showdown * x[:, None] * y[None, :])
        algebra = -.5 + a @ x + x @ matrix @ y
        terminal_errors.append(float(abs(direct - algebra)))
    assert max(terminal_errors) < 1e-12
    endpoint_values = {"SB_always_fold": float(-.5),
                       "SB_always_shove_BB_always_fold": float(-.5 + a.sum()),
                       "both_always_allin": float(-.5 + a.sum() + matrix.sum())}
    assert abs(endpoint_values["SB_always_shove_BB_always_fold"] - 1) < 1e-12
    assert abs(endpoint_values["both_always_allin"]) < 1e-12
    return {"tiny_game_exhaustive_br_gap": float(max_x - min_y),
            "random_profile_terminal_sum_checks": 12, "terminal_sum_max_abs_error": max(terminal_errors),
            "endpoint_net_SB_values_bb": endpoint_values}


def metrics(joint, a, matrix, x, y):
    marginal = joint.sum(axis=1)
    bb_reach = joint.T @ x
    return {**profile(a, matrix, x, y), "sb_shove_unconditional": float(marginal @ x),
            "bb_call_uniform_marginal": float(marginal @ y),
            "bb_call_conditional_on_shove": float(bb_reach @ y / bb_reach.sum()),
            "allin_called_unconditional": float(bb_reach @ y)}


def delta_ev(joint, a, matrix, x, y):
    sb_delta = (a + matrix @ y) / joint.sum(axis=1)
    reach = joint.T @ x
    bb_delta = -(matrix.T @ x) / reach
    return sb_delta, bb_delta


def compare_saved(path, joint, a, matrix, xstar, ystar, hands):
    raw = path.read_bytes()
    saved = json.loads(raw)
    settings = saved["settings"]
    hd = settings["handdata"]
    assert hd["stacks"] == [100000, 100000] and hd["blinds"] == [10000, 5000, 0]
    assert settings["eqmodel"]["id"] == "chipev" and not settings["eqmodel"]["raked"]
    nodes = saved["nodes"]
    assert set(nodes) == {"root", "root/0", "root/1", "root/1/0", "root/1/1"}
    assert nodes["root/0"]["data"]["leaf_vectors"] == [[950.0, 1050.0]]
    assert nodes["root/1/0"]["data"]["leaf_vectors"] == [[1100.0, 900.0]]
    assert nodes["root/1/1"]["data"]["leaf_vectors"] == [[2000.0, 0.0], [1000.0, 1000.0], [0.0, 2000.0]]
    rows = [nodes[p]["data"]["buckets"] for p in ["root", "root/1"]]
    for rowset in rows:
        assert [r["bucket"] for r in rowset] == list(range(169))
        assert [r["hand"] for r in rowset] == hands
        assert all(r["has_positive_average_weight"] and not r["locked_probabilities"] for r in rowset)
    x, y = (np.array([r["display_strategy"][1] for r in rs]) for rs in rows)
    assert np.all((x >= 0) & (x <= 1)) and np.all((y >= 0) & (y <= 1))
    sb_ev, bb_ev = delta_ev(joint, a, matrix, x, y)
    marginal = joint.sum(axis=1)
    reach = joint.T @ x
    result = {"decoded_path": str(path.resolve()), "decoded_sha256": hashlib.sha256(raw).hexdigest(),
              "archive_sha256": saved["profile"]["archive_sha256"],
              "per_node_saved_float32_update_counters": {p: nodes[p]["data"]["saved_counter_float32"] for p in ["root", "root/1"]},
              "profile": metrics(joint, a, matrix, x, y),
              "comparison_scope": "Decoded historical average strategies evaluated in the independently solved table-based game.",
              "ev_caveat": "Saved (R1-R0)/D is a history-weighted sampled action-value difference, not the exact value against the final average opponent. EV differences are descriptive, not exact-equality tests.",
              "players": {}}
    for who, actual, target, rowset, calculated, weights in [
        ("SB", x, xstar, rows[0], sb_ev, marginal),
        ("BB", y, ystar, rows[1], bb_ev, reach / reach.sum())]:
        err = np.abs(actual - target)
        historical = np.array([r["relative_ev_to_action0"][1] / 100 for r in rowset])
        ev_err = np.abs(historical - calculated)
        result["players"][who] = {"frequency_weighted_mae": float(weights @ err),
            "frequency_max_abs_error": float(err.max()), "frequency_rmse_unweighted": float(np.sqrt(np.mean(err ** 2))),
            "historical_vs_current_opponent_delta_ev_weighted_mae_bb": float(weights @ ev_err),
            "historical_vs_current_opponent_delta_ev_max_abs_error_bb": float(ev_err.max()),
            "largest_frequency_differences": [{"hand": hands[i], "original": actual[i], "independent": target[i],
                "abs_difference": err[i], "original_historical_delta_ev_bb": historical[i],
                "delta_ev_against_original_current_opponent_bb": calculated[i]} for i in np.argsort(-err)[:15]],
            "hands": [{"bucket": i, "hand": hands[i], "original": actual[i], "independent": target[i],
                       "original_historical_delta_ev_bb": historical[i], "current_opponent_delta_ev_bb": calculated[i]} for i in range(169)]}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-jar", type=Path, default=DEFAULT_JAR)
    parser.add_argument("--compare", type=Path, action="append")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "analysis/hrc-desktop")
    args = parser.parse_args()
    started = time.perf_counter()
    joint, showdown, combos, provenance = chance_data(args.table_jar)
    marginal = joint.sum(axis=1)
    # Net initial-stack SB payoffs: fold -.5, shove/fold +1,
    # shove/call 10*(P(win)-P(loss)); tie pays zero net.
    a = 1.5 * marginal
    matrix = 10 * showdown - joint
    checks = self_checks(joint, showdown, a, matrix)
    x, y, solve = solve_box_game(a, matrix, -.5)
    sb_delta, bb_delta = delta_ev(joint, a, matrix, x, y)
    hands = labels()
    comparisons = args.compare if args.compare is not None else sorted(args.output_dir.glob("hu10bb-pushfold-*-decoded.json"))
    result = {"schema": "independent-hu-pushfold-v1", "status": "solved_and_best_response_checked",
              "source_path": str(Path(__file__).resolve()),
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "implementation": "Independent Python payoff construction, two LPs, exact finite-model best responses; no HRC solver executed.",
              "game": {"players": 2, "stacks_bb_including_posts": [10, 10], "small_blind_bb": .5, "big_blind_bb": 1,
                       "ante_bb": 0, "SB_actions": ["fold", "shove_to_10"], "BB_actions_after_shove": ["fold", "call_to_10"],
                       "utility": "net chipEV in bb relative to initial stacks", "postflop": "all-in runout only", "private_abstraction": "169 suit-symmetric hand classes"},
              "model_formula": "U_SB(x,y)=-0.5+1.5*p'x+x'(10*(joint_win-joint_loss)-joint)y",
              "lp_description": "SB: maximize a'x+sum(t), t<=0,t<=M'x. BB: minimize sum(s),s>=0,s>=a+My. x,y in [0,1].",
              "chance_provenance": provenance, "self_checks": checks, "lp": solve,
              "equilibrium": metrics(joint, a, matrix, x, y),
              "mixed_SB": [{"hand": hands[i], "shove": x[i]} for i in range(169) if 1e-8 < x[i] < 1-1e-8],
              "mixed_BB": [{"hand": hands[i], "call": y[i]} for i in range(169) if 1e-8 < y[i] < 1-1e-8],
              "hands": [{"bucket": i, "hand": hands[i], "combos": int(combos[i]), "sb_shove": x[i], "bb_call": y[i],
                         "sb_shove_minus_fold_bb": sb_delta[i], "bb_call_minus_fold_given_shove_bb": bb_delta[i]} for i in range(169)],
              "comparisons": [compare_saved(p, joint, a, matrix, x, y, hands) for p in comparisons],
              "dependencies": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "method_reference": "https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs-ds.html",
              "limitations": ["The showdown chance table is read from the installed HRC resource; this is an independent optimizer, not an independently regenerated equity table.",
                              "The reported gap is for this finite HU push/fold game only; it is not a complete HRC exploitability claim.",
                              "LP solution frequencies can differ at nearly indifferent hands; best-response gap is the decision-quality comparison.",
                              "No claim that all other HRC configurations, multiway games, ICM or postflop solving are reproduced."]}
    result["elapsed_seconds"] = time.perf_counter() - started
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / "hu-independent-validation.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    np.savez_compressed(args.output_dir / "hu-independent-solution.npz", hand_labels=np.array(hands), sb_shove=x, bb_call=y,
                        combos=combos, sb_shove_minus_fold_bb=sb_delta, bb_call_minus_fold_given_shove_bb=bb_delta)
    print(json.dumps({"report": str(out), "equilibrium": result["equilibrium"], "lp_gap": solve["primal_dual_gap"],
                      "comparisons": [{"file": r["decoded_path"], "profile": r["profile"]} for r in result["comparisons"]],
                      "elapsed_seconds": result["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
