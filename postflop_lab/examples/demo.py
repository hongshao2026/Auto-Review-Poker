"""Run ChipEV and ICM on the same spot and query the saved solutions."""

import argparse
import json
from pathlib import Path

from postflop_lab import Solver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    river = json.loads(Path(__file__).with_name("river.json").read_text(encoding="utf-8"))
    solver = Solver()
    tournament = {"payouts": [500, 300, 200], "stacks": [20, 32, 45, 12, 8, 15], "seats": [0, 1]}
    for model, config in (("chips", river), ("icm", {**river, "tournament": tournament})):
        output = args.output / f"river-{model}.json"
        solver.solve(config, output, threads=4, report_every=50)
        node = solver.query(output, "bet:10", ev=True)
        print(json.dumps({"model": model, "node": node["id"], "actions": node["actions"],
                          "hand": node["hands"][0], "meta": node["meta"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
