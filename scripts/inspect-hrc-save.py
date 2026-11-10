#!/usr/bin/env python3
"""Read-only inspection/comparison of HRC 4.1 save archives; stdlib only.

This is research tooling, not an application-compatible loader or copied solver.
Evidence: pZ/pX/pY/qf, mt/mE/mA/mB/mD/mz/my/mx, ls/lM in the reviewed JAR.
Input archives are never modified or extracted. Unknown layouts remain explicit.
"""
from __future__ import annotations

import argparse
import hashlib
import gzip
import io
import json
import math
import struct
import sys
import zipfile
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "hrc-save-research-v1"
TARGET_SHA = "25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43"
RANKS = "23456789TJQKA"
ACTION_NAMES = ("fold", "check", "call", "raise")
CORE = ("settings.json", "state.json", "gametree.dat", "nodedata.dat", "idx.dat")


class DecodeError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(value):
    """Strict JSON while preserving nonfinite distinctions; bytes retain their own hashes."""
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("+Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def stable(value) -> bytes:
    return json.dumps(clean(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def need(condition, message):
    if not condition:
        raise DecodeError(message)


def unpack(fmt, data, offset=0):
    size = struct.calcsize(fmt)
    need(offset >= 0 and offset + size <= len(data), f"Truncated {fmt} at offset {offset}, buffer={len(data)}")
    return struct.unpack_from(fmt, data, offset)


def hand_label(index):
    row, col = divmod(index, 13)
    if row == col:
        return RANKS[row] * 2
    return RANKS[max(row, col)] + RANKS[min(row, col)] + ("s" if row > col else "o")


HAND_LABELS = [hand_label(i) for i in range(169)]
HAND_COMBOS = [6 if i // 13 == i % 13 else (4 if i // 13 > i % 13 else 12) for i in range(169)]


def action(word):
    kind = word & 15
    need(kind < 4 and (word & 240) == 0, f"Unsupported action word {word:016x}")
    return {"kind": ACTION_NAMES[kind], "actor": (word >> 8) & 15,
            "street": (word >> 13) & 7, "allin_flag": bool(word & 4096),
            "amount_internal": (word >> 16) & ((1 << 48) - 1), "encoded_hex": f"{word:016x}",
            "amount_semantics": "raise_to" if kind == 3 else ("increment" if kind == 2 else "none")}


def parse_tree(data):
    count, = unpack("<i", data)
    need(0 < count <= 10_000_000, f"Invalid tree node count {count}")
    nodes, offsets, pos = {}, {}, 4
    for _ in range(count):
        start = pos
        node_id, parent_id, kind, sequence_len, child_count = unpack("<iiBbh", data, pos)
        pos += 12
        need(0 <= node_id < count and node_id not in nodes, f"Invalid/duplicate node ID {node_id}")
        need(kind in (1, 2) and sequence_len >= 0 and child_count >= 0, f"Unsupported tree header for {node_id}")
        if kind == 1:
            street, actor = unpack("<bb", data, pos)
            pos += 2
        else:
            street, actor = None, None
            need(child_count == 0, f"Leaf {node_id} contains child count")
        words = unpack("<" + "Q" * sequence_len, data, pos)
        pos += sequence_len * 8
        children = list(unpack("<" + "i" * child_count, data, pos)) if kind == 1 else []
        pos += child_count * 4
        nodes[node_id] = {"id": node_id, "parent_id": parent_id, "kind": "decision" if kind == 1 else "leaf",
                          "street": street, "actor": actor, "incoming_actions": [action(w) for w in words],
                          "child_ids": children}
        offsets[node_id] = (start, pos - start)
    need(pos == len(data), f"Unexpected trailing tree bytes: {len(data)-pos}")
    roots = [i for i, n in nodes.items() if n["parent_id"] == -1]
    need(len(roots) == 1, f"Expected one root, found {roots}")
    queue, seen = deque([(roots[0], "root")]), set()
    while queue:
        node_id, path = queue.popleft()
        need(node_id in nodes and node_id not in seen, f"Cycle/reused/missing tree node {node_id}")
        seen.add(node_id)
        node = nodes[node_id]
        node["path"] = path
        for edge, child in enumerate(node["child_ids"]):
            if child == -1:
                continue
            need(child in nodes and nodes[child]["parent_id"] == node_id, f"Parent-child mismatch {node_id}->{child}")
            queue.append((child, f"{path}/{edge}"))
    need(len(seen) == count, f"Unreachable tree nodes: {count-len(seen)}")
    return nodes, offsets


def parse_node_records(data, nodes):
    declared_count, = unpack("<i", data)
    need(declared_count == len(nodes), f"Node payload mapping count {declared_count} != tree count {len(nodes)}")
    records, offsets, pos = {}, {}, 4
    # Viewer files intentionally contain fewer actual payload records than their count header.
    while pos < len(data):
        start = pos
        node_id, size, reserved, fmt, buckets, locks, reserved_tail = unpack("<iiiiiiQ", data, pos)
        need(node_id in nodes and node_id not in records, f"Invalid/duplicate payload ID {node_id}")
        need(0 <= size <= 268435424 and buckets >= 0 and locks >= 0, f"Invalid payload header at {pos}")
        pos += 32
        need(pos + size <= len(data), f"Truncated node payload for {node_id}")
        records[node_id] = {"format_id": fmt, "bucket_or_vector_count": buckets, "locked_action_count": locks,
                            "reserved": [reserved, reserved_tail], "payload": data[pos:pos+size]}
        pos += size
        offsets[node_id] = (start, pos - start)
    return records, offsets


def verify_index(data, tree_offsets, data_offsets):
    need(len(data) == 24 * len(tree_offsets), f"idx.dat length {len(data)} != 24*nodes")
    for node_id in range(len(tree_offsets)):
        toff, tlen, doff, dlen = unpack("<qiqi", data, node_id * 24)
        need((toff, tlen) == tree_offsets[node_id], f"idx.dat tree location mismatch at node {node_id}")
        expected = data_offsets.get(node_id, (0, 0))
        need((doff, dlen) == expected, f"idx.dat payload location mismatch at node {node_id}: {(doff,dlen)} != {expected}")


def normalize_positive(values):
    if not all(math.isfinite(v) for v in values):
        return None
    positive = [max(v, 0.0) for v in values]
    total = sum(positive)
    return [v / total for v in positive] if total > 0 else [1 / len(values)] * len(values)


def apply_saved_locks(weights, saved):
    """Read-side my.a(bucket) / mx.a(...,false), only when a my wrapper exists."""
    if not saved:
        return normalize_positive(weights)
    if not all(math.isfinite(v) for v in weights) or not all(math.isfinite(v) for v in saved.values()):
        return None
    k, total = len(weights), sum(saved.values())
    if len(saved) == k or total >= 1:
        return [saved.get(i, 0.0) for i in range(k)]
    free = [i for i in range(k) if i not in saved]
    result = [saved.get(i, 0.0) for i in range(k)]
    if len(free) == 1:
        result[free[0]] = 1 - total
        return result
    denominator = sum(max(0, weights[i]) for i in free)
    if denominator == 0:
        result[free[0]] = 1 - total
    else:
        for i in free:
            result[i] = (1 - total) * max(0, weights[i]) / denominator
    return result


def float_array(data):
    need(len(data) % 4 == 0, "Storage float array length is not divisible by four")
    return list(unpack("<" + "f" * (len(data) // 4), data))


def decode_storage(record, node):
    fmt, count, payload = record["format_id"], record["bucket_or_vector_count"], record["payload"]
    result = {"format_id": fmt, "payload_bytes": len(payload), "payload_sha256": sha(payload),
              "reserved": record["reserved"], "decode_status": "decoded"}
    if node["kind"] == "leaf":
        need(fmt == 1024 and record["locked_action_count"] == 0, f"Unsupported leaf layout {fmt}")
        need((count > 0 and len(payload) % (4 * count) == 0) or (count == 0 and len(payload) == 0), "Invalid leaf vector size")
        values = float_array(payload)
        width = len(values) // count if count else 0
        result.update(vector_count=count, vector_width=width,
                      leaf_vectors=[values[i*width:(i+1)*width] for i in range(count)],
                      value_semantics="saved terminal utility vectors; model/unit comes from settings, not assumed chipEV")
        return result
    k = len(node["child_ids"])
    need(k >= 2, f"Decision node {node['id']} has fewer than two actions")
    locks, pos = {}, 0
    for _ in range(record["locked_action_count"]):
        edge, = unpack("<i", payload, pos)
        pos += 4
        need(0 <= edge < k and edge not in locks, f"Invalid/duplicate lock action {edge}")
        locks[edge] = list(unpack("<" + "f" * count, payload, pos))
        pos += 4 * count
    data = payload[pos:]
    result.update(bucket_count=count, action_count=k,
                  locked_actions=[{"action_index": edge, "weights": values} for edge, values in sorted(locks.items())],
                  storage_bytes=len(data), storage_sha256=sha(data))
    if fmt not in (23, 25, 27, 31, 63):
        result.update(decode_status="unsupported_storage_format", buckets=[],
                      reason="Legacy/unknown format preserved by exact payload hash; no invented strategies or counts")
        return result
    if fmt == 63:
        prefix_count = 2 * k + 2
        metadata = list(unpack("<" + "f" * prefix_count, data))
        original_format, = unpack("<i", data, prefix_count * 4)
        result["frequency_constraints"] = {"target_frequencies": metadata[:k], "stored_range_values": metadata[k:k+2],
                                             "edges": metadata[k+2:], "underlying_format_id": original_format}
        data = data[4 * (prefix_count + 1):]
    values = float_array(data)
    expected = {23: 1+(2*k+1)*count, 25: 1+k+k*count, 27: 1+k+2*k*count,
                31: 1+k+(2*k+1)*count, 63: 1+k+(2*k+1)*count}[fmt]
    need(len(values) == expected, f"Node {node['id']} format {fmt}: expected {expected} floats, got {len(values)}")
    result.update(saved_counter_float32=values[0], counter_semantics="per-node update counter saved as float32; not global solver iterations or per-hand visits",
                  float_count=len(values), has_relative_ev=fmt in (23, 31, 63),
                  ev_semantics="(R[action]-R[action0])/weighted_denominator; original utility scale, not absolute EV, not automatically bb",
                  hand_mapping="ls/lM 169 preflop classes" if node["street"] == 0 and count == 169 else "abstract bucket IDs; no hand labels inferred")
    if fmt in (25, 27, 31, 63):
        result["shared_average_weights"] = values[1:1+k]
        result["shared_average_strategy"] = normalize_positive(values[1:1+k])
    rows = []
    for bucket in range(count):
        start = (1 + (2*k+1)*bucket if fmt == 23 else
                 1 + k + (k if fmt == 25 else 2*k if fmt == 27 else 2*k+1)*bucket)
        regret = values[start:start+k]
        denominator = values[start+k] if fmt in (23, 31, 63) else None
        average = None if fmt == 25 else values[start+k+(1 if fmt in (23,31,63) else 0):start+2*k+(1 if fmt in (23,31,63) else 0)]
        source = regret if average is None else average
        saved = {edge: weights[bucket] for edge, weights in locks.items()}
        # Original my display requires an average segment; flag unsupported combinations.
        display = None if saved and average is None else apply_saved_locks(source, saved)
        relative = ([(v-regret[0])/denominator for v in regret]
                    if denominator is not None and denominator > 0 and math.isfinite(denominator) else None)
        row = {"bucket": bucket, "regret_values": regret, "weighted_denominator": denominator,
               "average_weights": average, "display_strategy": display, "relative_ev_to_action0": relative,
               "has_positive_average_weight": average is not None and sum(max(v,0) for v in average) > 0,
               "locked_probabilities": saved, "strategy_basis": "positive_regret_normalization" if fmt == 25 else "saved_average_normalization"}
        if node["street"] == 0 and count == 169:
            row.update(hand=HAND_LABELS[bucket], combos=HAND_COMBOS[bucket])
        rows.append(row)
    result["buckets"] = rows
    result["positive_average_buckets"] = sum(row["has_positive_average_weight"] for row in rows)
    return result


def inspect(path: Path, external_profile=None, max_bytes=2_147_483_648):
    need(path.is_file(), f"Archive not found: {path}")
    need(path.stat().st_size <= max_bytes, f"Archive exceeds --max-bytes: {path}")
    raw = path.read_bytes()
    entries, blobs = [], {}
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        infos = archive.infolist()
        names = [entry.filename for entry in infos]
        need(len(names) == len(set(names)), "Duplicate ZIP entry names are ambiguous")
        need(sum(entry.file_size for entry in infos) <= max_bytes, "Uncompressed archive exceeds --max-bytes")
        for entry in infos:
            need(not (entry.flag_bits & 1), f"Encrypted ZIP entry unsupported: {entry.filename}")
            content = archive.read(entry)
            entries.append({"name": entry.filename, "size": entry.file_size, "compressed_size": entry.compress_size,
                            "compression": entry.compress_type, "crc32": f"{entry.CRC:08x}", "sha256": sha(content),
                            "date_time": list(entry.date_time), "extra_hex": entry.extra.hex(), "comment_hex": entry.comment.hex()})
            if entry.filename in CORE:
                blobs[entry.filename] = content
    for required in CORE[:4]:
        need(required in blobs, f"Missing required entry {required}")
    settings_text, state_text = (blobs[name].decode("utf-8-sig") for name in CORE[:2])
    settings, state = json.loads(settings_text), json.loads(state_text)
    nodes, tree_offsets = parse_tree(blobs["gametree.dat"])
    records, data_offsets = parse_node_records(blobs["nodedata.dat"], nodes)
    if "idx.dat" in blobs:
        verify_index(blobs["idx.dat"], tree_offsets, data_offsets)
    normalized = {}
    for node_id, node in nodes.items():
        item = {key: value for key, value in node.items() if key not in ("id", "parent_id", "child_ids", "path")}
        item["children"] = [None if child == -1 else nodes[child]["path"] for child in node["child_ids"]]
        item["actions"] = [{"action_index": i, "child_path": None if child == -1 else nodes[child]["path"],
                            "sequence": None if child == -1 else nodes[child]["incoming_actions"]}
                           for i, child in enumerate(node["child_ids"])]
        item["data"] = decode_storage(records[node_id], node) if node_id in records else {"decode_status": "missing_viewer_payload"}
        normalized[node["path"]] = item
    core = {"settings": settings, "state": state, "nodes": normalized}
    formats = Counter(str(record["format_id"]) for record in records.values())
    return {"schema": SCHEMA, "profile": {"reviewed_implementation": "HRC 4.1.0.202603231401", "reviewed_jar_sha256": TARGET_SHA,
                "file_version_claim": "archive itself has no verified JAR identity; external profile must establish producer",
                "archive_path": str(path.resolve()), "archive_sha256": sha(raw), "archive_bytes": len(raw),
                "entry_metadata": entries, "settings_json_exact_text": settings_text, "state_json_exact_text": state_text,
                "external": external_profile, "decoder_sha256": sha(Path(__file__).read_bytes()),
                "hand_mapping_evidence": "ls ordinal0708 / lM ordinal0715; 22=0, AA=168; row>col suited",
                "limitations": ["No original program code is executed", "Counts are float32 snapshots, not exact iteration history",
                                "Untrained display fallback may be uniform; positive_average_buckets is evidence of stored positive mass, not convergence",
                                "EV values are relative to action0 in original utility units", "Legacy storage formats remain opaque"]},
            "summary": {"nodes": len(nodes), "decision_nodes": sum(n["kind"] == "decision" for n in nodes.values()),
                        "leaf_nodes": sum(n["kind"] == "leaf" for n in nodes.values()), "payload_records": len(records),
                        "missing_payload_records": len(nodes)-len(records), "formats": dict(formats),
                        "index_verified": "idx.dat" in blobs, "canonical_sha256": sha(stable(core)),
                        "locked_action_total": sum(r["locked_action_count"] for r in records.values()),
                        "opaque_nodes": sum(n["data"]["decode_status"] == "unsupported_storage_format" for n in normalized.values())},
            **core}


def differences(a, b, limit=200, tolerance=0.0):
    found, count, maximum = [], 0, 0.0
    def walk(left, right, path):
        nonlocal count, maximum
        if isinstance(left, (int,float)) and not isinstance(left,bool) and isinstance(right,(int,float)) and not isinstance(right,bool):
            if math.isfinite(left) and math.isfinite(right):
                delta = abs(left-right)
                maximum = max(maximum, delta)
                if delta <= tolerance:
                    return
            elif clean(left) == clean(right):
                return
        elif isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    record(path+"/"+str(key), left.get(key,"<missing>"), right.get(key,"<missing>"))
                else:
                    walk(left[key], right[key], path+"/"+str(key))
            return
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                record(path+"/length", len(left), len(right))
            for i, (lv,rv) in enumerate(zip(left,right)):
                walk(lv,rv,path+"/"+str(i))
            return
        elif left == right:
            return
        record(path,left,right)
    def record(path, left, right):
        nonlocal count
        count += 1
        if len(found) < limit:
            found.append({"path":path,"before":clean(left),"after":clean(right)})
    walk(a,b,"")
    return {"equal":count == 0,"difference_count":count,"maximum_absolute_numeric_difference":maximum,
            "examples":found,"examples_truncated":count > len(found),"absolute_tolerance":tolerance}


def compare(before, after, tolerance=0.0):
    sections = {}
    for key in ("settings","state"):
        sections[key] = differences(before[key], after[key], tolerance=tolerance)
    structure_before = {p:{k:v for k,v in n.items() if k != "data"} for p,n in before["nodes"].items()}
    structure_after = {p:{k:v for k,v in n.items() if k != "data"} for p,n in after["nodes"].items()}
    sections["tree"] = differences(structure_before,structure_after)
    data_before = {p:n["data"] for p,n in before["nodes"].items()}
    data_after = {p:n["data"] for p,n in after["nodes"].items()}
    sections["node_data_exact"] = differences(data_before,data_after)
    # Hashes are exact comparisons. Tolerant numeric diagnostics must not mask raw loss.
    profiles = [snapshot["profile"].get("external") for snapshot in (before,after)]
    profile_comparison = differences(profiles[0]["data"],profiles[1]["data"]) if all(p is not None for p in profiles) else None
    return {"schema": SCHEMA+"-comparison", "before_profile":before["profile"],"after_profile":after["profile"],
            "before_summary":before["summary"],"after_summary":after["summary"],
            "external_experiment_profile_comparison":profile_comparison,
            "same_archive_bytes":before["profile"]["archive_sha256"] == after["profile"]["archive_sha256"],
            "same_canonical_state_exact":before["summary"]["canonical_sha256"] == after["summary"]["canonical_sha256"],
            "comparison":sections,"interpretation":"Exact canonical equality ignores ZIP metadata, record order and node IDs; it includes settings, equity state, topology, raw strategy payload, locks and counters. Equality supports only the observed saves; differences may reflect continued solving rather than serialization loss."}


def synthetic_archive(path, reverse=False, counter=2.0, lock=False):
    """Transparent self-test fixture writer, never used to modify a supplied archive."""
    ids = {0:0, 1:2 if reverse else 1, 2:1 if reverse else 2}
    def word(kind, actor=0, amount=0):
        return kind | actor << 8 | amount << 16
    tree_records = {0:struct.pack("<iiBbhbbii",0,-1,1,0,2,0,0,ids[1],ids[2]),
                    1:struct.pack("<iiBbhQ",ids[1],0,2,1,0,word(0)),
                    2:struct.pack("<iiBbhQ",ids[2],0,2,1,0,word(2,amount=100))}
    floats = [counter] + [.5,2.5,3,1.25,1.75] * 169
    stored = struct.pack("<"+"f"*len(floats),*floats)
    locked = struct.pack("<i",0)+struct.pack("<"+"f"*169,*([.25]*169)) if lock else b""
    payload = locked + stored
    payloads = {0:struct.pack("<iiiiiiQ",0,len(payload),0,23,169,int(lock),0)+payload}
    for original in (1,2):
        payloads[original] = struct.pack("<iiiiiiQ",ids[original],8,0,1024,1,0,0)+struct.pack("<ff",-1,1)
    order = [2,0,1] if reverse else [0,1,2]
    tree,data = bytearray(struct.pack("<i",3)),bytearray(struct.pack("<i",3))
    locations = {}
    for original in order:
        locations[ids[original]] = [len(tree),len(tree_records[original]),len(data),len(payloads[original])]
        tree.extend(tree_records[original]);data.extend(payloads[original])
    index = b"".join(struct.pack("<qiqi",*locations[i]) for i in range(3))
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("settings.json",json.dumps({"synthetic_test_fixture":True,"handdata":{"stacks":[1000,1000],"blinds":[100,50,0]}}))
        archive.writestr("state.json",'{"eqpre":[0,0],"eqpost":[0,0]}')
        archive.writestr("gametree.dat",tree);archive.writestr("nodedata.dat",data);archive.writestr("idx.dat",index)


def self_test(folder):
    folder.mkdir(parents=True,exist_ok=True)
    files = [folder/name for name in ("synthetic-a.hrcz","synthetic-reordered.hrcz","synthetic-counter.hrcz","synthetic-lock.hrcz")]
    synthetic_archive(files[0]);synthetic_archive(files[1],reverse=True)
    synthetic_archive(files[2],counter=3);synthetic_archive(files[3],lock=True)
    a,b,c,d = [inspect(p) for p in files]
    checks = []
    def check(name, condition, actual=None):
        checks.append({"name":name,"pass":bool(condition),"actual":clean(actual)})
    check("169_labels_unique_and_combo_count",len(set(HAND_LABELS)) == 169 and sum(HAND_COMBOS) == 1326)
    check("native_169_mapping",[HAND_LABELS[i] for i in (0,12,156,168)] == ["22","A2o","A2s","AA"])
    row = a["nodes"]["root"]["data"]["buckets"][168]
    check("original_strategy_probe_fixture_average",row["display_strategy"] == [5/12,7/12],row["display_strategy"])
    check("original_strategy_probe_fixture_relative_ev",row["relative_ev_to_action0"] == [0,2/3],row["relative_ev_to_action0"])
    check("explicit_saved_counter",a["nodes"]["root"]["data"]["saved_counter_float32"] == 2)
    check("lock_read_semantics",d["nodes"]["root"]["data"]["buckets"][0]["display_strategy"] == [.25,.75])
    check("canonical_ignore_record_ids_and_order",compare(a,b)["same_canonical_state_exact"])
    check("counter_loss_detected",not compare(a,c)["same_canonical_state_exact"])
    check("lock_change_detected",not compare(a,d)["same_canonical_state_exact"])
    node = {"id":0,"kind":"decision","street":1,"child_ids":[1,2]}
    def storage(fmt, values, prefix=b""):
        payload=prefix+struct.pack("<"+"f"*len(values),*values)
        return decode_storage({"format_id":fmt,"bucket_or_vector_count":1,"locked_action_count":0,
                               "reserved":[0,0],"payload":payload},node)
    fmt25=storage(25,[2,1,3,4,-2])
    check("format25_shared_average_is_not_bucket_strategy",fmt25["shared_average_strategy"] == [.25,.75]
          and fmt25["buckets"][0]["display_strategy"] == [1,0] and fmt25["buckets"][0]["relative_ev_to_action0"] is None)
    fmt27=storage(27,[2,1,3,4,-2,1,3])
    check("format27_has_average_without_ev",fmt27["buckets"][0]["display_strategy"] == [.25,.75]
          and fmt27["buckets"][0]["relative_ev_to_action0"] is None)
    fmt31=storage(31,[2,1,3,.5,2.5,3,1.25,1.75])
    check("format31_flat_serialized_segments",fmt31["buckets"][0]["relative_ev_to_action0"] == [0,2/3])
    fmt63=storage(63,[2,1,3,.5,2.5,3,1.25,1.75],struct.pack("<ffffffi",float("nan"),.5,0,10,0,0,23))
    check("format63_prefix_and_data",clean(fmt63["frequency_constraints"])["target_frequencies"] == ["NaN",.5]
          and fmt63["frequency_constraints"]["underlying_format_id"] == 23
          and fmt63["buckets"][0]["relative_ev_to_action0"] == [0,2/3])
    unknown=storage(7,[0])
    check("legacy_unknown_is_explicit",unknown["decode_status"] == "unsupported_storage_format" and not unknown["buckets"])
    corrupt = folder/"synthetic-bad-index.hrcz"
    with zipfile.ZipFile(files[0]) as source,zipfile.ZipFile(corrupt,"w") as dest:
        for name in source.namelist():
            data = source.read(name)
            if name == "idx.dat":
                damaged=bytearray(data);struct.pack_into("<i",damaged,8,999);data=bytes(damaged)
            dest.writestr(name,data)
    try:
        inspect(corrupt);rejected=False
    except DecodeError:
        rejected=True
    check("corrupt_index_rejected",rejected)
    return {"schema":SCHEMA+"-self-test","passed":all(c["pass"] for c in checks),"checks":checks,
            "fixture_directory":str(folder.resolve()),"evidence_limit":"Synthetic archive tests plus existing original strategy numeric fixture; does not prove compatibility with an application-generated save until supplied."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("save",nargs="?",type=Path)
    parser.add_argument("other",nargs="?",type=Path,help="Compare a second save after canonicalizing node IDs/order")
    parser.add_argument("--output",type=Path,help="Write full JSON report (.gz suffix compresses JSON); default stdout")
    parser.add_argument("--profile",type=Path,help="Exact external experiment profile JSON, preserved with text/hash")
    parser.add_argument("--other-profile",type=Path)
    parser.add_argument("--max-bytes",type=int,default=2_147_483_648)
    parser.add_argument("--tolerance",type=float,default=0,help="Settings/state numeric diagnostics only; exact state verdict always remains exact")
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--fixture-dir",type=Path,default=Path("analysis/hrc-desktop/decoder-fixtures"))
    args = parser.parse_args()
    def profile(path):
        if path is None:return None
        data=path.read_bytes()
        return {"path":str(path.resolve()),"sha256":sha(data),"exact_text":data.decode("utf-8-sig"),"data":json.loads(data)}
    try:
        if args.self_test:
            report=self_test(args.fixture_dir)
        else:
            if args.save is None:parser.error("provide a save path or --self-test")
            if args.output and args.output.resolve() in {p.resolve() for p in (args.save,args.other,args.profile,args.other_profile) if p}:
                parser.error("output must not overwrite an input archive or experiment profile")
            first=inspect(args.save,profile(args.profile),args.max_bytes)
            report=compare(first,inspect(args.other,profile(args.other_profile),args.max_bytes),args.tolerance) if args.other else first
        report["generated_utc"]=datetime.now(timezone.utc).isoformat()
        encoded=json.dumps(clean(report),ensure_ascii=False,indent=2,allow_nan=False)+"\n"
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            if args.output.suffix.lower() == ".gz":
                with gzip.open(args.output,"wt",encoding="utf-8",compresslevel=6) as stream:
                    stream.write(encoded)
            else:
                args.output.write_text(encoded,encoding="utf-8")
            print(json.dumps({"output":str(args.output.resolve()),"schema":report["schema"],
                              "summary":report.get("summary"),"passed":report.get("passed"),
                              "same_canonical_state_exact":report.get("same_canonical_state_exact")},ensure_ascii=False))
        else:
            print(encoded,end="")
        return 0 if report.get("passed",True) else 1
    except (DecodeError,ValueError,OSError,zipfile.BadZipFile,struct.error) as error:
        print(json.dumps({"error":str(error),"type":type(error).__name__},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
