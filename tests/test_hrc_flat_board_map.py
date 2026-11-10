"""Production flat index correctness and bounded resource-loading contracts."""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/native/flat_board_map_probe.cpp"
HEADERS = [ROOT / "native/hrc_flat_board_map.hpp", ROOT / "native/hrc_cards.hpp"]


@pytest.fixture(scope="module")
def probe():
    folder = ROOT / ".research-cache/flat-board-map-tests"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(SOURCE.read_bytes() + b"".join(p.read_bytes() for p in HEADERS)).hexdigest()[:20]
    executable = folder / (digest + (".exe" if os.name == "nt" else ""))
    if not executable.exists():
        zig = Path("D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe")
        if zig.exists():
            command = [str(zig), "c++"]
        elif shutil.which("g++"):
            command = ["g++"]
        else:
            pytest.skip("C++17 compiler unavailable")
        subprocess.run(command + ["-O2", "-std=c++17", "-ffp-contract=off", "-pthread", str(SOURCE), "-o", str(executable)],
                       check=True, capture_output=True, text=True, timeout=60)
    return executable


def invoke(probe, *args):
    result = subprocess.run([str(probe), *map(str, args)], check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def unit(probe):
    return invoke(probe, "--unit")


def test_collisions_wraparound_missing_and_duplicate_keys(unit):
    assert unit["ok"] and unit["collision_chain"] == 64 and unit["wraparound"]
    assert unit["missing_keys"] == 10000 and unit["duplicate_preserves_value"]


def test_capacity_overflow_and_half_full_limit_keep_missing_queries_bounded(unit):
    assert unit["overflow_rejected_before_allocation"] and unit["load_factor_limit"] == .5


def test_move_publication_and_shared_readers_preserve_values(unit):
    assert unit["move_preserves_mapping"] and unit["concurrent_reads"] == 80000


@pytest.fixture(scope="module")
def resource_result(probe):
    folder = Path(os.environ.get("HRC_ABSTRACTION_DIR", ROOT / ".research-cache/abstractions"))
    if not all((folder / f"street{street}.{suffix}").is_file()
               for street in (1, 2, 3) for suffix in ("boards.u64", "buckets.u16")):
        pytest.skip("Locally prepared static abstraction resources unavailable")
    result = invoke(probe, "--resources", folder)
    (ROOT / ".research-cache/flat-board-map-tests/resource-result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def test_every_resource_board_key_matches_original_row_order(resource_result):
    assert resource_result["ok"] and resource_result["resource_keys"] == 1755 + 16432 + 134459


def test_sampled_rows_match_raw_resource_legal_hole_order(resource_result):
    assert resource_result["sampled_canonical_rows"] == 3 * 256
    assert resource_result["legal_bucket_comparisons"] == 256 * (1176 + 1128 + 1081)


def test_resource_budget_covers_actual_arrays_and_loader_temporaries(resource_result):
    assert resource_result["map_allocated_bytes"] <= resource_result["map_budget_bytes"]
    assert resource_result["load_peak_array_bound_bytes"] <= resource_result["production_resource_budget_bytes"]


@pytest.mark.parametrize("damage,expected", [
    ("truncated_boards", "Wrong abstraction size"),
    ("duplicate_board", "Invalid canonical board index"),
    ("wrong_card_count", "Invalid canonical board index"),
    ("truncated_buckets", "Wrong abstraction size"),
    ("bucket_outside_profile", "Abstraction bucket outside profile bounds"),
])
def test_loader_rejects_malformed_first_street_before_using_rows(probe, tmp_path, damage, expected):
    # Synthetic bytes only; no installed resource is copied or modified.
    boards = sorted(sum(1 << card for card in cards) for cards in itertools.combinations(range(24), 3))[:1755]
    if damage == "duplicate_board":
        boards[1] = boards[0]
    elif damage == "wrong_card_count":
        boards[-1] = (1 << 50) | (1 << 49)
    data = struct.pack("<1755Q", *boards)
    (tmp_path / "street1.boards.u64").write_bytes(data[:-1] if damage == "truncated_boards" else data)
    buckets = bytearray(1755 * 1176 * 2)
    if damage == "bucket_outside_profile":
        struct.pack_into("<H", buckets, 0, 1024)
    (tmp_path / "street1.buckets.u16").write_bytes(buckets[:-1] if damage == "truncated_buckets" else buckets)
    result = invoke(probe, "--load", tmp_path)
    assert result["loaded"] is False and expected in result["error"]
