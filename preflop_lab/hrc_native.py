"""Build/run/read the independent native v4 research kernel.

The .hrcz importer consumes topology and settings only. Native storage starts at
zero; original nodedata and terminal utility vectors are never training inputs.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import threading
import time
from typing import Callable
from .hrc_benchmarks import MAX_SAMPLES

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "analysis/hrc-native/build"
SOURCE = ROOT / "native/hrc_research_solver.cpp"
CARDS = ROOT / "native/hrc_cards.hpp"
EQUITY = ROOT / "native/hrc_equity.hpp"
MTT = ROOT / "native/hrc_mtt.hpp"
POLICY = ROOT / "native/hrc_policy.hpp"
CI = ROOT / "native/hrc_ci.hpp"
FGS = ROOT / "native/hrc_fgs.hpp"
SETTLEMENT = ROOT / "native/hrc_settlement.hpp"
CHANCE = ROOT / "native/hrc_chance.hpp"
DYNAMIC = ROOT / "native/hrc_dynamic.hpp"
DIGEST = ROOT / "native/hrc_digest.hpp"
PARALLEL = ROOT / "native/hrc_parallel.hpp"
SCOPE = ROOT / "native/hrc_scope.hpp"
TERMINAL_TABLE = ROOT / "native/hrc_terminal_table.hpp"
NODE_MUTEX = ROOT / "native/hrc_node_mutex.hpp"
UNLOCKED_READ = ROOT / "native/hrc_unlocked_read.hpp"
FLAT_BOARD_MAP = ROOT / "native/hrc_flat_board_map.hpp"
_build_lock = threading.Lock()


# Measured flags retain the existing floating-point evaluation rules.
_NATIVE_ZIG_FLAGS = ("-O3", "-std=c++17", "-ffp-contract=off", "-flto=thin")
_NATIVE_MSVC_FLAGS = ("/nologo", "/O2", "/EHsc", "/std:c++17", "/fp:precise", "/DNDEBUG")


def _native_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _native_json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _native_write_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _native_freeze_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
        try:
            # Publish complete contents without replacing a sibling build's
            # snapshot. All snapshots and temporary files share a filesystem.
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise RuntimeError("Immutable native build input changed: " + str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _native_global_record(record: dict) -> dict:
    """Preserve only a separately verified, still-identical live-service alias.

    This never creates/publishes an alias or edits the canonical identity record.
    A parent-controlled publication must first install the alias and provenance.
    """
    canonical = dict(record)
    try:
        previous = json.loads((BUILD / "build.json").read_text(encoding="utf-8"))
        alias = previous.get("live_legacy_alias")
        if not isinstance(alias, dict) or alias.get("schema") != "hrc-live-legacy-alias-v1":
            return canonical
        legacy = alias.get("observed_legacy_source_sha256")
        if (not isinstance(legacy, str) or len(legacy) != 64
                or any(c not in "0123456789abcdef" for c in legacy)):
            return canonical
        if not isinstance(alias.get("publication_id"), str) or not alias["publication_id"]:
            return canonical
        if previous.get("source_sha256") != legacy:
            return canonical
        if (previous.get("build_identity") != record["build_identity"]
                or alias.get("build_identity") != record["build_identity"]
                or alias.get("source_files") != record["identity_spec"]["source_files"]
                or alias.get("canonical_executable_sha256") != record["executable_sha256"]
                or alias.get("alias_executable_sha256") != record["executable_sha256"]):
            return canonical
        if previous.get("canonical_legacy_source_sha256", record["source_sha256"]) != record["source_sha256"]:
            return canonical
        expected = BUILD.absolute() / ("hrc_research_solver-" + legacy[:20] + ".exe")
        # Require the exact legacy-cache location, not an arbitrary same-hash file.
        if Path(alias.get("alias_executable_path", "")).absolute() != expected:
            return canonical
        if (not expected.is_file() or _native_sha(expected) != record["executable_sha256"]
                or _native_sha(Path(record["executable_path"])) != record["executable_sha256"]):
            return canonical
        canonical["canonical_legacy_source_sha256"] = record["source_sha256"]
        canonical["source_sha256"] = legacy
        canonical["source_sha256_semantics"] = "observed_live_legacy_alias_key"
        canonical["live_legacy_alias"] = alias
        # executable_path stays the canonical identity artifact; legacy build()
        # derives its alias filename and does not read this field.
        return canonical
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Incomplete or mismatched compatibility evidence must never poison the
        # canonical cache. Do not alter, replace or remove the old alias itself.
        return dict(record)


def _native_toolchain() -> dict:
    for zig in (Path(r"D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe"),
                Path(r"D:\Tools\REA-Research\zig-x86_64-windows-0.15.2\zig.exe")):
        if zig.is_file():
            return {"kind": "zig", "path": str(zig.resolve()), "sha256": _native_sha(zig),
                    "version": subprocess.check_output([str(zig), "version"], text=True).strip(),
                    "compiler_version": subprocess.check_output([str(zig), "c++", "--version"], text=True).strip()}
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    install = None
    if vswhere.is_file():
        found = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
        if found:
            install = Path(found.splitlines()[0])
    if install is None:
        candidate = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools")
        if candidate.is_dir():
            install = candidate
    if install is None:
        raise RuntimeError("MSVC C++ BuildTools was not found; native kernel cannot be built.")
    version_file = install / "VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt"
    tool_version = version_file.read_text(encoding="utf-8-sig").strip()
    compiler = install / "VC/Tools/MSVC" / tool_version / "bin/Hostx64/x64/cl.exe"
    linker = compiler.with_name("link.exe")
    env_script = install / "Common7/Tools/VsDevCmd.bat"
    version = subprocess.run([str(compiler), "/Bv"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    return {"kind": "msvc", "path": str(compiler.resolve()), "sha256": _native_sha(compiler),
            "version": version.stdout + version.stderr, "tool_version": tool_version,
            "linker_sha256": _native_sha(linker), "compiler_install": str(install),
            "environment_script": str(env_script), "environment_script_sha256": _native_sha(env_script)}


def build(*, profile: Path | None = None) -> Path:
    """Compile immutable source/toolchain/flag identities, without installation."""
    with _build_lock:
        # This compatibility digest is NOT the actual build/cache identity.
        # Keep its exact historical order for explicitly audited legacy clients.
        legacy_paths = (SOURCE, CARDS, EQUITY, MTT, POLICY, CI, FGS, SETTLEMENT, CHANCE,
                        DYNAMIC, DIGEST, PARALLEL, SCOPE, TERMINAL_TABLE, NODE_MUTEX,
                        UNLOCKED_READ, FLAT_BOARD_MAP)
        # Include every named native source/header, including newly added headers
        # that an old manually maintained tuple may omit.
        paths = sorted(p for p in SOURCE.parent.rglob("*") if p.is_file() and p.suffix in (".cpp", ".hpp", ".h"))
        payloads = {p.relative_to(SOURCE.parent).as_posix(): p.read_bytes() for p in paths}
        source_files = {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                        for name, data in payloads.items()}
        source_set = hashlib.sha256(_native_json_bytes(source_files)).hexdigest()
        legacy_digest = hashlib.sha256(b"".join(payloads[p.name] for p in legacy_paths)).hexdigest()
        compiler = _native_toolchain()
        flags = list(_NATIVE_ZIG_FLAGS if compiler["kind"] == "zig" else _NATIVE_MSVC_FLAGS)
        snapshot = BUILD / "sources" / source_set
        profile_info, profile_data = None, None
        if profile is not None:
            if compiler["kind"] != "zig":
                raise ValueError("This profile-use adapter only supports the Zig/Clang compiler")
            profile = Path(profile).resolve()
            profile_data = profile.read_bytes()
            profile_hash = hashlib.sha256(profile_data).hexdigest()
            profile_copy = BUILD / "profiles" / (profile_hash + ".profdata")
            profile_info = {"path": str(profile), "sha256": profile_hash, "bytes": len(profile_data),
                            "frozen_path": str(profile_copy.resolve())}
            flags.append("-fprofile-use=" + str(profile_copy.resolve()))
        spec = {"schema": "native-build-identity-v2", "source_files": source_files,
                "source_set_sha256": source_set, "compiler": compiler, "ordered_flags": flags,
                "profile": profile_info, "translation_unit": str((snapshot / SOURCE.name).resolve()),
                "working_directory": str(BUILD.resolve()), "host_cpu": os.environ.get("PROCESSOR_IDENTIFIER"),
                "environment": {key: os.environ.get(key) for key in ("ZIG_LIB_DIR", "CPATH", "CPLUS_INCLUDE_PATH",
                    "LIBRARY_PATH", "INCLUDE", "LIB", "LIBPATH", "CL", "_CL_")}}
        identity = hashlib.sha256(_native_json_bytes(spec)).hexdigest()
        folder = BUILD / "identities" / identity
        exe, stamp = folder / "solver.exe", folder / "build.json"
        if exe.is_file() and stamp.is_file():
            record = json.loads(stamp.read_text(encoding="utf-8"))
            if (record.get("build_identity") == identity and record.get("identity_spec") == spec
                    and record.get("executable_sha256") == _native_sha(exe)):
                _native_write_json(BUILD / "build.json", _native_global_record(record))
                return exe
        if exe.exists():
            raise RuntimeError("Refusing to overwrite an existing native artifact with an invalid identity: " + str(exe))
        folder.mkdir(parents=True, exist_ok=True)
        lock_path = folder / "compile.lock"
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("Native build identity is already compiling; retry after it finishes: " + identity) from exc
        try:
            os.close(lock_fd)
            snapshot.mkdir(parents=True, exist_ok=True)
            for name, data in payloads.items():
                _native_freeze_file(snapshot / name, data)
            if profile_info:
                _native_freeze_file(profile_copy, profile_data)
            pending = folder / "solver.pending.exe"
            if compiler["kind"] == "zig":
                command = [compiler["path"], "c++", *flags, str(snapshot / SOURCE.name), "-o", str(pending)]
            else:
                # Preserve the existing MSVC fallback, but pin the audited exact
                # compiler and VCTools version rather than whatever PATH finds.
                batch = folder / "build.cmd"
                batch.write_text('@echo off\ncall "' + compiler["environment_script"] + '" -arch=x64 -host_arch=x64 -vcvars_ver=' + compiler["tool_version"] + ' >nul\n'
                    'if errorlevel 1 exit /b %errorlevel%\n"' + compiler["path"] + '" ' + ' '.join(flags) +
                    ' "' + str(snapshot / SOURCE.name) + '" /Fe:"' + str(pending) + '" /Fo:"' + str(folder / "solver.obj") + '"\n'
                    'exit /b %errorlevel%\n', encoding="utf-8")
                command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(batch)]
            result = subprocess.run(command, cwd=BUILD, capture_output=True, text=True, encoding="utf-8", errors="replace")
            (folder / "build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            if result.returncode:
                raise RuntimeError("Native compilation failed: " + (result.stdout + result.stderr)[-6000:])
            # Windows rename does not replace an existing destination. The lock
            # prevents concurrent builds of the same identity in other processes.
            pending.rename(exe)
            record = {"source_sha256": legacy_digest, "source_sha256_semantics": "legacy_ordered_concatenation_only",
                      "legacy_source_files": [p.name for p in legacy_paths], "source_set_sha256": source_set,
                      "build_identity": identity, "identity_spec": spec, "compiler": compiler["path"],
                      "ordered_flags": flags, "command": command, "executable_path": str(exe),
                      "executable_sha256": _native_sha(exe)}
            _native_write_json(stamp, record)
            _native_write_json(BUILD / "build.json", _native_global_record(record))
            return exe
        finally:
            lock_path.unlink()


def _compact_tree(tree_path):
    if isinstance(tree_path, dict):
        return tree_path
    if hasattr(tree_path, "compact_export"):
        return tree_path.compact_export()
    path = Path(tree_path)
    if path.suffix.lower() == ".hrcz":
        from .hrc_tree import load_hrc_tree
        return load_hrc_tree(path).compact_export()
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _chance_bytes(compact):
    """Validate and encode the portable fixed-board mode1 extension."""
    chance, dynamic = compact.get('chance'), compact.get('dynamic')
    if chance is None and dynamic is None:
        return b''
    if not isinstance(chance, dict) or chance.get('version') != 1 or chance.get('mode') != 1:
        raise ValueError('Only chance version1 mode1 is supported')
    if not isinstance(dynamic, dict) or dynamic.get('version') != 1 or not isinstance(dynamic.get('tables'), list):
        raise ValueError('Chance requires dynamic version1 tables')
    history = chance.get('board_history')
    if not isinstance(history, list) or not 2 <= len(history) <= 4 or history[0] != 0:
        raise ValueError('Chance requires cumulative fixed flop/turn/river history')
    for i, board in enumerate(history):
        if type(board) is not int or not 0 <= board < 2**52 or (i and (board.bit_count() != i+2 or board & history[i-1] != history[i-1])):
            raise ValueError('Invalid cumulative chance board history')
    attempts, calls = chance.get('max_attempts', 1_000_000), chance.get('max_random_calls', 10_000_000)
    if any(type(v) is not int or not 1 <= v <= 1_000_000_000 for v in (attempts, calls)):
        raise ValueError('Chance budgets must be integers in [1,1000000000]')
    ranges = chance.get('ranges')
    players = compact['players']
    if not isinstance(ranges, list) or len(ranges) != players:
        raise ValueError('Chance ranges must include every dealt seat')
    data = bytearray(struct.pack('<IIQQ', 1, len(history), attempts, calls))
    data.extend(struct.pack(f'<{len(history)}Q', *history))
    for row in ranges:
        if row is None:
            data.extend(struct.pack('<I', 0)); continue
        if not isinstance(row, list) or len(row) != 1326 or any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 for v in row):
            raise ValueError('Each chance range must be null or 1326 finite nonnegative weights')
        # Keep the original left-to-right summation order after board blockers.
        mass = 0.0
        for hi in range(1,52):
            for lo in range(hi):
                if not history[-1] & ((1 << hi) | (1 << lo)):
                    mass += row[hi*(hi-1)//2+lo]
        if not math.isfinite(mass) or mass <= 0:
            raise ValueError('Chance range has no positive finite mass after board blockers')
        data.extend(struct.pack('<I1326d', 1326, *row))
    tables = dynamic['tables']
    if len(tables) > 3:
        raise ValueError('At most three dynamic street tables are allowed')
    by_street = {}
    data.extend(struct.pack('<I', len(tables)))
    for table in tables:
        if not isinstance(table, dict):
            raise ValueError('Invalid dynamic resource descriptor')
        street, file, digest, size = (table.get(k) for k in ('street','file','sha256','bytes'))
        effective = table.get('effective_counts')
        if type(street) is not int or street not in (1,2,3) or street in by_street:
            raise ValueError('Invalid or duplicate dynamic street')
        if not isinstance(file,str) or not file or file in ('.','..') or len(file)>255 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for c in file):
            raise ValueError('Dynamic file must be a relative single ASCII filename')
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid dynamic SHA-256')
        if type(size) is not int or not 28 <= size <= 2**32:
            raise ValueError('Invalid dynamic resource byte length')
        if not isinstance(effective,list) or len(effective)!=players or any(type(v) is not int or not 0 <= v <= 2**31-1 for v in effective):
            raise ValueError('Invalid dynamic effective bucket counts')
        by_street[street] = table
        data.extend(struct.pack('<I', street))
        for text in (file,digest):
            encoded=text.encode('ascii'); data.extend(struct.pack('<I',len(encoded))); data.extend(encoded)
        data.extend(struct.pack(f'<Q{players}I',size,*effective))
    root = compact['nodes'][compact['root']]
    if root['children'] and root['street'] != len(history)-1:
        raise ValueError('Chance fixed-board street must equal the subtree root street')
    for node in compact['nodes']:
        if not node['children']: continue
        table = by_street.get(node['street'])
        if table is None:
            raise ValueError('Missing dynamic table for decision street')
        actor = node['actor']
        if type(actor) is not int or not 0 <= actor < players or node['buckets'] != table['effective_counts'][actor] or node['buckets'] < 1:
            raise ValueError('Decision buckets must equal actor-specific positive effective count')
    return bytes(data)


def _verify_dynamic_resources(compact, resource_dir):
    """Verify each provided resource, including unused descriptors, by streaming."""
    for table in compact.get('dynamic', {}).get('tables', []):
        path = Path(resource_dir) / table['file']
        if not path.is_file() or path.stat().st_size != table['bytes']:
            raise ValueError('Dynamic resource size mismatch: ' + table['file'])
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest() != table['sha256']:
                raise ValueError('Dynamic resource SHA-256 mismatch: ' + table['file'])


def prepare(tree_path, output_dir) -> dict:
    """Export fresh topology/state input as a compact little-endian binary."""
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compact = _compact_tree(tree_path)
    nodes, terms = compact["nodes"], compact["terminals"]
    players = compact["players"]
    if not 2 <= players <= 10 or compact["big_blind"] <= 0:
        raise ValueError("Unsupported players/blinds")
    if [n["id"] for n in nodes] != list(range(len(nodes))):
        raise ValueError("Nodes must be in ID order")
    chance_bytes = _chance_bytes(compact)
    imported_float32 = compact.get('import_provenance', {}).get('format') == 'hrcz'
    serial = json.dumps(compact, sort_keys=True, separators=(",", ":")).encode()
    identity = int.from_bytes(hashlib.sha256(serial).digest()[:8], "little")
    children = []
    node_bytes = bytearray()
    incoming = [0]*len(nodes)
    for n in nodes:
        if n['children'] and (type(n['buckets']) is not int or not 1 <= n['buckets'] <= (2**31-1 if chance_bytes else 16384)):
            raise ValueError('Decision bucket count exceeds supported domain')
        first = len(children)
        children.extend(n["children"])
        for child in n["children"]:
            if type(child) is not int or not 0 <= child < len(nodes):
                raise ValueError("Invalid child ID")
            incoming[child] += 1
        special = n.get("special", 0)
        if "special" not in n and len(n["actions"]) > 1 and n["actions"][1] == 1:
            special = 2 if nodes[n["children"][1]]["children"] else 1
        node_bytes.extend(struct.pack("<7i", n["actor"], n["street"], n["buckets"], first,
                                      len(n["children"]), special, n["terminal_id"]))
    if any(v != (0 if i == compact["root"] else 1) for i, v in enumerate(incoming)):
        raise ValueError("Input must be a rooted tree with one parent per nonroot node")
    seen = set()
    stack = [(compact["root"], 0)]
    while stack:
        node, depth = stack.pop()
        if node in seen or depth > 256:
            raise ValueError("Cycle or excessive tree depth")
        seen.add(node)
        stack.extend((child, depth+1) for child in nodes[node]["children"])
    if len(seen) != len(nodes):
        raise ValueError("Disconnected tree")
    stores=compact.get('stores')
    formats=[23,25,25,25]
    if stores is not None:
        if not isinstance(stores,dict) or stores.get('version')!=1 or not isinstance(stores.get('street_formats'),list):
            raise ValueError('stores must contain version:1 and street_formats')
        formats=stores['street_formats']
        if len(formats)!=4 or formats[0]!=23 or any(type(f) is not int or f not in (25,27,31) for f in formats[1:]):
            raise ValueError('Expected street formats [23,25|27|31,25|27|31,25|27|31]')
    policy_bytes = bytearray()
    policies = compact.get('policies')
    if policies is not None:
        from .hrc_policy import BucketLocks, FrequencyStore
        if not isinstance(policies, dict) or policies.get('version') != 1 or not isinstance(policies.get('nodes'), list):
            raise ValueError('policies must have version 1 and a nodes list')
        entries = policies['nodes']
        policy_bytes.extend(struct.pack('<I', len(entries)))
        policy_ids = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Policy node must be a dictionary')
            node_id = entry.get('node_id')
            if type(node_id) is not int or not 0 <= node_id < len(nodes) or node_id in policy_ids:
                raise ValueError('Invalid or duplicate policy node ID')
            policy_ids.add(node_id)
            node = nodes[node_id]
            k, h = len(node['children']), node['buckets']
            if k < 2 or ('locks' in entry) == ('frequency' in entry):
                raise ValueError('Policy requires decision node and exactly one of locks/frequency')
            if 'locks' in entry:
                if formats[node['street']]==25:
                    raise ValueError('Bucket locks require format23/27/31 storage')
                locks = BucketLocks(k, h, entry['locks'])
                special = node.get('special', 0) or (len(node['actions']) > 1 and node['actions'][1] == 1)
                if special and locks.rows[0] is not None:
                    raise ValueError('Cannot lock the special virtual fold action')
                lock_tolerance = k*2**-23 if imported_float32 else 1e-12
                if locks.count == k and any(abs(sum(r[b] for r in locks.rows)-1)>lock_tolerance for b in range(h)):
                    raise ValueError('Fully locked distributions must sum to one')
                policy_bytes.extend(struct.pack('<II', node_id, 1))
                for row in locks.rows:
                    policy_bytes.extend(struct.pack('<I', int(row is not None)))
                    if row is not None:
                        policy_bytes.extend(struct.pack(f'<{h}d', *row))
            else:
                frequency = entry['frequency']
                if not isinstance(frequency, dict):
                    raise ValueError('frequency must be a dictionary')
                # Only target/edge validation is needed here; storage is native.
                if imported_float32:
                    targets=frequency.get('targets',[None]*k)
                    if not isinstance(targets,list) or len(targets)!=k or any(t is not None and (type(t) not in (int,float) or not math.isfinite(t) or not 0<=t<=1) for t in targets) or sum(t for t in targets if t is not None)>1+k*2**-23:
                        raise ValueError('Invalid float32 imported frequency targets')
                    store=FrequencyStore(1,k,None,frequency.get('edges'))
                    store.targets=[math.nan if t is None else t for t in targets]
                else:
                    store = FrequencyStore(1, k, frequency.get('targets'), frequency.get('edges'))
                policy_bytes.extend(struct.pack('<II', node_id, 2))
                policy_bytes.extend(struct.pack(f'<{2*k}d', *store.targets, *store.edges))
    ci = compact.get('ci')
    if ci is not None and (not isinstance(ci, dict) or type(ci.get('enabled')) is not bool):
        raise ValueError('ci must have boolean enabled')
    ci_enabled = bool(ci and ci['enabled'])
    equity = compact.get('equity')
    rake=compact.get('rake')
    rake_bytes=b''
    if rake is not None:
        if equity is not None or compact.get('fgs') is not None:
            raise ValueError('Rake supports chip equity only')
        if not isinstance(rake,dict) or rake.get('mode') not in ('nfnd','gg','full'):
            raise ValueError('Unsupported rake mode')
        fraction,cap=rake.get('fraction'),rake.get('cap')
        if isinstance(fraction,bool) or not isinstance(fraction,(int,float)) or not math.isfinite(fraction) or not 0<=fraction<=1:
            raise ValueError('Rake fraction must be finite in [0,1]')
        if type(cap) is not int or not 0<=cap<=10**15:
            raise ValueError('Rake cap must be integer internal chips in [0,1e15]')
        for term in terms:
            if type(term.get('street')) is not int or not 0<=term['street']<=3 or type(term.get('raise_count')) is not int or not 0<=term['raise_count']<=2**31-1:
                raise ValueError('Rake requires explicit terminal street and raise_count')
        rake_bytes=struct.pack('<Idq',('nfnd','gg','full').index(rake['mode'])+1,fraction,cap)
    dead_money = any(t.get('dead_money', 0) != 0 for t in terms)
    equity_bytes = b''
    if equity is not None:
        if not isinstance(equity, dict) or equity.get('mode') not in ('icm', 'mtt_icm'):
            raise ValueError('Unsupported tournament equity model')
        bounty = equity.get('bounty', {})
        if not isinstance(bounty, dict) or bounty.get('mode', 'none') not in ('none', 'ko', 'pko'):
            raise ValueError('Unsupported bounty model')
        prizes, other = equity['payouts'], equity.get('other_stacks', [])
        amounts = bounty.get('amounts', [0] * players)
        other_amounts = bounty.get('other_amounts', [0] * len(other))
        if len(amounts) != players or len(other_amounts) != len(other) or len(other) > 10000:
            raise ValueError('Tournament bounty/field dimensions do not match')
        if not 1 <= len(prizes) <= players + len(other):
            raise ValueError('Tournament payout dimensions do not match')
        kind = ('none', 'ko', 'pko').index(bounty.get('mode', 'none'))
        equity_bytes = struct.pack('<IIId', 1 if equity['mode'] == 'icm' else 2, kind, len(prizes),
                                   bounty.get('immediate_fraction', .5 if kind == 2 else 1))
        equity_bytes += struct.pack(f'<{len(prizes)}dI', *prizes, len(other))
        equity_bytes += struct.pack(f'<{len(other)}d', *other)
        equity_bytes += struct.pack(f'<{players}d', *amounts)
        equity_bytes += struct.pack(f'<{len(other)}d', *other_amounts)
    fgs_bytes = b''
    fgs = compact.get('fgs')
    if fgs is not None:
        if equity is None or equity['mode'] != 'icm' or equity.get('other_stacks'):
            raise ValueError('FGS requires local ICM')
        if 'chance_cache' in fgs:
            raise ValueError('FGS cache path is not portable; use resource_dir/fgs-chance-v1.bin')
        ante_type = ('Regular', 'BBAnteFirst', 'BBBlindFirst').index(fgs['ante_type'])
        straddle = ('Off', 'Single', 'Double', 'Button').index(fgs['straddle'])
        fgs_bytes = struct.pack('<3q3I3i3q4QdI', fgs['big_blind'], fgs['small_blind'], fgs['ante'],
                                ante_type, straddle, int(fgs['moving_button']), fgs['depth'], fgs['depth3way'], fgs['next_level_at'],
                                *fgs['next_level'], fgs['cache_capacity'], fgs['terminal_cache_capacity'], fgs['max_states'], fgs['max_sweeps'],
                                fgs['max_seconds'], int(fgs['skip_sb']))
    features = policies is not None or ci_enabled or fgs is not None or stores is not None or rake is not None or bool(chance_bytes) or imported_float32
    flags = int(equity is not None) | (2 if dead_money else 0) | (4 if policies is not None else 0) | (8 if ci_enabled else 0) | (16 if fgs is not None else 0) | (32 if stores is not None else 0) | (64 if rake is not None else 0) | (128 if chance_bytes else 0) | (256 if imported_float32 else 0)
    binary = output / "tree.bin"
    with binary.open("wb") as f:
        f.write(b"HRTREE04" if features else b"HRTREE03" if dead_money else b"HRTREE02" if equity is not None else b"HRTREE01")
        f.write(struct.pack("<5IQd", players, compact["root"], len(nodes), len(children), len(terms),
                            identity, float(compact["big_blind"])))
        f.write(struct.pack(f"<{players}d", *compact["initial_stacks"]))
        if dead_money or features:
            f.write(struct.pack('<I', flags))
        if stores is not None:
            f.write(struct.pack('<4I',*formats))
        f.write(node_bytes)
        f.write(struct.pack(f"<{len(children)}i", *children))
        for t in terms:
            f.write(struct.pack(f"<{players}d", *t["remaining"]))
            f.write(struct.pack(f"<{players}d", *t["contributions"]))
            folded = sum(1 << p for p, value in enumerate(t["folded"]) if value)
            f.write(struct.pack("<I", folded))
            if dead_money:
                f.write(struct.pack('<d', t.get('dead_money', 0)))
            if rake is not None:
                f.write(struct.pack('<ii',t['street'],t['raise_count']))
        f.write(equity_bytes)
        f.write(policy_bytes)
        f.write(fgs_bytes)
        f.write(rake_bytes)
        f.write(chance_bytes)
    manifest = {"schema": "independent-native-input-v1", "tree_sha256": hashlib.sha256(serial).hexdigest(),
                "tree_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "players": players, "nodes": len(nodes), "terminal_nodes": len(terms),
                "decision_nodes": len(nodes)-len(terms), "big_blind_internal": compact["big_blind"],
                "fresh_zero_storage": not bool(compact.get('import_provenance')), "original_strategy_read": bool(compact.get('import_provenance')), "original_leaf_values_read": False,
                "topology_source": compact.get("provenance", {}), "tree_validation": compact.get("validation", {}),
                "rng": "independent xoshiro256** with SplitMix64 seed and rejection-bounded integers; not Java RNG stream equivalence",
                "numeric_scope": "Audited v4 operations, single-thread; not original concurrency/snapshot schedule equivalence"}
    manifest['utility'] = 'net_payout' if equity is not None else 'net_bb'
    if equity is not None:
        manifest.update(schema='independent-native-input-v2', equity=equity)
    if dead_money:
        manifest.update(schema='independent-native-input-v3', dead_money=True)
    if features:
        manifest.update(schema='independent-native-input-v4', policies=policies, track_ci=ci_enabled, fgs=fgs, stores=stores, rake=rake)
    if chance_bytes:
        manifest.update(chance=compact['chance'], dynamic=compact['dynamic'])
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / 'tree.json').write_bytes(serial)
    return {"tree_binary": str(binary), "manifest_path": str(manifest_path), "manifest": manifest, "compact": compact}


def run(tree_path, resource_dir, samples: int, seed: int, output_dir,
        progress_callback: Callable | None = None, cancel_check: Callable | None = None,
        *, resume_from=None, mode="v4", reset_regret=False, reset_average=False,
        stop_after_seconds=None, target_ci=None, hard_seconds=None, checkpoint_migration="reject",
        max_memory_bytes=1 << 30, threads=1, constant_scalar_shortcuts=True,
        track_ci=None, sampling_scope='entire_tree', sampling_path=None,
        stopping_mode=None, sampling_stage='calculation', allow_algorithm_change=False,
        root_mean_valid=None) -> dict:
    from .hrc_sampling import validated_sampling, sampling_selection, preserve_ci_identity, write_scope_descriptor, algorithm_resume
    controls = {'sampling_scope': sampling_scope, 'sampling_path': [] if sampling_path is None else sampling_path,
                'sampling_stage': sampling_stage}
    if stopping_mode is not None:
        controls.update(stopping_mode=stopping_mode)
        if target_ci is not None:controls['target_ci']=target_ci
        if stop_after_seconds is not None:controls['stop_after_seconds']=stop_after_seconds
    selected = validated_sampling(controls)
    if stopping_mode == 'ci':
        track_ci=True;target_ci=selected['target_ci']
    if track_ci is not None and type(track_ci) is not bool:
        raise ValueError('track_ci must be a boolean or None')
    if type(allow_algorithm_change) is not bool:
        raise ValueError('allow_algorithm_change must be a boolean')
    if root_mean_valid is not None and type(root_mean_valid) is not bool:
        raise ValueError('root_mean_valid must be a boolean or None')
    if resume_from:
        source_index = Path(resume_from).resolve().parent / 'index.json'
        if source_index.is_file():
            source_valid = json.loads(source_index.read_text(encoding='utf-8')).get('root_mean_valid', True)
            if type(source_valid) is not bool:
                raise ValueError('Source checkpoint root_mean_valid must be a boolean')
            root_mean_valid = source_valid if root_mean_valid is None else root_mean_valid and source_valid
    if sampling_scope == 'selected_subtree':
        root_mean_valid = False
    if type(samples) is not int or not 0 <= samples <= MAX_SAMPLES:
        raise ValueError(f"samples must be an integer between 0 and {MAX_SAMPLES:,}")
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("seed must be uint64")
    if type(threads) is not int or not 1<=threads<=32:
        raise ValueError('threads must be an integer in [1,32]')
    if type(constant_scalar_shortcuts) is not bool:
        raise ValueError('constant_scalar_shortcuts must be a boolean')
    if type(max_memory_bytes) is not int or not (1 << 20) <= max_memory_bytes <= (8 << 30):
        raise ValueError('max_memory_bytes must be an integer in [1MiB,8GiB]')
    if mode not in ("v3", "v4"):
        raise ValueError("mode must be v3 or v4")
    if type(reset_regret) is not bool or type(reset_average) is not bool:
        raise ValueError('reset flags must be booleans')
    # The formal HRC dialog's full reset clears both EV/regret and strategy
    # accumulators. Legacy callers retain the two independent native flags.
    if stopping_mode is not None and sampling_stage == 'calculation' and reset_regret:
        reset_average = True
    for value in (stop_after_seconds, hard_seconds):
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not .1<=value<=86400):
            raise ValueError('Seconds targets must be finite in [0.1,86400]')
    if target_ci is not None and (type(target_ci) not in (int,float) or not math.isfinite(target_ci) or target_ci<=0):
        raise ValueError('target_ci must be finite and positive')
    if checkpoint_migration not in ('reject','preserve','reset'):
        raise ValueError('checkpoint_migration must be reject, preserve or reset')
    if checkpoint_migration!='reject' and not resume_from:
        raise ValueError('Checkpoint migration requires resume_from')
    output = Path(output_dir).resolve()
    compact = _compact_tree(tree_path)
    selection = sampling_selection(compact, sampling_scope, sampling_path)
    if track_ci is not None and resume_from:
        compact=preserve_ci_identity(compact,resume_from)
    tree_path=compact
    if checkpoint_migration!='reject' and Path(resume_from).resolve().parent==output:
        raise ValueError('Checkpoint migration requires a new output directory')
    if resume_from and Path(resume_from).resolve().parent==output:
        # Validate before prepare rewrites metadata beside an existing result.
        compact=_compact_tree(tree_path)
        encoded=json.dumps(compact,sort_keys=True,separators=(',',':')).encode()
        with Path(resume_from).open('rb') as source:
            header=source.read(36)
        expected=int.from_bytes(hashlib.sha256(encoded).digest()[:8],'little')
        if len(header)!=36 or header[:8] not in (b'HRSOLV01',b'HRSOLV02',b'HRSOLV03') or struct.unpack_from('<Q',header,8)[0]!=expected or struct.unpack_from('<I',header,32)[0]!=int(mode=='v4'):
            raise ValueError('In-place resume requires matching tree identity and solver mode; source metadata was preserved')
        tree_path=compact
    prepared = prepare(tree_path, output)
    migration=None
    resume_input=resume_from
    if checkpoint_migration!='reject':
        from .hrc_checkpoint import migrate_checkpoint
        resume_input,migration=migrate_checkpoint(resume_from,prepared['compact'],output,checkpoint_migration,mode)
    if target_ci is not None and not (track_ci if track_ci is not None else prepared['manifest'].get('track_ci')):
        raise ValueError('target_ci requires explicit ci.enabled=true')
    scope_file, selection = write_scope_descriptor(prepared['compact'], output, sampling_scope, sampling_path)
    algorithm_change=None
    if resume_input:
        resume_input, algorithm_change=algorithm_resume(resume_input, output, mode, allow_algorithm_change)
    _verify_dynamic_resources(prepared['compact'], resource_dir)
    if prepared['compact'].get('fgs'):
        cache = Path(resource_dir) / 'fgs-chance-v1.bin'
        spec = prepared['compact']['fgs']
        if not cache.is_file() or spec.get('chance_bytes', cache.stat().st_size) != cache.stat().st_size:
            raise ValueError('Missing or invalid FGS chance resource')
        if spec.get('chance_sha256'):
            with cache.open('rb') as file:
                if hashlib.file_digest(file, 'sha256').hexdigest() != spec['chance_sha256']:
                    raise ValueError('FGS chance resource digest mismatch')
    exe = build()
    cancellation = output / "cancel.request"
    cancellation.unlink(missing_ok=True)
    command = [str(exe), prepared["tree_binary"], str(Path(resource_dir).resolve()), str(samples), str(seed), str(output), mode]
    if samples > 1_000_000_000 or scope_file or track_ci is not None or root_mean_valid is not None or not constant_scalar_shortcuts or threads!=1 or resume_from or reset_regret or reset_average or max_memory_bytes != 1 << 30 or any(v is not None for v in (stop_after_seconds,target_ci,hard_seconds)):
        command.extend([str(Path(resume_input).resolve()) if resume_input else '-', str(int(reset_regret)), str(int(reset_average))])
        command.extend([str(-1 if v is None else v) for v in (stop_after_seconds,target_ci,hard_seconds)])
        command.append(str(max_memory_bytes))
        command.append(str(threads))
        command.append(str(int(constant_scalar_shortcuts)))
        command.append(str(scope_file) if scope_file else '-')
        command.append(str(-1 if track_ci is None else int(track_ci)))
        command.append(str(-1 if root_mean_valid is None else int(root_mean_valid)))
        if samples > 1_000_000_000:
            command.append(str(samples))  # Explicit bounded cumulative mode; native uint64 counters.
    events = queue.Queue()
    errors = []
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", bufsize=1)
    def read_stdout():
        for line in process.stdout:
            events.put(line)
        events.put(None)
    def read_stderr():
        errors.append(process.stderr.read())
    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start(); stderr_thread.start()
    logs = []
    requested_cancel = False
    while True:
        if not requested_cancel and cancel_check and cancel_check():
            cancellation.write_text("cancel\n", encoding="ascii")
            requested_cancel = True
        try:
            line = events.get(timeout=.1)
        except queue.Empty:
            continue
        if line is None:
            break
        row = json.loads(line)
        logs.append(row)
        if progress_callback:
            progress_callback(row)
    code = process.wait()
    stdout_thread.join(); stderr_thread.join()
    (output / "progress.jsonl").write_text("\n".join(json.dumps(r) for r in logs) + "\n", encoding="utf-8")
    (output / "stderr.txt").write_text("".join(errors), encoding="utf-8")
    if code:
        failure = {'kind': 'failed', 'resource_limit': any(r.get('resource_limit') for r in logs),
                   'error': ''.join(errors)[-6000:], 'checkpoint_path': str(output / 'checkpoint.bin') if (output / 'checkpoint.bin').exists() else None}
        (output / 'failure.json').write_text(json.dumps(failure, indent=2), encoding='utf-8')
        raise RuntimeError(f"Native solver exited {code}: {''.join(errors)[-6000:]}")
    last = logs[-1]
    if last.get("kind") != "finished":
        raise RuntimeError("Native solver produced no completion record")
    summary = {**last, "fresh_zero_origin": not bool(prepared['compact'].get('import_provenance')), "resumed": bool(resume_from), "seed": seed,
               "mode": mode, "native": True, "original_solver_called": False,
               "utility": prepared['manifest']['utility'], "checkpoint_path": str(output / "checkpoint.bin"),
               "index_path": str(output / "index.json")}
    summary.update(reset_regret=reset_regret, reset_average=reset_average,
                   ci_restarted=bool(track_ci if track_ci is not None else prepared['manifest'].get('track_ci')))
    summary.update(stop_after_seconds=stop_after_seconds,target_ci=target_ci,hard_seconds=hard_seconds)
    summary.update(checkpoint_migration=checkpoint_migration,migration=migration)
    summary.update(max_memory_bytes=max_memory_bytes, chance_mode=1 if prepared['compact'].get('chance') else None)
    summary.update(training_threads=threads,parallel_mode='async_shared' if threads>1 else 'serial')
    summary['constant_scalar_shortcuts_requested']=constant_scalar_shortcuts
    summary.update(stopping_mode=stopping_mode or ('ci' if target_ci is not None else 'time' if stop_after_seconds is not None else 'samples'),
                   sampling_stage=sampling_stage, sampling_selection=selection,
                   track_ci_requested=track_ci, algorithm_change=algorithm_change)
    summary['precision_target_reached'] = bool(sampling_stage == 'calculation' and
        target_ci is not None and summary.get('stop_reason') == 'ci_target' and summary.get('target_reached'))
    summary['estimated_memory_bytes']=next((row['estimated_memory_bytes'] for row in logs if 'estimated_memory_bytes' in row),None)
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"index_path": str(output / "index.json"), "checkpoint_path": str(output / "checkpoint.bin"),
            "manifest_path": prepared["manifest_path"], "summary": summary}


def _normalize(values, special=False):
    p = [max(v, 0.0) for v in values]
    if special:
        p[0] = 0.0
        if len(p) == 2:
            return [0.0, 1.0]
    total = sum(p)
    if total > 0:
        return [v / total for v in p]
    if not special:
        return [1 / len(p)] * len(p)
    if len(p) == 3 and values[1] == values[2]:
        return [0.0, .5, .5]
    p[max(range(1, len(p)), key=values.__getitem__)] = 1.0
    return p


def read_node(output_dir, node_id: int, *, index=None, special=None, bucket_ids=None) -> dict:
    """Read one node, optionally seeking only selected dynamic bucket rows."""
    output = Path(output_dir)
    if index is None:
        index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    n = index["nodes"][node_id]
    if special is None:
        special = bool(n.get('special', 0))
    k, hcount = n["actions"], n["buckets"]
    result = dict(n)
    if not k:
        result["hands"] = []
        return result
    selected = range(hcount) if bucket_ids is None else list(bucket_ids)
    if bucket_ids is not None:
        if any(type(h) is not int or not 0<=h<hcount for h in selected) or len(set(selected))!=len(selected):
            raise ValueError('bucket_ids must contain distinct valid integer bucket IDs')
        result['bucket_selection']=selected
        result['hands_complete']=len(selected)==hcount
    def offset(h):
        return 1+k+(2*k+1)*h if n['format'] in (31,63) else 1+k+2*k*h if n['format']==27 else 1+(2*k+1)*h if n['format']==23 else 1+(h+1)*k
    width = k if n['format']==25 else 2*k if n['format']==27 else 2*k+1
    with (output / "checkpoint.bin").open("rb") as f:
        if bucket_ids is None:
            f.seek(n["visits_offset"])
            visits = struct.unpack(f"<{hcount}Q", f.read(8*hcount))
            f.seek(n["raw_offset"])
            raw = struct.unpack(f"<{n['raw_count']}d", f.read(8*n["raw_count"]))
            segments = None
            global_average=raw[1:k+1]
        else:
            visits={};segments={};raw=None
            for h in selected:
                f.seek(n['visits_offset']+8*h);visits[h]=struct.unpack('<Q',f.read(8))[0]
                f.seek(n['raw_offset']+8*offset(h));segments[h]=struct.unpack(f'<{width}d',f.read(8*width))
            f.seek(n['raw_offset']+8);global_average=struct.unpack(f'<{k}d',f.read(8*k))
        frequency_state = None
        shared_state = None
        if n['format'] == 63:
            f.seek(n['frequency_state_offset'])
            frequency_state = struct.unpack(f'<{2+3*k}d', f.read(8*(2+3*k)))
        if n['format']==31:
            f.seek(n['shared_state_offset'])
            shared_state=struct.unpack(f'<{k}d',f.read(8*k))
    locks = None
    if n.get('locks') and bucket_ids is None:
        from .hrc_policy import BucketLocks
        locks = BucketLocks(k, hcount, n['locks'])
    rows = []
    for h in selected:
        r = offset(h)
        values = raw[r:r+width] if segments is None else segments[h]
        regret = values[:k]
        if n["format"] in (23,27,31,63):
            a=k+int(n['format']!=27)
            avg = values[a:a+k]
            display = _normalize(avg)
            denominator = values[k] if n['format']!=27 else 0
            relative = [(v-regret[0])/denominator for v in regret] if denominator > 0 else None
        else:
            display = _normalize(regret)
            relative = None
        current = _normalize(regret, special)
        if bucket_ids is not None and n.get('locks'):
            from .hrc_policy import BucketLocks
            locks = BucketLocks(k, 1, [None if row is None else [row[h]] for row in n['locks']])
        if frequency_state is not None:
            edges = frequency_state[2:2+k]
            ev = [float('nan')]*k if relative is None else relative
            adjusted = [v+e for v, e in zip(ev, edges)]
            best = int(bool(special))
            for a in range(best, k):
                if adjusted[best] < adjusted[a]:
                    best = a
            current = [float(a==best) for a in range(k)]
        elif locks is not None and locks.count:
            current = locks.compose(regret, h if bucket_ids is None else 0, True, special)
            display = locks.compose(avg, h if bucket_ids is None else 0, False)
        rows.append({"bucket": h, "visits": visits[h], "trained": visits[h]>0,
                     "current_strategy": current, "display_strategy": display,
                     "relative_ev_to_action0": relative})
    result["hands"] = rows
    result["display_semantics"] = "locked_per_bucket_average" if n.get('locks') else "per_bucket_average" if n["format"] in (23,27,31,63) else "per_bucket_current_regret_policy"
    if n["format"] in (25,27):
        result["global_average"] = _normalize(global_average)
    if shared_state is not None:
        result['global_average']=_normalize(shared_state)
    if frequency_state is not None:
        result['frequency_state'] = {'minimum': frequency_state[0], 'maximum': frequency_state[1],
                                     'edges': list(frequency_state[2:2+k]), 'edge_sums': list(frequency_state[2+k:2+2*k]),
                                     'shared_sums': list(frequency_state[2+2*k:])}
        result['global_average'] = _normalize(frequency_state[2+2*k:])
    return result
