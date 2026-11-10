"""Python interface to the local Rust engine. The inputs and outputs are plain JSON."""

import json
import math
import subprocess
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory


_RANKS = "23456789TJQKA"
_CARDS = tuple(rank + suit for rank in _RANKS for suit in "cdhs")
_PIO_HANDS = tuple(_CARDS[hi] + _CARDS[lo] for hi in range(52) for lo in range(hi))


def _pio_range(weights):
    if len(weights) != 1326:
        raise ValueError("set_range requires 1326 weights in Pio hand order")
    combos = []
    for combo, token in zip(_PIO_HANDS, weights):
        weight = float(token)
        if not math.isfinite(weight) or not 0 <= weight <= 1:
            raise ValueError(f"invalid range weight for {combo}: {token}")
        if weight:
            combos.append(combo if weight == 1 else f"{combo}:{token}")
    if not combos:
        raise ValueError("set_range has no positive weights")
    return ",".join(combos)


def _pio_rake(fraction, cap):
    fraction, cap = float(fraction), float(cap)
    if not 0 <= fraction <= 1 or not math.isfinite(cap) or cap < 0:
        raise ValueError("invalid rake fraction or cap")
    if fraction > 0 and cap == 0:
        raise ValueError("positive Pio rake with zero cap has ambiguous engine semantics")
    return {"percent": 100 * fraction, "cap": cap}


def import_pio(path, *, rake_source="commands"):
    """Translate a Pio preset with embedded postflop build commands into a config.

    The default uses the saved commands. Set rake_source='fields' to use the
    Viewer fields on presets where the stored tail and the fields disagree.
    """
    if rake_source not in ("commands", "fields"):
        raise ValueError("rake_source must be 'commands' or 'fields'")
    text = Path(path).read_text(encoding="utf-8-sig")
    fields, config = {}, {"betting_lines": []}
    seen = set()
    in_lines = built = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            key, sep, value = line[1:].partition("#")
            if sep:
                fields[key] = value
            continue
        op, *args = line.split()
        try:
            key = (op, args[0]) if op == "set_range" and args else (op,)
            if op != "add_line" and key in seen:
                raise ValueError(f"duplicate {op}")
            seen.add(key)
            if built and op != "set_rake":
                raise ValueError(f"unexpected {op} after build_tree")
            if op == "set_range" and args and args[0] in ("OOP", "IP"):
                config[f"{args[0].lower()}_range"] = _pio_range(args[1:])
            elif op == "set_board" and args:
                cards = "".join(args)
                board = [cards[i:i+2] for i in range(0, len(cards), 2)]
                if len(board) not in (3, 4, 5) or len(set(board)) != len(board) or not set(board) <= set(_CARDS):
                    raise ValueError("invalid board")
                config["board"] = " ".join(board)
            elif op == "set_eff_stack" and len(args) == 1:
                config["effective_stack"] = int(args[0])
                if not 0 < config["effective_stack"] <= 0xFFFFFFFF:
                    raise ValueError("effective stack out of range")
            elif op == "set_pot" and len(args) == 3:
                oop, ip, dead = map(int, args)
                if oop or ip or dead <= 0:
                    raise ValueError("only set_pot 0 0 <positive dead pot> is supported")
                config["starting_pot"] = dead
            elif op == "clear_lines" and not args:
                in_lines = True
            elif op == "add_line" and in_lines and args:
                amounts = list(map(int, args))
                if any(not 0 <= amount <= 0xFFFFFFFF for amount in amounts):
                    raise ValueError("betting-line amount out of range")
                config["betting_lines"].append(amounts)
            elif op == "build_tree" and in_lines and args in ([], ["mem_ignore"], ["mem_pessimistic"]):
                built = True
            elif op == "set_isomorphism" and len(args) == 2 and all(a in ("0", "1") for a in args):
                pass  # This engine enumerates all runouts.
            elif op == "set_rake" and len(args) == 2:
                config["rake"] = _pio_rake(*args)
            else:
                raise ValueError(f"unsupported or malformed build command: {op}")
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    required = {"board", "oop_range", "ip_range", "effective_stack", "starting_pot"}
    if not built or required - config.keys():
        raise ValueError(f"{path}: incomplete postflop build commands")
    if rake_source == "fields":
        if fields.get("Rake.Enabled", "false").lower() == "true":
            try:
                config["rake"] = _pio_rake(fields["Rake.Fraction"], fields["Rake.Cap"])
            except KeyError as exc:
                raise ValueError(f"{path}: missing rake field {exc}") from exc
        else:
            config.pop("rake", None)
    return config


class Solver:
    def __init__(self, executable=None):
        if executable is None:
            executable = Path(__file__).with_name("bin") / "solver.exe"
        self.executable = Path(executable).resolve()
        if not self.executable.is_file():
            raise FileNotFoundError(f"{self.executable}; build with postflop_lab/Build.ps1")

    def _run(self, args, timeout):
        result = subprocess.run([str(self.executable), *map(str, args)], text=True, encoding="utf-8",
                                capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"solver exit {result.returncode}")
        return result.stdout

    @staticmethod
    def _config_path(config, work):
        if isinstance(config, Mapping):
            path = work / "spot.json"
            path.write_text(json.dumps(dict(config), allow_nan=False), encoding="utf-8")
            return path
        return Path(config).resolve()

    def solve(self, config, output, *, threads=None, report_every=100, storage="f32",
              max_strategy_mib=4096, timeout=None):
        """Train and atomically publish a solution, returning the run's text log."""
        output = Path(output).resolve()
        if not isinstance(config, Mapping) and Path(config).resolve() == output:
            raise ValueError("solution output cannot replace the input config")
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="postflop-", dir=output.parent) as work:
            work = Path(work)
            config_path = self._config_path(config, work)
            staged = work / "solution.json"
            args = ["solve", "--config", config_path, "--out", staged,
                    "--report-every", report_every, "--storage", storage,
                    "--max-strategy-mib", max_strategy_mib]
            if threads is not None:
                args.extend(["--threads", threads])
            log = self._run(args, timeout)
            staged.replace(output)
            return log

    def tree(self, config, line="", *, timeout=None):
        """Return JSON describing a node and its available actions before training."""
        with TemporaryDirectory(prefix="postflop-") as work:
            path = self._config_path(config, Path(work))
            return json.loads(self._run(["tree", "--config", path, f"--line={line}"], timeout))

    def query(self, solution, line="", *, ev=False, timeout=None):
        """Read saved combo strategies and optionally compute node/action EVs."""
        args = ["query", "--solution", Path(solution).resolve(), f"--line={line}"]
        if ev:
            args.append("--ev")
        return json.loads(self._run(args, timeout))
