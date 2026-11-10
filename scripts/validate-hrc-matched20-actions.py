"""Rebuild own tree, bind it to timed input, compare every saved action/state."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_tree_builder import build_tree
from preflop_lab.hrc_hrcz_tree import load_archive_tree


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    base = ROOT/'.research-cache/three40bb-ci10-independent-20261107'
    archive = ROOT/'analysis/hrc-desktop/three40bb-matched20-20261108/final.hrcz'
    settings = json.loads((base/'settings.json').read_text(encoding='utf-8'))
    cached = json.loads((base/'input/tree.json').read_text(encoding='utf-8'))
    manifest = json.loads((base/'input/manifest.json').read_text(encoding='utf-8'))
    own = build_tree(settings, special_fold_mode='checkdown')
    # Original archive is opened only after the generated compact exactly matches
    # the actual immutable timed input. No saved strategy guides the builder.
    assert own.compact_export() == cached
    assert sha(base/'input/tree.bin') == manifest['tree_binary_sha256']
    original = load_archive_tree(archive)
    counts, differences, examples = Counter(), Counter(), []
    def check(field, left, right, path):
        counts[field] += 1
        if left != right:
            differences[field] += 1
            if len(examples) < 20:
                examples.append(dict(field=field, path=list(path), own=left, original=right))
    stack = [(own.root, original.root, ())]
    while stack:
        a, b, path = stack.pop()
        left, right = own.nodes[a], original.nodes[b]
        counts['nodes'] += 1
        check('incoming_actions_kind_actor_street_amount_allin',
              [asdict(x) for x in left.incoming_actions], [asdict(x) for x in right.incoming_actions], path)
        counts['individual_incoming_actions'] += len(left.incoming_actions)
        check('actor', left.actor, right.actor, path)
        check('street', left.street, right.street, path)
        check('child_count', len(left.children), len(right.children), path)
        for key in ['remaining', 'contributions', 'street_contributions', 'folded', 'street',
                    'current_bet', 'pot', 'dead_money']:
            check('state.'+key, getattr(own.states[a], key), getattr(original.states[b], key), path)
        stack.extend((x, y, path+(i,)) for i, (x, y) in enumerate(zip(left.children, right.children)))
    assert counts['nodes'] == len(own.nodes) == len(original.nodes) == 3964
    report = dict(schema='hrc-matched20-full-actions-v1', status='equivalent' if not differences else 'differences_found',
                  rebuilt_compact_exactly_equals_timed_input=True, native_binary_matches_frozen_manifest=True,
                  settings_sha256=sha(base/'settings.json'), timed_compact_sha256=sha(base/'input/tree.json'),
                  timed_tree_binary_sha256=sha(base/'input/tree.bin'), original_archive_sha256=sha(archive),
                  builder_source_sha256=sha(ROOT/'preflop_lab/hrc_tree_builder.py'),
                  original_replayer_source_sha256=sha(ROOT/'preflop_lab/hrc_hrcz_tree.py'),
                  compared_counts=dict(counts), differences=dict(differences), examples=examples,
                  interpretation='Extends the compact-only audit: every full incoming action sequence, including amounts/all-in flags, and intermediate funds now compared.',
                  limits=['This binds the independent generated tree to timed input and checks action/state equality, not solver/CI/strategy equivalence.',
                          'Original replay and builder share reviewed rule primitives; action sequences are compared directly from archive words.'])
    destination = ROOT/'reports/hrc-three40bb-matched20-actions-20261108.json'
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    assert not differences, differences
    print(json.dumps({'status': report['status'], 'checks': dict(counts), 'report': str(destination)}))


if __name__ == '__main__':
    main()
