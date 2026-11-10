"""Compact, read-only archive comparison for the recorded nine-seat 10/20BB runs.

Decode and validate every node one at a time; retain only the root's 169 classes.
This observes HRC results and does not implement a multiway solver.
"""
from collections import Counter
from datetime import datetime, timezone
import argparse
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hrc_save", ROOT / "scripts/inspect-hrc-save.py")
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def snapshot(path):
    path = path.resolve()
    decoder.need(path.stat().st_size < 512 * 1024**2, "Archive size exceeds research limit")
    with zipfile.ZipFile(path) as archive:
        decoder.need(len(archive.namelist()) == len(set(archive.namelist())), "Duplicate archive entries")
        decoder.need(sum(x.file_size for x in archive.infolist()) < 512 * 1024**2, "Expanded archive too large")
        blobs = {name: archive.read(name) for name in decoder.CORE}
    settings, state = (json.loads(blobs[n]) for n in decoder.CORE[:2])
    nodes, tree_offsets = decoder.parse_tree(blobs["gametree.dat"])
    records, data_offsets = decoder.parse_node_records(blobs["nodedata.dat"], nodes)
    decoder.verify_index(blobs["idx.dat"], tree_offsets, data_offsets)
    decoder.need(len(records) == len(nodes), "Complete save has missing node data")
    streets, formats, buckets, canonical = Counter(), Counter(), Counter(), {}
    root = None
    locks = 0
    for node_id, node in nodes.items():
        record = records[node_id]
        data = decoder.decode_storage(record, node)
        decoder.need(data["decode_status"] == "decoded", "Unsupported node format")
        formats[str(record["format_id"])] += 1
        locks += record["locked_action_count"]
        if node["kind"] == "decision":
            streets[str(node["street"])] += 1
            buckets[str(node["street"])] += record["bucket_or_vector_count"]
        children = [nodes[c]["path"] if c != -1 else None for c in node["child_ids"]]
        canonical[node["path"]] = {
            "kind": node["kind"], "actor": node["actor"], "street": node["street"],
            "incoming_actions": node["incoming_actions"], "children": children,
            "storage": {k: v for k, v in record.items() if k != "payload"},
            "payload_sha256": data["payload_sha256"],
        }
        if node["path"] == "root":
            decoder.need(node["street"] == 0 and node["actor"] == 0, "Expected UTG preflop root")
            decoder.need(record["format_id"] == 23 and record["bucket_or_vector_count"] == 169, "Unexpected root storage")
            rows = data["buckets"]
            decoder.need(len({row["hand"] for row in rows}) == 169, "Hand labels incomplete")
            decoder.need(all(row["has_positive_average_weight"] for row in rows), "Untrained root class")
            decoder.need(all(abs(sum(row["display_strategy"]) - 1) < 1e-12 for row in rows), "Invalid strategy")
            frequency = [sum(row["combos"] * row["display_strategy"][i] for row in rows) / 1326
                         for i in range(len(node["child_ids"]))]
            root = {"actions": [nodes[c]["incoming_actions"] for c in node["child_ids"]],
                    "uniform_combo_weighted_frequency": frequency,
                    "saved_update_counter_float32": data["saved_counter_float32"], "hands": rows}
    decoder.need(root is not None, "Root missing")
    decoder.need(settings["eqmodel"] == {"id": "chipev", "raked": False}, "Expected unraked ChipEV")
    decoder.need(len(settings["handdata"]["stacks"]) == 9, "Expected nine seats")
    decoder.need(settings["handdata"]["blinds"] == [10000, 5000, 0], "Unexpected blinds/ante")
    root["selected_raise_2bb_ev_bb"] = {
        row["hand"]: row["relative_ev_to_action0"][1] / 100
        for row in root["hands"] if row["hand"] in ("AA", "KK", "22", "72o")
    }
    return {"archive": str(path), "archive_sha256": decoder.sha(path.read_bytes()),
            "archive_bytes": path.stat().st_size, "settings": settings, "state": state,
            "summary": {"nodes": len(nodes), "decision_nodes": sum(streets.values()),
                        "leaf_nodes": len(nodes)-sum(streets.values()), "decisions_by_street": dict(streets),
                        "bucket_rows_by_street": dict(buckets), "formats": dict(formats),
                        "locked_action_total": locks, "all_nodes_decoded": True, "all_index_entries_verified": True,
                        "raw_state_canonical_sha256": decoder.sha(decoder.stable({"settings": settings, "state": state, "nodes": canonical}))},
            "root": root}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    decoder.need(args.output.resolve() not in [p.resolve() for p in args.archives], "Output would overwrite archive")
    results = [snapshot(path) for path in args.archives]
    differences = [decoder.differences(results[0]["settings"], r["settings"]) for r in results[1:]]
    report = {"schema": "hrc-nine-stack-depth-v1", "generated_utc": datetime.now(timezone.utc).isoformat(),
              "script_sha256": decoder.sha(Path(__file__).read_bytes()),
              "decoder_sha256": decoder.sha((ROOT / "scripts/inspect-hrc-save.py").read_bytes()),
              "snapshots": results, "settings_differences_from_first": differences,
              "limitations": ["Original HRC observed results, not an independent nine-player solve.",
                              "Node counters and sample counts are not convergence or exploitability certificates.",
                              "Only root uses uniform combo weighting; downstream reach is not inferred.",
                              "Raw-state canonical hash is separate from the full expanded decoder's hash convention.",
                              "Current action set includes 2bb opens and all-in 3bets, no non-all-in 3bet sizing."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decoder.clean(report), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "snapshots": [
        {"file": Path(r["archive"]).name, "summary": r["summary"],
         "root_frequency": r["root"]["uniform_combo_weighted_frequency"],
         "root_counter": r["root"]["saved_update_counter_float32"],
         "root_ev_bb": r["root"]["selected_raise_2bb_ev_bb"]} for r in results],
        "setting_changes": differences}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
