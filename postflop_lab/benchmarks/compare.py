"""Measure the local engine and an official Pio UPI engine on common trees."""

import argparse
import hashlib
import json
from itertools import permutations
from pathlib import Path
import queue
import re
from statistics import median
import subprocess
from threading import Thread
from time import perf_counter

from postflop_lab.client import _PIO_HANDS, import_pio


RIVER_STEPS = [16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384]
BOARD = "Qs Jh 2h 8c 3d"
TARGETS = [0.1, 0.01]
END = "BENCH_END"


def hand_key(hand):
    return "".join(sorted((hand[:2], hand[2:])))


def range_weights(text):
    weights = {}
    for term in text.split(","):
        cards, sep, value = term.partition(":")
        weight = float(value) if sep else 1.0
        if len(cards) == 4:
            weights[hand_key(cards)] = weight
            continue
        ranks, suitedness = sorted(cards[:2]), cards[2:]
        for combo in _PIO_HANDS:
            suited = combo[1] == combo[3]
            if sorted(combo[::2]) == ranks and (not suitedness or suited == (suitedness == "s")):
                weights[hand_key(combo)] = weight
    return weights


def cases():
    oop = "22,33,44,55,66,77,88,99,TT,JJ,AQo,AJo,AQs,AJs,ATs,A9s,A8s,A7s,A6s,A5s,A4s,A3s,A2s,KQo,KQs,KJs,KTs,QJs,QTs,JTs,T9s,98s,87s,76s"
    ip = "AA,KK,QQ,JJ,TT,99,88,77,66,AK,AQ,AJ,AT,KQ,KJ,KTs,QJs,QTs,JTs,T9s,98s,A9s,A8s,A5s,A4s,A3s,A2s"
    river = {"board": BOARD, "oop_range": "QcQd,Ac4c", "ip_range": "TcTd",
             "effective_stack": 100, "starting_pot": 100, "betting_lines": [[100]]}
    turn = {"board": "Qs Jh 2h 8c", "oop_range": oop, "ip_range": ip,
            "effective_stack": 540, "starting_pot": 180,
            "betting_lines": [[90], [0, 90], [0, 0, 90], [0, 0, 0, 90],
                              [90, 90, 270], [90, 90, 90, 270], [0, 90, 90, 270], [0, 90, 90, 90, 270]]}
    flop = {**turn, "board": "Qs Jh 2h",
            "betting_lines": [[90], [0, 90], [0, 0, 0, 0, 90], [0, 0, 0, 0, 0, 90],
                              [90, 90, 90, 90, 270], [90, 90, 90, 90, 90, 270],
                              [0, 90, 90, 90, 90, 270], [0, 90, 90, 90, 90, 90, 270]]}
    icm = {**river, "tournament": {"payouts": [60, 30, 10], "stacks": [100, 100, 100], "seats": [0, 1]}}
    flop_icm = {**flop, "tournament": {"payouts": [50, 30, 20], "stacks": [540, 810, 675, 405], "seats": [0, 1]}}
    return {
        "river": (river, RIVER_STEPS, "|allin", ("r:0", "r:0:b100")),
        "turn": (turn, [4, 8, 16, 32, 64, 128, 256, 512], "|bet:90", ("r:0", "r:0:b90")),
        "flop": (flop, [4, 8, 16, 32, 64, 128, 256], "|bet:90", ("r:0", "r:0:b90")),
        "river_icm": (icm, RIVER_STEPS, "|allin", ("r:0", "r:0:b100")),
        "flop_icm": (flop_icm, [8, 16, 32, 64, 128, 256, 512], "|bet:90", ("r:0", "r:0:b90")),
    }


def icm_utility(stack):
    """Exact three-seat Malmuth–Harville equity scaled by 400/100."""
    s = [stack, 300 - stack, 100]
    first = s[0] / 400
    second = sum((s[i] / 400) * s[0] / (400 - s[i]) for i in (1, 2))
    return 4 * (60 * first + 30 * second + 10 * (1 - first - second))


def icm_curves(cfg):
    """Enumerate finishing orders and tabulate every possible terminal stack."""
    t = cfg["tournament"]
    pot = cfg["starting_pot"]
    effective = cfg["effective_stack"]
    total = sum(t["stacks"]) + pot
    scale = total / sum(t["payouts"])
    commitments = {0, *(amount for line in cfg["betting_lines"] for amount in line)}
    points = {effective + pot // 2, effective + (pot + 1) // 2}
    points.update(effective - amount for amount in commitments)
    points.update(effective + pot + amount for amount in commitments)
    curves = []
    for hero, opp in (t["seats"], list(reversed(t["seats"]))):
        curve = {}
        for point in sorted(points):
            stacks = list(t["stacks"])
            stacks[hero] += point - effective
            stacks[opp] += effective + pot - point
            live = [i for i, stack in enumerate(stacks) if stack > 0]
            ev = 0.0
            if stacks[hero] == 0:
                ev = t["payouts"][len(live)] if len(live) < len(t["payouts"]) else 0.0
            else:
                for order in permutations(live):
                    place = order.index(hero)
                    if place >= len(t["payouts"]):
                        continue
                    remaining = total
                    chance = 1.0
                    for seat in order:
                        chance *= stacks[seat] / remaining
                        remaining -= stacks[seat]
                    ev += chance * t["payouts"][place]
            curve[point] = ev * scale
        curves.append(curve)
    return curves


class Pio:
    def __init__(self, path, threads, algorithm, iso):
        self.process = subprocess.Popen([str(path)], cwd=path.parent, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
        self.rows = queue.Queue()
        self.info = []

        def drain():
            for line in self.process.stdout:
                self.rows.put((perf_counter(), line.strip()))
            self.rows.put((perf_counter(), None))

        Thread(target=drain, daemon=True).start()
        try:
            self.banner = self.ask(f"set_end_string {END}")
            for cmd in ("is_ready", f"set_threads {threads}", "set_accuracy 0 chips",
                        f"set_isomorphism {int(iso)} 0", "set_info_freq 1000000",
                        f"set_algorithm {algorithm}"):
                self.ask(cmd)
            self.settings = self.ask("show_settings")
            self.version = self.ask("show_version")[0]
            self.build_id = self.ask("show_build_version")[0]
            self.hand_order = [hand_key(h) for h in " ".join(self.ask("show_hand_order")).split()]
            if set(self.hand_order) != {hand_key(h) for h in _PIO_HANDS}:
                raise ValueError("Unexpected Pio hand order")
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write("exit\n")
                self.process.stdin.flush()
                self.process.wait(timeout=3)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait()

    def next_row(self):
        t, row = self.rows.get(timeout=180)
        if row is None:
            raise RuntimeError(f"Pio exited {self.process.poll()}")
        return t, row

    def ask(self, cmd):
        self.process.stdin.write(cmd + "\n")
        self.process.stdin.flush()
        response = []
        while True:
            t, row = self.next_row()
            if row == END:
                if any(s.startswith("ERROR") for s in response):
                    raise RuntimeError(f"{cmd.split()[0]}: {response}")
                return response
            if row.startswith("SOLVER:"):
                self.info.append((t, row))
            elif row:
                response.append(row)

    def build(self, cfg):
        for side in ("oop", "ip"):
            weights = range_weights(cfg[f"{side}_range"])
            self.ask(f"set_range {side.upper()} " + " ".join(f"{weights.get(h, 0):.9g}" for h in self.hand_order))
        for cmd in ("set_board " + "".join(cfg["board"].split()), f"set_eff_stack {cfg['effective_stack']}",
                    f"set_pot 0 0 {cfg['starting_pot']}", "clear_lines"):
            self.ask(cmd)
        for line in cfg["betting_lines"]:
            self.ask("add_line " + " ".join(map(str, line)))
        self.icm_curves = icm_curves(cfg) if "tournament" in cfg else None
        start = perf_counter()
        self.ask("build_tree")
        if self.icm_curves is not None:
            self.ask("reset_icm_tables")
            for side, curve in zip(("OOP", "IP"), self.icm_curves):
                for stack, ev in curve.items():
                    self.ask(f"set_icm_point {side} {stack} {ev:.9g}")
            self.ask("set_icm {0} {0}".format(cfg["effective_stack"]))
        return perf_counter() - start

    def train(self, count):
        self.info.clear()
        request = perf_counter()
        self.ask(f"go {count} steps")
        while not any(line.startswith("SOLVER: stopped") for _, line in self.info):
            item = self.next_row()
            self.info.append(item)
        began = next(t for t, row in self.info if row.startswith("SOLVER: started"))
        ended = next(t for t, row in self.info if row.startswith("SOLVER: stopped"))
        return ended - request, ended - began

    def quality(self, cfg):
        start = perf_counter()
        results = self.ask("calc_results")
        elapsed = perf_counter() - start
        fields = {name.lower(): float(value) for name, value in (row.split(":", 1) for row in results if ":" in row)}
        ev = [fields["ev oop"], fields["ev ip"]]
        mes = [fields["oop's mes"], fields["ip's mes"]]
        exploit = fields["exploitable for"]
        if abs(exploit - sum(m - v for m, v in zip(mes, ev)) / 2) > 0.003:
            raise RuntimeError(f"Pio exploitability definition differs: {results}")
        return elapsed, 100 * exploit / cfg["starting_pot"], ev, mes

    def policy(self, node, weights):
        children = [row for row in self.ask(f"show_children {node}") if row.startswith(node + ":")]
        rows = [[float(x) for x in row.split()] for row in self.ask(f"show_strategy {node}")]
        if len(rows) != len(children) or any(len(row) != 1326 for row in rows):
            raise RuntimeError(f"Unexpected strategy shape at {node}")
        return {"line": node, "actions": [x.split(":")[-1] for x in children],
                "frequencies": {h: [row[i] for row in rows] for i, h in enumerate(self.hand_order) if h in weights}}


def pio_run(path, threads, algorithm, iso, case, checkpoints, terminal_probe=None):
    cfg, _, _, nodes = case
    launch = perf_counter()
    with Pio(path, threads, algorithm, iso) as pio:
        metadata = {"build_s": pio.build(cfg), "startup_setup_s": perf_counter() - launch,
                    "version": pio.version, "build_id": pio.build_id, "settings": pio.settings,
                    "root": pio.ask("show_node r:0")}
        if "tournament" in cfg:
            effective = cfg["effective_stack"]
            metadata["icm_curves"] = pio.icm_curves
            metadata["icm_baseline_cste"] = [curve[effective] for curve in pio.icm_curves]
            if terminal_probe is None:
                terminal_probe = ("r:0:b100:c", 100) if len(cfg["board"].split()) == 5 else (
                    "r:0:b90:c:8c:c:c:3d:b270:c", 270)
            showdown, t = terminal_probe
            pot = cfg["starting_pot"]
            metadata["terminal_probe"] = showdown
            metadata["terminal_evs"] = [pio.ask(f"show_win_evs {p} {showdown}") for p in ("OOP", "IP")]
            for i, (observed,) in enumerate(metadata["terminal_evs"]):
                curve = pio.icm_curves[i]
                points = (effective + pot + t, effective - t, effective + (pot + 1 - i) // 2)
                expected = [curve[x] - curve[effective] for x in points]
                if any(abs(float(a) - b) > 0.0003 for a, b in zip(observed.split(), expected, strict=True)):
                    raise RuntimeError(f"ICM terminal EV mismatch at {showdown}: {observed} vs {expected}")
        train_s = worker_s = check_s = 0
        rows = []
        for iteration in checkpoints:
            t, w = pio.train(iteration - (rows[-1]["iteration"] if rows else 0))
            train_s += t
            worker_s += w
            dt, pct, ev, mes = pio.quality(cfg)
            check_s += dt
            actual = int(pio.ask("show_iters")[0])
            if actual != iteration:
                raise RuntimeError(f"Pio requested {iteration} iterations but reported {actual}")
            rows.append({"iteration": actual, "train_s": train_s, "worker_s": worker_s, "check_s": check_s,
                         "pct_pot": pct, "pot_ev": ev, "root_br": mes})
        rows[-1]["policy"] = [pio.policy(node, range_weights(cfg[f"{seat}_range"]))
                              for node, seat in zip(nodes, ("oop", "ip"))]
        return metadata, rows


def local_run(path, threads, case, config_path, checkpoints):
    _, _, nodes, _ = case
    start = perf_counter()
    result = subprocess.run([str(path), str(config_path), str(threads), ",".join(map(str, checkpoints)), nodes],
                            capture_output=True, text=True, encoding="utf-8", timeout=240, check=True)
    elapsed = perf_counter() - start
    metadata, *rows = map(json.loads, result.stdout.splitlines())
    metadata["process_s"] = elapsed
    for row in rows:
        for node in row["policy"]:
            node["frequencies"] = {hand_key(h): val for h, val in node["frequencies"].items()}
    return metadata, rows


def qualifying_checkpoint(sweep, threshold, rounding_margin):
    for i, row in enumerate(sweep):
        if all(point["pct_pot"] + rounding_margin <= threshold for point in sweep[i:]):
            return row["iteration"]
    return None


def summarize(sweep, trials, rounding_margin):
    output = {}
    for threshold in TARGETS:
        iteration = qualifying_checkpoint(sweep, threshold, rounding_margin)
        if iteration is None:
            continue
        runs = trials[str(iteration)]
        if not all(r["rows"][0]["pct_pot"] + rounding_margin <= threshold for r in runs):
            continue
        output[str(threshold)] = {"iteration": iteration,
                                  "build_s": median(r["metadata"]["build_s"] for r in runs),
                                  "train_s": median(r["rows"][0]["train_s"] for r in runs),
                                  "worker_s": median(r["rows"][0].get("worker_s", r["rows"][0]["train_s"]) for r in runs),
                                  "check_s": median(r["rows"][0]["check_s"] for r in runs),
                                  "solve_to_result_s": median(r["rows"][0]["train_s"] + r["rows"][0]["check_s"] for r in runs),
                                  "build_to_result_s": median(r["metadata"]["build_s"] + r["rows"][0]["train_s"] + r["rows"][0]["check_s"] for r in runs),
                                  "pct_pot": median(r["rows"][0]["pct_pot"] for r in runs)}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pio", required=True, type=Path)
    parser.add_argument("--local", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--cases", nargs="+", choices=cases(), default=["river", "turn", "flop", "river_icm"])
    parser.add_argument("--modes", nargs="+", choices=("local", "v4_small", "pio_cfr", "v4_iso"),
                        default=["local", "v4_small"])
    parser.add_argument("--preset", type=Path, help="benchmark one imported Pio flop preset")
    parser.add_argument("--board", help="override the imported flop, for Pio Free board restrictions")
    parser.add_argument("--tournament", type=Path, help="JSON payout and stack structure for the imported preset")
    parser.add_argument("--checkpoints", nargs="+", type=int, help="override the iteration checkpoints")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.threads < 1 or args.trials < 1:
        parser.error("threads and trials must be positive")
    pio_path, local_path = args.pio.resolve(), args.local.resolve()
    report = {"threads": args.threads, "trials": args.trials, "pio_sha256": hashlib.sha256(pio_path.read_bytes()).hexdigest(),
              "local_sha256": hashlib.sha256(local_path.read_bytes()).hexdigest(), "cases": {}}
    definitions = {name: cases()[name] for name in args.cases}
    terminal_probe = None
    if args.preset is not None:
        if args.tournament is None:
            parser.error("--preset needs a --tournament JSON file")
        cfg = import_pio(args.preset)
        original_board = cfg["board"]
        cfg["board"] = args.board or original_board
        if len(cfg["board"].split()) != 3 or len(original_board.split()) != 3:
            parser.error("--preset requires a flop preset and a three-card board")
        if cfg["starting_pot"] % 2:
            parser.error("--preset needs an even starting pot to align split-pot payoffs")
        original_rake = cfg.pop("rake", None)
        cfg["tournament"] = json.loads(args.tournament.read_text(encoding="utf-8-sig"))
        if len(cfg["tournament"]["stacks"]) > 8:
            parser.error("the independent finishing-order benchmark supports at most eight seats")
        openings = [line[0] for line in cfg["betting_lines"] if line[0] > 0]
        if not openings:
            parser.error("preset needs an OOP opening bet for strategy comparison")
        bet = min(openings)
        token = "allin" if bet == cfg["effective_stack"] else f"bet:{bet}"
        turn, river = [c for c in ("8c", "3d", "5s", "7d", "4h") if c not in cfg["board"].split()][:2]
        terminal_probe = (f"r:0:c:c:{turn}:c:c:{river}:c:c", 0)
        definitions = {"preset_icm": (
            cfg, [16, 32, 64, 96, 128, 192, 256, 384, 512], f"|{token}", ("r:0", f"r:0:b{bet}"),
        )}
        report["preset"] = {
            "path": str(args.preset.resolve()), "sha256": hashlib.sha256(args.preset.read_bytes()).hexdigest(),
            "original_board": original_board, "removed_rake": original_rake,
        }
    elif args.board or args.tournament:
        parser.error("--board and --tournament require --preset")
    if args.checkpoints and (args.checkpoints[0] < 1 or any(a >= b for a, b in zip(args.checkpoints, args.checkpoints[1:]))):
        parser.error("--checkpoints must be positive and strictly increasing")
    for name, case in definitions.items():
        cfg, checkpoints, _, _ = case
        checkpoints = args.checkpoints or checkpoints
        path = args.out.parent / (name + ".config.json")
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        result = report["cases"][name] = {"config": cfg, "modes": {}}
        for mode in args.modes:
            if mode == "v4_iso" and len(cfg["board"].split()) != 3:
                continue
            def run(points):
                if mode == "local":
                    return local_run(local_path, args.threads, case, path.resolve(), points)
                algorithm = "v4_small" if mode == "v4_iso" else mode
                return pio_run(pio_path, args.threads, algorithm, mode == "v4_iso", case, points, terminal_probe)
            print(f"{name} / {mode}: sweep", flush=True)
            metadata, rows = run(checkpoints)
            margin = 0 if mode == "local" else 0.05 / cfg["starting_pot"]
            candidates = {qualifying_checkpoint(rows, threshold, margin) for threshold in TARGETS} - {None}
            trials = {}
            for iteration in sorted(candidates):
                print(f"{name} / {mode}: {args.trials} fresh runs at {iteration} steps", flush=True)
                trials[str(iteration)] = [{"metadata": m, "rows": r} for m, r in (run([iteration]) for _ in range(args.trials))]
            result["modes"][mode] = {"metadata": metadata, "sweep": rows, "trials": trials,
                                     "targets": summarize(rows, trials, margin)}
            args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(result["modes"][mode]["targets"]), flush=True)


if __name__ == "__main__":
    main()
