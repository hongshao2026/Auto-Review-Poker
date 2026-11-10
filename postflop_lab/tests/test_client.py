import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from postflop_lab import Solver, import_pio


RIVER = json.loads((Path(__file__).parents[1] / "examples/river.json").read_text(encoding="utf-8"))
TOURNAMENT = {"payouts": [500, 300, 200], "stacks": [20, 32, 45, 12, 8, 15], "seats": [0, 1]}


class LocalSolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.solver = Solver()

    def test_river_chip_and_icm_change_policy(self):
        with TemporaryDirectory() as directory:
            chips, icm = [Path(directory, f"{name}.json") for name in ("chips", "icm")]
            self.solver.solve(RIVER, chips, threads=1, report_every=100)
            self.solver.solve({**RIVER, "tournament": TOURNAMENT}, icm, threads=1, report_every=100)
            chip_node, icm_node = [self.solver.query(path, "bet:10", ev=True) for path in (chips, icm)]
            self.assertEqual(chip_node["meta"]["payoff_unit"], "chips")
            self.assertEqual(icm_node["meta"]["payoff_unit"], "cste")
            for node in (chip_node, icm_node):
                self.assertLess(node["meta"]["exploitability_pct_of_pot"], 0.5)
                self.assertTrue(node["hands"])
                for hand in node["hands"]:
                    self.assertAlmostEqual(sum(hand["frequencies"]), 1.0, places=5)
                    self.assertTrue(all(math.isfinite(ev) for ev in hand["action_evs"]))
                    self.assertAlmostEqual(hand["ev"], sum(p * ev for p, ev in zip(hand["frequencies"], hand["action_evs"])), places=5)
            delta = max(abs(a - b) for x, y in zip(chip_node["hands"], icm_node["hands"])
                        for a, b in zip(x["frequencies"], y["frequencies"]))
            self.assertGreater(delta, 0.01)

    def test_exact_tree_and_chance_query(self):
        config = {**RIVER, "board": "Ks 7d 2c 8h", "max_iterations": 6,
                  "betting_lines": [[5, 5, 5, 12], [0, 0, 7]], "sizings": {}}
        root = self.solver.tree(config)
        self.assertEqual([a["token"] for a in root["actions"]], ["check", "bet:5"])
        river_line = "bet:5,call,Ah,check"
        river = self.solver.tree(config, river_line)
        self.assertEqual([a["token"] for a in river["actions"]], ["check", "bet:7"])
        self.assertEqual(river["pot"], 20)
        with TemporaryDirectory() as directory:
            output = Path(directory, "turn.json")
            self.solver.solve(config, output, threads=2, report_every=6)
            self.assertEqual(self.solver.query(output, "bet:5,call")["kind"], "chance")
            node = self.solver.query(output, river_line, ev=True)
            self.assertEqual(node["board"][-1], "Ah")
            self.assertTrue(any(hand["ev"] is not None for hand in node["hands"]))

    def test_lock_and_failed_solve_preserve_previous_file(self):
        config = {**RIVER, "locks": [{"line": "", "player": 0, "freqs": [0.8, 0.2]}], "max_iterations": 2}
        with TemporaryDirectory() as directory:
            output = Path(directory, "solution.json")
            self.solver.solve(config, output, threads=1)
            for hand in self.solver.query(output)["hands"]:
                self.assertAlmostEqual(hand["frequencies"][0], 0.8, places=6)
            previous = output.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "board"):
                self.solver.solve({**config, "board": "As"}, output)
            self.assertEqual(output.read_bytes(), previous)

    def test_import_vector_order_and_reject_unknown_upi(self):
        # Pio's first combo is 2d2c, followed by 2h2c.
        weights = " ".join(["0", "0.75", *(["0"] * 1324)])
        content = f"""#Rake.Enabled#True
#Rake.Fraction#0.05
#Rake.Cap#10
set_range OOP {weights}
set_range IP {weights}
set_board AsKd7hTcJd
set_eff_stack 20
set_pot 0 0 10
clear_lines
add_line 5
build_tree
"""
        with TemporaryDirectory() as directory:
            path = Path(directory, "preset.txt")
            path.write_text(content, encoding="utf-8")
            cfg = import_pio(path)
            self.assertEqual(cfg["oop_range"], "2h2c:0.75")
            self.assertEqual(cfg["betting_lines"], [[5]])
            self.assertNotIn("rake", cfg)
            self.assertEqual(import_pio(path, rake_source="fields")["rake"], {"percent": 5, "cap": 10})
            path.write_text(content + "load_tree other.cfr\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "load_tree"):
                import_pio(path)

    def test_rake_uses_unilateral_gain_and_can_stop(self):
        config = {**RIVER, "sizings": {}, "rake": {"percent": 5, "cap": 20}, "max_iterations": 3}
        with TemporaryDirectory() as directory:
            output = Path(directory, "raked.json")
            log = self.solver.solve(config, output, threads=1, report_every=1)
            meta = self.solver.query(output)["meta"]
            self.assertIn("NashConv:", log)
            self.assertAlmostEqual(meta["exploitability_chips"], 0.0, places=6)
            self.assertEqual(meta["iterations"], 1)

    def test_resource_limits_are_errors(self):
        with self.assertRaisesRegex(RuntimeError, "max_tree_nodes"):
            self.solver.tree({**RIVER, "max_tree_nodes": 1})
        config = {**RIVER, "board": "Ks 7d 2c 8h", "oop_range": "random", "ip_range": "random",
                  "sizings": {}, "betting_lines": [[5, 5, 5, 12], [0, 0, 7]], "max_iterations": 1}
        with TemporaryDirectory() as directory:
            output = Path(directory, "solution.json")
            with self.assertRaisesRegex(RuntimeError, "strategy arrays require"):
                self.solver.solve(config, output, max_strategy_mib=1)
            self.assertFalse(output.exists())

    def test_in_the_money_bust_preserves_river_equilibrium(self):
        config = {"board": "Qs Jh 2h 8c 3d", "oop_range": "QcQd,Ac4c", "ip_range": "TcTd",
                  "effective_stack": 100, "starting_pot": 100, "betting_lines": [[100]],
                  "tournament": {"payouts": [60, 30, 10], "stacks": [100, 100, 100], "seats": [0, 1]},
                  "max_iterations": 2048, "target_exploitability": 0}
        with TemporaryDirectory() as directory:
            output = Path(directory, "paid-bust.json")
            self.solver.solve(config, output, threads=1, report_every=2048)
            root = self.solver.query(output)
            response = self.solver.query(output, "allin")
            allin = next(i for i, a in enumerate(root["actions"]) if a["token"] == "allin")
            call = next(i for i, a in enumerate(response["actions"]) if a["token"] == "call")
            bluff = next(h for h in root["hands"] if set((h["combo"][:2], h["combo"][2:])) == {"Ac", "4c"})
            self.assertAlmostEqual(bluff["frequencies"][allin], 23/28, delta=0.002)
            self.assertAlmostEqual(response["hands"][0]["frequencies"][call], 15/38, delta=0.002)
            for actual, expected in zip(root["meta"]["root_evs"]["pot_share"], (150.21929825, 121.13095238)):
                self.assertAlmostEqual(actual, expected, delta=0.02)


if __name__ == "__main__":
    unittest.main()
