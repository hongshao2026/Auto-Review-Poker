"""Bounded native lock correctness under oversubscription and exception unwinding."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/native/node_mutex_stress.cpp"
HEADER = ROOT / "native/hrc_node_mutex.hpp"


@pytest.fixture(scope="module")
def result():
    folder = ROOT / ".research-cache/node-mutex-tests"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(SOURCE.read_bytes() + HEADER.read_bytes()).hexdigest()[:20]
    exe = folder / (digest + (".exe" if os.name == "nt" else ""))
    if not exe.exists():
        zig = Path("D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe")
        if zig.exists():
            compiler = [str(zig), "c++"]
        elif shutil.which("g++"):
            compiler = ["g++"]
        else:
            pytest.skip("C++17 compiler unavailable")
        subprocess.run(compiler + ["-O3", "-std=c++17", "-pthread", str(SOURCE), "-o", str(exe)],
                       check=True, capture_output=True, text=True, timeout=60)
    run = subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=30)
    parsed = json.loads(run.stdout)
    (folder / "latest-result.json").write_text(json.dumps(parsed, indent=2) + "\n")
    return parsed


def test_32_contenders_preserve_protected_state_and_all_finish(result):
    assert result["ok"] and result["threads"] == 32
    assert result["updates"] == 64000 and result["all_workers_finished"]
    if os.name == "nt" or os.sys.platform.startswith("linux"):
        assert result["affinity_limited_to_at_most_two_cpus"]


def test_exception_unwinding_releases_lock_under_contention(result):
    assert result["exceptions"] == 32 * 118


def test_descheduled_holder_excludes_waiters_and_they_resume(result):
    assert result["early_entries"] == 0
    assert result["slow_holder_waiters"] == 32


def test_array_elements_are_cache_line_aligned(result):
    assert result["lock_bytes"] == result["alignment"] == 64
