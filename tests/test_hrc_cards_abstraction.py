"""Independent native evaluator / local abstraction reader verification.

Native compilation is skipped only if no suitable local compiler exists.
Exact profile tests are skipped if the separately prepared local cache is absent.
No original HRC classes or solver are invoked by this test suite.
"""
import array
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

from preflop_lab.hrc_abstraction import (
    PROFILES, canonical_board, canonical_boards, combo_index,
    legal_hole_column, permute_mask, preflop_class, file_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("HRC_ABSTRACTION_CACHE", ROOT / ".research-cache/abstractions"))
DRIVER = r'''
#include "hrc_cards.hpp"
#include <iostream>
#include <chrono>
int main(int argc,char**argv) {
  if(argc==4 && std::string(argv[1])=="--compact") {
    try {auto values=hrc_cards::read_compact_buckets(argv[2],std::stoull(argv[3]));for(auto v:values)std::cout<<int(v)<<' ';}
    catch(const std::exception& e){std::cerr<<e.what();return 1;}return 0;
  }
  hrc_cards::AbstractionTables tables;
  if(argc>1) tables.load(argv[1]);
  char op;uint64_t mask;int street,combo;
  while(std::cin>>op) {
    if(op=='R') {std::cin>>mask;std::cout<<hrc_cards::rank7(mask)<<'\n';}
    if(op=='P') {std::cin>>combo;std::cout<<hrc_cards::preflop_class(combo)<<'\n';}
    if(op=='C') {std::cin>>mask;auto c=hrc_cards::canonical_board(mask);std::cout<<c.mask;for(auto p:c.suit_map)std::cout<<' '<<p;std::cout<<'\n';}
    if(op=='B') {std::cin>>street>>mask>>combo;int out;hrc_cards::fill_street_buckets(street,&combo,1,mask,tables,&out);std::cout<<out<<'\n';}
    if(op=='S') {for(int s=1;s<=3;++s)std::cout<<tables.streets[s].values.size()*sizeof(uint16_t)+tables.streets[s].compact_values.size()<<' ';std::cout<<'\n';}
    if(op=='T') {
      int n;std::cin>>n;std::vector<uint64_t> hands(n);for(auto &m:hands)std::cin>>m;
      volatile uint64_t total=0;auto begin=std::chrono::steady_clock::now();
      for(int k=0;k<1000;++k)for(auto m:hands)total+=hrc_cards::rank7(m);
      double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
      std::cout<<n*1000<<' '<<seconds<<' '<<total<<'\n';
    }
  }
}
'''


class MappingMathTests(unittest.TestCase):
    def test_full_flop_canonical_index_matches_original_probe(self):
        boards = canonical_boards(1)
        values = array.array("Q", boards)
        if __import__("sys").byteorder != "little":
            values.byteswap()
        import hashlib
        self.assertEqual(hashlib.sha256(values.tobytes()).hexdigest(),
                         "b5f4eb663ab0657ceb31273943d2aa96c87e025804b65983358464e0c52933ac")

    def test_legal_column_against_enumeration(self):
        rng = random.Random(5225)
        for n in (3, 4, 5):
            for _ in range(20):
                board = sum(1 << c for c in rng.sample(range(52), n))
                legal = [(l, h) for h in range(1, 52) for l in range(h)
                         if not board & ((1 << h) | (1 << l))]
                self.assertEqual([legal_hole_column(board, l, h) for l, h in legal], list(range(len(legal))))


class NativeCardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="hrc-independent-cards-")
        directory = Path(cls.temp.name)
        source = directory / "probe.cpp"
        source.write_text(DRIVER, encoding="utf-8")
        cls.binary = directory / ("probe.exe" if os.name == "nt" else "probe")
        vs = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\Common7\Tools\VsDevCmd.bat")
        zig_candidates = [Path(r"D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe"),
                          Path(r"D:\Tools\REA-Research\zig-x86_64-windows-0.15.2\zig.exe")]
        zig = next((p for p in zig_candidates if p.exists()), zig_candidates[0])
        if zig.exists():
            run = subprocess.run([str(zig), "c++", "-O3", "-std=c++17", "-I", str(ROOT / "native"), str(source), "-o", str(cls.binary)], capture_output=True, text=True, errors="replace")
        elif os.name == "nt" and vs.exists():
            batch = directory / "build.cmd"
            batch.write_text('@echo off\ncall "' + str(vs) + '" -arch=x64 -host_arch=x64\n'
                             'cl /nologo /O2 /EHsc /std:c++17 /I"' + str(ROOT / "native") + '" "'
                             + str(source) + '" /Fe:"' + str(cls.binary) + '" /Fo:"' + str(directory / "probe.obj") + '"\n', encoding="utf-8")
            run = subprocess.run(["cmd.exe", "/d", "/c", str(batch)], capture_output=True, text=True, errors="replace")
        elif shutil.which("g++"):
            run = subprocess.run(["g++", "-O3", "-std=c++17", "-I", str(ROOT / "native"), str(source), "-o", str(cls.binary)], capture_output=True, text=True)
        else:
            cls.temp.cleanup()
            raise unittest.SkipTest("No local C++ compiler")
        if run.returncode:
            raise RuntimeError(run.stdout + run.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_probe(self, lines, resources=False):
        command = [str(self.binary)] + ([str(CACHE)] if resources else [])
        run = subprocess.run(command, input="\n".join(lines) + "\n", text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        return run.stdout.splitlines()

    def test_rank_order_ties_against_installed_phevaluator(self):
        try:
            from phevaluator import evaluate_cards
        except ImportError:
            self.skipTest("PHEvaluator not installed in this interpreter")
        rng = random.Random(20261105)
        hands = [rng.sample(range(52), 7) for _ in range(30000)]
        # Wheel/royal, two trips, three pairs, quads, flush kickers and ties.
        names = ["Ac 2c 3c 4c 5c 9d Td", "Tc Jc Qc Kc Ac 2d 3h", "Ac Ad Ah Kc Kd Kh 2s",
                 "Ac Ad Kc Kd Qc Qd 2s", "Ac Ad Ah As Kc 2d 3h", "Ac Kc Qc 9c 2c 7d 8h",
                 "Ac Kd Qh Js Tc 2d 3h", "Ah Ks Qd Jc Th 4d 5h"]
        ranks = "23456789TJQKA"; suits = "cdhs"
        hands += [[ranks.index(c[0]) * 4 + suits.index(c[1]) for c in s.split()] for s in names]
        native = [int(x) for x in self.run_probe([f'R {sum(1 << c for c in h)}' for h in hands])]
        oracle = [evaluate_cards(*h) for h in hands]
        mapping = {}
        for rank, actual in zip(oracle, native):
            if rank in mapping:
                self.assertEqual(mapping[rank], actual, "Tie mismatch")
            mapping[rank] = actual
        ordered = [mapping[r] for r in sorted(mapping)]
        self.assertTrue(all(a > b for a, b in zip(ordered, ordered[1:])), "Relative ranking mismatch")
        self.assertEqual(native[-2], native[-1])
        self.assertGreater(native[-7], native[-8])
        print(json.dumps({"independent_rank_cases": len(hands), "distinct_rank_classes": len(mapping), "all_passed": True}))

    def test_native_preflop_all_1326_and_suit_canonicalization(self):
        pairs = [(l, h) for h in range(1, 52) for l in range(h)]
        out = self.run_probe([f'P {combo_index(l,h)}' for l,h in pairs])
        self.assertEqual([int(x) for x in out], [preflop_class(l,h) for l,h in pairs])
        rng = random.Random(310)
        boards = [sum(1 << c for c in rng.sample(range(52), n)) for n in (3,4,5) for _ in range(1000)]
        out = self.run_probe([f'C {m}' for m in boards])
        for board, line in zip(boards, out):
            actual = [int(x) for x in line.split()]
            canonical, mapping = canonical_board(board)
            self.assertEqual(actual, [canonical, *mapping])

    def test_exact_profiles_native_lookup_and_suit_invariance(self):
        if not (CACHE / "manifest.json").exists():
            self.skipTest("Local abstraction resource cache is absent")
        manifest = json.loads((CACHE / "manifest.json").read_text())
        rng = random.Random(98174)
        lines, expected = [], []
        for profile in manifest["profiles"]:
            street = profile["street"]
            self.assertEqual((profile["buckets"], profile["id"]), PROFILES[street])
            self.assertEqual(file_sha256(CACHE / profile["values_file"]), profile["id"])
            boards = array.array("Q"); values = array.array("H")
            with (CACHE / profile["boards_file"]).open("rb") as f:
                boards.fromfile(f, profile["rows"])
            with (CACHE / profile["values_file"]).open("rb") as f:
                values.fromfile(f, profile["rows"] * profile["hole_columns"])
            for _ in range(75):
                row = rng.randrange(len(boards)); board = boards[row]
                legal = [(l,h) for h in range(1,52) for l in range(h) if not board & ((1<<h)|(1<<l))]
                col = rng.randrange(len(legal)); lo,hi = legal[col]
                expected_bucket = values[row * len(legal) + col]
                for permutation in itertools.permutations(range(4)):
                    new_board = permute_mask(board, permutation)
                    new_lo = 4*(lo//4)+permutation[lo%4]; new_hi = 4*(hi//4)+permutation[hi%4]
                    lines.append(f'B {street} {new_board} {combo_index(new_lo,new_hi)}')
                    expected.append(expected_bucket)
            del values
        actual = [int(x) for x in self.run_probe(lines, resources=True)]
        self.assertEqual(actual, expected)
        stored = list(map(int, self.run_probe(['S'], resources=True)[0].split()))
        self.assertEqual(stored, [4_127_760, 18_535_296, 145_350_179])
        print(json.dumps({"exact_profile_cases": len(actual), "streets": 3, "suit_permutations": 24, "all_passed": True}))

    def test_compact_reader_chunk_boundaries_and_byte_limits(self):
        # The last partial chunk and both ends of the uint8 domain must survive
        # conversion; malformed u16 values must fail before being truncated.
        values = [(i*17)%256 for i in range(16_384+3)]
        path = Path(self.temp.name)/'compact.u16'
        data = array.array('H', values)
        if __import__('sys').byteorder != 'little':
            data.byteswap()
        path.write_bytes(data.tobytes())
        command = [str(self.binary), '--compact', str(path), str(len(values))]
        output = subprocess.check_output(command, text=True)
        self.assertEqual(list(map(int, output.split())), values)
        for invalid in (256, 65535):
            with path.open('r+b') as stream:
                stream.seek(-2, 2)
                stream.write(invalid.to_bytes(2, 'little'))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('outside profile bounds', result.stderr)
        path.write_bytes(data.tobytes()[:-1])
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Wrong abstraction size', result.stderr)

    def test_rank_throughput(self):
        rng = random.Random(882)
        hands = [sum(1 << c for c in rng.sample(range(52),7)) for _ in range(10000)]
        line = self.run_probe(['T 10000 ' + ' '.join(map(str,hands))])[0]
        evaluations, seconds, checksum = line.split()
        self.assertGreater(int(checksum), 0)
        print(json.dumps({"rank_benchmark_evaluations": int(evaluations), "seconds": float(seconds),
                          "evaluations_per_second": int(evaluations)/float(seconds), "scope": "ranking only; not training throughput"}))


if __name__ == "__main__":
    unittest.main()
