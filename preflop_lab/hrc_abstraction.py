"""Preprocess explicitly selected, locally installed HRC abstraction resources.

Only data resources are read. Generic Brotli decoding does not load any HRC
class, solver, strategy, or license component. The cache is local research data
and must not be bundled as independent product assets. Card ranking is separate
and independently implemented in native/hrc_cards.hpp.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

PROFILES = {
    1: (1024, "22804b04d3732210b3f28dbaee3a59fbe7ab7a573b679ee68c876760aba76b94"),
    2: (256, "661d702e82b930222bdd1e7cea3eef35f9306baaad628cec48713091b7e2e398"),
    3: (256, "41e796828302d1cb95d18663fc2e1eee65f2831c90b26339a814d285003785a1"),
}
ROW_COUNTS = {1: 1755, 2: 16432, 3: 134459}
HOLE_COLUMNS = {1: 1176, 2: 1128, 3: 1081}
# Independently enumerated indices, then compared byte-for-byte with original
# lo's three complete index arrays by exact-profile-original-reader-validation.
BOARD_DIGESTS = {
    1: "b5f4eb663ab0657ceb31273943d2aa96c87e025804b65983358464e0c52933ac",
    2: "c4dc7ccbe7d0ff940f2b7f91a28f9280e28b07ebcf161f388c3156be8a1319b7",
    3: "48748c346e100e9c99f21c0833463d25a39d5ee4e272b41c1df6a71d06f6414a",
}
SUIT_MASK = 0x1111111111111


def canonical_board(board: int) -> tuple[int, tuple[int, ...]]:
    """Return sorted suit-vector board and stable old-suit -> new-suit map."""
    vectors = [(board >> s) & SUIT_MASK for s in range(4)]
    order = sorted(range(4), key=vectors.__getitem__)
    mapping = [0] * 4
    for new, old in enumerate(order):
        mapping[old] = new
    return sum(vectors[old] << new for new, old in enumerate(order)), tuple(mapping)


def permute_mask(mask: int, mapping) -> int:
    return sum(((mask >> s) & SUIT_MASK) << mapping[s] for s in range(4))


def combo_index(lo: int, hi: int) -> int:
    lo, hi = sorted((lo, hi))
    if not 0 <= lo < hi < 52:
        raise ValueError("Expected two different card IDs in 0..51")
    return hi * (hi - 1) // 2 + lo


def preflop_class(lo: int, hi: int) -> int:
    lo, hi = sorted((lo, hi))
    a, b = hi // 4, lo // 4
    return a * 13 + b if (lo % 4 == hi % 4 or a == b) else b * 13 + a


def legal_hole_column(board: int, lo: int, hi: int) -> int:
    """Index after removing board cards, equivalent to filtered combo order."""
    lo, hi = sorted((lo, hi))
    if board & ((1 << lo) | (1 << hi)):
        raise ValueError("Hole/board collision")
    a = lo - (board & ((1 << lo) - 1)).bit_count()
    b = hi - (board & ((1 << hi) - 1)).bit_count()
    return b * (b - 1) // 2 + a


def canonical_boards(street: int) -> list[int]:
    if street not in PROFILES:
        raise ValueError("Street must be 1, 2 or 3")
    boards = {canonical_board(sum(1 << c for c in cards))[0]
              for cards in itertools.combinations(range(52), street + 2)}
    result = sorted(boards)
    if len(result) != ROW_COUNTS[street]:
        raise ValueError("Canonical board enumeration count mismatch")
    return result


def file_sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def verify_profile_from_save(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        settings = json.loads(z.read("settings.json"))
    abstractions = settings["engine"]["configuration"]["abstractions"]
    by_street = {a["street"]: a for a in abstractions}
    for s, (buckets, digest) in PROFILES.items():
        if by_street.get(s, {}).get("buckets") != buckets or by_street[s].get("id") != digest:
            raise ValueError(f"Save profile does not match selected street {s}")
    return {"path": str(path.resolve()), "sha256": file_sha256(path), "abstractions": abstractions}


def verify_cached_resources(output: Path) -> dict:
    """Verify portable local data against known profile identities, without a JAR."""
    output = Path(output)
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    rows = {p['street']: p for p in manifest['profiles']}
    for street, (buckets, digest) in PROFILES.items():
        row = rows[street]
        values = output / f'street{street}.buckets.u16'
        boards = output / f'street{street}.boards.u64'
        if row['id'] != digest or row['buckets'] != buckets or file_sha256(values) != digest or file_sha256(boards) != BOARD_DIGESTS[street]:
            raise ValueError('保存的翻后抽象资源身份不匹配。')
    return manifest


def prepare_resources(plugins: Path, output: Path, jdk: Path | None = None,
                      save: Path | None = None) -> dict:
    root = Path(__file__).resolve().parents[1]
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if save:
        verify_profile_from_save(save)
    try:
        return verify_cached_resources(output)
    except (OSError, KeyError, TypeError, ValueError):
        pass
    old_manifest = {}
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        try:
            old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    old_profiles = {p["street"]: p for p in old_manifest.get("profiles", [])}
    jar = plugins / "net.holdemresources.postflopabstractions.holdem_1.0.0.jar"
    decoder = plugins / "net.holdemresources.calculator.mavendependencies_0.2.0/org.brotli/dec-0.1.2.jar"
    source = root / "scripts/java/BrotliResourceBytes.java"
    jdk = jdk or Path(r"D:\Tools\REA-Research\jdk-21.0.13+9\bin")
    java = str(jdk / "java.exe") if (jdk / "java.exe").exists() else shutil.which("java")
    javac = str(jdk / "javac.exe") if (jdk / "javac.exe").exists() else shutil.which("javac")
    if not java or not javac:
        raise RuntimeError("A JDK is required only for the generic Brotli preprocessing helper")
    helper = output / "decoder-helper"
    helper.mkdir(exist_ok=True)
    subprocess.run([javac, "-cp", str(decoder), "-d", str(helper), str(source)],
                   check=True, capture_output=True)
    manifest = {"schema": "local-hrc-abstraction-v1", "data_origin": "user-installed proprietary resource; local research cache only",
                "training_uses_original_code": False, "resource_jar": str(jar.resolve()),
                "resource_jar_sha256": file_sha256(jar), "generic_brotli_jar_sha256": file_sha256(decoder),
                "card_id": "rank*4+suit:2c=0,As=51", "row_order": "canonical board mask ascending",
                "column_order": "hi*(hi-1)/2+lo after deleting board cards from deck",
                "byte_order": "little", "save_profile": verify_profile_from_save(save) if save else None,
                "profiles": []}
    with zipfile.ZipFile(jar) as z:
        for street, (buckets, digest) in PROFILES.items():
            members = [n for n in z.namelist() if n.endswith(f".{buckets}.{street}.{digest}.dat.br")]
            if len(members) != 1:
                raise ValueError(f"Expected one exact resource for street {street}")
            member = members[0]
            values_path = output / f"street{street}.buckets.u16"
            expected_size = ROW_COUNTS[street] * HOLE_COLUMNS[street] * 2
            values_valid = (values_path.exists() and values_path.stat().st_size == expected_size
                            and file_sha256(values_path) == digest)
            if not values_valid:
                temporary = values_path.with_suffix(".pending")
                with temporary.open("wb") as f:
                    run = subprocess.run([java, "-Xmx512m", "-cp", str(helper) + (";" if sys.platform == "win32" else ":") + str(decoder),
                                          "BrotliResourceBytes", str(jar), member], stdout=f, stderr=subprocess.PIPE)
                if run.returncode:
                    raise RuntimeError(run.stderr.decode(errors="replace"))
                if temporary.stat().st_size != expected_size or file_sha256(temporary) != digest:
                    raise ValueError(f"Resource content hash or length mismatch for street {street}")
                temporary.replace(values_path)
            board_path = output / f"street{street}.boards.u64"
            previous = old_profiles.get(street, {})
            board_cache_valid = (old_manifest.get("schema") == "local-hrc-abstraction-v1"
                                 and previous.get("id") == digest
                                 and previous.get("rows") == ROW_COUNTS[street]
                                 and board_path.exists()
                                 and board_path.stat().st_size == ROW_COUNTS[street] * 8
                                 and file_sha256(board_path) == previous.get("boards_sha256") == BOARD_DIGESTS[street])
            if board_cache_valid:
                board_hash = previous["boards_sha256"]
            else:
                boards = canonical_boards(street)
                board_bytes = struct.pack("<" + "Q" * len(boards), *boards)
                board_path.write_bytes(board_bytes)
                board_hash = hashlib.sha256(board_bytes).hexdigest()
                if board_hash != BOARD_DIGESTS[street]:
                    raise ValueError(f"Canonical board digest mismatch at street {street}")
            if (values_valid and previous.get("values_sha256") == digest
                    and previous.get("minimum_bucket") == 0
                    and previous.get("maximum_bucket") == buckets - 1):
                low, high = previous["minimum_bucket"], previous["maximum_bucket"]
            else:
                values = array.array("H")
                with values_path.open("rb") as f:
                    values.fromfile(f, ROW_COUNTS[street] * HOLE_COLUMNS[street])
                if sys.byteorder != "little":
                    values.byteswap()
                low, high = min(values), max(values)
                del values
                if low < 0 or high >= buckets:
                    raise ValueError(f"Bucket outside profile bounds at street {street}")
            profile = {"street": street, "buckets": buckets, "id": digest, "resource_member": member,
                       "compressed_member_sha256": hashlib.sha256(z.read(member)).hexdigest(),
                       "rows": ROW_COUNTS[street], "hole_columns": HOLE_COLUMNS[street], "values_bytes": expected_size,
                       "values_sha256": digest, "boards_sha256": board_hash,
                       "minimum_bucket": low, "maximum_bucket": high,
                       "values_file": values_path.name, "boards_file": board_path.name}
            manifest["profiles"].append(profile)
            print(json.dumps({"prepared_street": street, "rows": ROW_COUNTS[street], "bytes": expected_size,
                              "reused_verified_boards": board_cache_valid}), flush=True)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins", type=Path, default=Path(r"D:\Program Files\HRC\plugins"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--jdk", type=Path)
    args = parser.parse_args()
    manifest = prepare_resources(args.plugins, args.output, args.jdk, args.save)
    print(json.dumps({"manifest": str((args.output / "manifest.json").resolve()),
                      "profiles": len(manifest["profiles"])}))


if __name__ == "__main__":
    main()
