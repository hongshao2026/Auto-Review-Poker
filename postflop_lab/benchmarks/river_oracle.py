"""Independently evaluate the benchmark's two-hand river profiles."""

import argparse
import json
from pathlib import Path

from .compare import hand_key, icm_utility


def profile(mode, snapshot):
    oop, ip = snapshot["policy"]
    bet = oop["actions"].index("allin" if mode == "local" else "b100")
    call = ip["actions"].index("call" if mode == "local" else "c")
    return [oop["frequencies"][hand_key(hand)][bet] for hand in ("QcQd", "Ac4c")], ip["frequencies"][hand_key("TcTd")][call]


def evaluate(bets, call, utility):
    bust, behind, won_pot, won_shove = [utility(stack) for stack in (0, 100, 200, 300)]
    oop_check = (won_pot, behind)
    oop_bet = tuple((1 - call) * won_pot + call * outcome for outcome in (won_shove, bust))
    ev_oop = sum((1 - p) * x + p * y for p, x, y in zip(bets, oop_check, oop_bet)) / 2
    br_oop = sum(max(x, y) for x, y in zip(oop_check, oop_bet)) / 2
    ip_checked = sum((1 - p) * value for p, value in zip(bets, (behind, won_pot))) / 2
    ip_fold = sum(bets) * behind / 2
    ip_call = sum(p * value for p, value in zip(bets, (bust, won_shove))) / 2
    ev_ip = ip_checked + (1 - call) * ip_fold + call * ip_call
    br_ip = ip_checked + max(ip_fold, ip_call)
    return [ev_oop, ev_ip], (br_oop - ev_oop + br_ip - ev_ip) / 2


def assess(report):
    results = {}
    for case_name in ("river", "river_icm"):
        if case_name not in report["cases"]:
            continue
        is_icm = case_name == "river_icm"
        utility = icm_utility if is_icm else lambda stack: stack - 100
        expected_bets = [1, 23/28 if is_icm else 0.5]
        expected_call = 15/38 if is_icm else 0.5
        expected_evs, error = evaluate(expected_bets, expected_call, utility)
        assert abs(error) < 1e-12
        case = results[case_name] = {"exact": {"bets": expected_bets, "call": expected_call, "ev": expected_evs}}
        for mode, run in report["cases"][case_name]["modes"].items():
            last = run["sweep"][-1]
            bets, call = profile(mode, last)
            evs, exploit = evaluate(bets, call, utility)
            engine_evs = last["pot_ev"]
            if is_icm and mode != "local":
                engine_evs = [x + utility(100) for x in engine_evs]
            case[mode] = {"iteration": last["iteration"], "bets": bets, "call": call, "oracle_ev": evs,
                          "engine_ev": engine_evs, "oracle_pct_pot": exploit, "engine_pct_pot": last["pct_pot"],
                          "ev_error_vs_equilibrium": [a - b for a, b in zip(evs, expected_evs)],
                          "ev_engine_minus_oracle": [a - b for a, b in zip(engine_evs, evs)]}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = assess(json.loads(args.report.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
