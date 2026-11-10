"""Observation-only EP comparison after an independent native phase ends."""
import argparse
import json
import mmap
from pathlib import Path
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_native import read_node
from preflop_lab.hrc_research import decoder


def source_node(archive, node_id):
    """Read only one original decision payload; never load saved leaf vectors."""
    with zipfile.ZipFile(archive) as source:
        index = source.read('idx.dat')
        _, _, offset, length = struct.unpack_from('<qiqi', index, node_id * 24)
        with source.open('nodedata.dat') as stream:
            stream.seek(offset)
            block = stream.read(length)
    ident, size, reserved, fmt, buckets, locks, tail = struct.unpack_from('<6iQ', block)
    assert ident == node_id and size + 32 == len(block) and fmt == 23 and buckets == 169
    record = dict(format_id=fmt, bucket_or_vector_count=buckets, payload=block[32:],
                  reserved=[reserved, tail], locked_action_count=locks)
    return decoder().decode_storage(record, dict(id=node_id, kind='decision', street=0, child_ids=[0, 1, 2]))


def frozen_audit(case, phase):
    original = json.loads((case / 'initialization/index.json').read_text())
    current = json.loads((phase / 'index.json').read_text())
    compact = json.loads((case / 'input/tree.json').read_text())
    selected, pending = set(), [1]
    while pending:
        ident = pending.pop()
        selected.add(ident)
        pending.extend(compact['nodes'][ident]['children'])
    failures, checked = [], 0
    with (case / 'initialization/checkpoint.bin').open('rb') as fa, (phase / 'checkpoint.bin').open('rb') as fb:
        with mmap.mmap(fa.fileno(), 0, access=mmap.ACCESS_READ) as a, mmap.mmap(fb.fileno(), 0, access=mmap.ACCESS_READ) as b:
            for i, row in enumerate(original['nodes']):
                if i in selected:
                    continue
                other = current['nodes'][i]
                start = row['visits_offset'] - 12
                end = original['nodes'][i+1]['visits_offset'] - 12 if i+1 < len(original['nodes']) else row['raw_offset'] + row['raw_count'] * 8
                checked += 1
                if row != other or a[start:end] != b[start:end]:
                    failures.append(i)
    return dict(outside_nodes_checked=checked, changed_outside_node_ids=failures,
                all_outside_node_records_byte_identical=not failures)


def compare(phase_name, *, output_dir=None, label=None):
    case = ROOT / '.research-cache/hand-bubble-20261108'
    phase = Path(output_dir) if output_dir is not None else case / phase_name
    summary = json.loads((phase / 'summary.json').read_text())
    assert summary['kind'] == 'finished'
    source = source_node('C:/Users/Shao/HoldemResources/SavedHands/Hand bubble.hrcz', 1)
    own = read_node(phase, 1)
    assert own['actions'] == 3 and own['buckets'] == 169
    weights, left, right, rows = 0, [0.] * 3, [0.] * 3, []
    for a, b in zip(own['hands'], source['buckets']):
        assert a['bucket'] == b['bucket']
        p, q, weight = a['display_strategy'], b['display_strategy'], b['combos']
        distance = sum(abs(x-y) for x, y in zip(p, q)) / 2
        weights += weight
        for i in range(3):
            left[i] += p[i] * weight
            right[i] += q[i] * weight
        rows.append(dict(hand=b['hand'], combos=weight, ours=p, hrc=q,
                         total_variation=distance, visits=a['visits']))
    report = dict(phase=phase_name, selected_path=[0], node_id=1,
        action_order=['fold', 'raise to 2bb', 'all-in to 29.775bb'],
        source_policy_used_for_training=False, source_leaf_utilities_read=False,
        summary=summary, original_saved_node_update_counter_float32=source['saved_counter_float32'],
        original_saved_ci='not recorded in this archive',
        uniform_combo_weighted_frequencies=dict(ours=[v/weights for v in left], hrc=[v/weights for v in right]),
        uniform_combo_weighted_total_variation=sum(r['total_variation']*r['combos'] for r in rows)/weights,
        hands=rows, limitations=['Uniform-combo weighting is not conditional reach weighting.',
            'Own frozen UTG strategy comes from independent initialization; HRC used its saved prefix.',
            'A stopped or initialized phase is not a converged result; CI is a strategy drift metric.'])
    if phase_name == 'formal':
        report['frozen_prefix_audit'] = frozen_audit(case, phase)
        assert report['frozen_prefix_audit']['all_outside_node_records_byte_identical']
    target = ROOT / f'reports/hrc-hand-bubble-{label or phase_name}-comparison-20261108.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('phase', 'uniform_combo_weighted_frequencies', 'uniform_combo_weighted_total_variation')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('initialization', 'formal'))
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--label', choices=('ci10',))
    args = parser.parse_args()
    compare(args.phase, output_dir=args.output_dir, label=args.label)
