"""Read-only path-by-path comparison of cached independent and saved HRC trees.

Only settings.json and gametree.dat are read from the archive. No nodedata,
state, saved policies, or saved utilities are read. Running without --execute
only reports the plan and does not parse either large tree.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_COMPACT = ROOT/'.research-cache/deep-tree-optimization-20261106/nine40bb_large_chip/tree.json'
DEFAULT_SETTINGS = ROOT/'.research-cache/deep-tree-optimization-20261106/large-settings.json'
DEFAULT_ARCHIVE = ROOT/'analysis/hrc-desktop/nine40bb-large-ci-initial-20261106.hrcz'
DEFAULT_REPORT = ROOT/'reports/hrc-nine40bb-topology-equivalence-20261106.json'


def sha_bytes(data): return hashlib.sha256(data).hexdigest()


def sha_file(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def normalized_settings(settings):
    result = deepcopy(settings)
    # The independent cached configuration identifies these profiles by counts;
    # actual installed ID equality was separately verified by benchmark preflight.
    for spec in result.get('engine', {}).get('configuration', {}).get('abstractions', []):
        spec.pop('id', None)
    return result


def setting_differences(left, right, path='settings'):
    if type(left) is not type(right): return [{'field': path, 'independent': left, 'original': right}]
    if isinstance(left, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            if key not in left or key not in right:
                result.append({'field': path+'.'+key, 'independent': left.get(key, '<missing>'),
                               'original': right.get(key, '<missing>')})
            else: result.extend(setting_differences(left[key], right[key], path+'.'+key))
        return result
    if isinstance(left, list):
        if len(left) != len(right): return [{'field': path+'.length', 'independent': len(left), 'original': len(right)}]
        return [item for i, (a, b) in enumerate(zip(left, right))
                for item in setting_differences(a, b, path+f'[{i}]')]
    return [] if left == right else [{'field': path, 'independent': left, 'original': right}]


def compare(compact, original, *, example_limit=30):
    """Compare edge-slot paths, independent of node IDs or physical record order."""
    nodes = compact['nodes']; terminals = compact['terminals']
    original_nodes = original.nodes
    seen_own = bytearray(len(nodes)); seen_original = bytearray(len(original_nodes))
    mapping = array('i', [-1])*len(nodes)
    exact = Counter(); differences = Counter(); examples = []; paired = Counter()
    differing_nodes = 0; differing_terminals = 0
    own_streets = Counter(); original_streets = Counter()
    for i, node in enumerate(nodes):
        if node['id'] != i: raise ValueError('Cached compact node IDs are not indexed')
        if node['children']: own_streets[node['street']] += 1
    for node in original_nodes:
        if not node.terminal: original_streets[node.street] += 1

    def check(field, own, saved, path, oid, sid):
        if own == saved:
            exact[field] += 1; return True
        differences[field] += 1
        if len(examples) < example_limit:
            examples.append({'path': list(path), 'path_text': 'root'+''.join('/'+str(x) for x in path),
                'independent_node_id': oid, 'original_node_id': sid,
                'field': field, 'independent': own, 'original': saved})
        return False

    for field, expected in [('players', original.rules.players),
            ('big_blind', original.rules.big_blind), ('initial_stacks', list(original.rules.initial_stacks))]:
        check('root.'+field, compact[field], expected, (), compact['root'], original.root)
    stack = [(compact['root'], original.root, ())]
    while stack:
        oid, sid, path = stack.pop()
        if not 0 <= oid < len(nodes) or not 0 <= sid < len(original_nodes):
            raise ValueError('Child ID outside topology')
        if seen_own[oid] or seen_original[sid]:
            check('path.unique_node_mapping', [oid, sid], 'one unique node per root path', path, oid, sid)
            continue
        seen_own[oid] = seen_original[sid] = 1; mapping[oid] = sid
        own, saved, state = nodes[oid], original_nodes[sid], original.states[sid]
        own_terminal, saved_terminal = not own['children'], saved.terminal
        paired['nodes'] += 1
        good = check('node.terminal', own_terminal, saved_terminal, path, oid, sid)
        good &= check('node.actor', own['actor'], -1 if saved_terminal else saved.actor, path, oid, sid)
        good &= check('node.street', own['street'], state.street, path, oid, sid)
        good &= check('node.buckets', own['buckets'], 0 if saved_terminal else original.rules.buckets[state.street], path, oid, sid)
        actions = [original_nodes[c].incoming_actions[0].kind for c in saved.children]
        special = ((1 if original_nodes[saved.children[1]].terminal else 2)
                   if len(actions)>1 and actions[1] == 1 else 0)
        good &= check('node.special', own.get('special', 0), special, path, oid, sid)
        good &= check('node.action_kinds_in_edge_order', own['actions'], actions, path, oid, sid)
        good &= check('node.child_count', len(own['children']), len(saved.children), path, oid, sid)
        if own_terminal and saved_terminal:
            paired['terminals'] += 1
            leaf = terminals[own['terminal_id']]
            if leaf['node_id'] != oid: raise ValueError('Cached compact terminal mapping mismatch')
            leaf_good = True
            fields = {'remaining': list(state.remaining), 'contributions': list(state.contributions),
                      'folded': list(state.folded), 'dead_money': state.dead_money,
                      'live_mask': sum(1<<i for i, folded in enumerate(state.folded) if not folded)}
            for field, expected in fields.items():
                own_value = leaf.get(field, 0) if field == 'dead_money' else leaf[field]
                leaf_good &= check('terminal.'+field, own_value, expected, path, oid, sid)
            good &= leaf_good
            differing_terminals += not leaf_good
        elif not own_terminal and not saved_terminal:
            paired['decisions'] += 1
        differing_nodes += not good
        # Compare the same edge index even after a mismatch. Missing branch
        # descendants remain explicitly unpaired instead of being guessed.
        for edge in range(min(len(own['children']), len(saved.children))-1, -1, -1):
            stack.append((own['children'][edge], saved.children[edge], path+(edge,)))
    unpaired_own = seen_own.count(0); unpaired_original = seen_original.count(0)
    if unpaired_own: differences['unpaired.independent_nodes'] = unpaired_own
    if unpaired_original: differences['unpaired.original_nodes'] = unpaired_original
    return {'equivalent_on_compared_fields': not differences, 'paired': dict(paired),
        'independent_nodes': len(nodes), 'original_nodes': len(original_nodes),
        'independent_terminals': len(terminals),
        'original_terminals': sum(n.terminal for n in original_nodes),
        'independent_decisions_by_street': dict(sorted(own_streets.items())),
        'original_decisions_by_street': dict(sorted(original_streets.items())),
        'differing_paired_nodes': differing_nodes, 'differing_paired_terminals': differing_terminals,
        'unpaired_independent_nodes': unpaired_own, 'unpaired_original_nodes': unpaired_original,
        'equal_checks_by_field': dict(exact), 'difference_counts_by_field': dict(differences),
        'first_difference': examples[0] if examples else None, 'difference_examples': examples,
        'example_limit': example_limit,
        'node_ids_equal': all(i == value for i, value in enumerate(mapping)),
        'id_mapping_sha256_native_int32': sha_bytes(mapping.tobytes()),
        'limitations': [
            'Cached compact stores action kinds and edge order, not incoming action amounts or forced action sequences.',
            'Original full edge sequences are independently rule-replayed; their final state is compared at every paired leaf.',
            'Equal leaf funds do not alone prove identical intermediate bet amounts; those require the original independent builder tree, not this compact.',
            'This compares structure, abstraction counts and settlement inputs; not saved policies, strategy convergence, or CI trajectories.']}, mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--compact', type=Path, default=DEFAULT_COMPACT)
    parser.add_argument('--settings', type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument('--archive', type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument('--report', type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    plan = {'status': 'ready_not_started', 'archive': str(args.archive.resolve()),
        'independent_compact': str(args.compact.resolve()), 'independent_settings': str(args.settings.resolve()),
        'read_archive_members': ['settings.json', 'gametree.dat'], 'original_strategy_read': False,
        'original_leaf_values_read': False, 'report': str(args.report.resolve())}
    if not args.execute:
        print(json.dumps(plan, indent=2)); return
    if args.report.exists(): raise ValueError('Existing evidence report; refusing overwrite')
    started = time.perf_counter(); plan['started_utc'] = datetime.now(timezone.utc).isoformat()
    try:
        print(json.dumps({'phase': 'read_cached_compact'}), flush=True)
        independent_settings = json.loads(args.settings.read_text(encoding='utf-8'))
        plan['compact_sha256'] = sha_file(args.compact)
        compact = json.loads(args.compact.read_text(encoding='utf-8'))
        with zipfile.ZipFile(args.archive) as archive:
            payload = {}
            for name, maximum in [('settings.json', 1000000), ('gametree.dat', 200000000)]:
                if archive.namelist().count(name) != 1 or archive.getinfo(name).file_size > maximum:
                    raise ValueError('Missing, duplicate or oversized '+name)
                payload[name] = archive.read(name)
        plan['original_member_sha256'] = {name: sha_bytes(data) for name, data in payload.items()}
        saved_settings = json.loads(payload['settings.json'])
        plan['settings_equal_ignoring_only_abstraction_ids'] = normalized_settings(independent_settings) == normalized_settings(saved_settings)
        plan['settings_differences'] = setting_differences(normalized_settings(independent_settings), normalized_settings(saved_settings))
        plan['original_abstractions'] = saved_settings['engine']['configuration']['abstractions']
        print(json.dumps({'phase': 'independent_rule_replay_of_saved_gametree'}), flush=True)
        from preflop_lab.hrc_hrcz_tree import replay_archive_tree
        original = replay_archive_tree(saved_settings, payload['gametree.dat'], state=None,
            provenance={'read_members': list(payload), 'saved_strategy_loaded': False, 'saved_terminal_utilities_loaded': False})
        del payload
        plan['original_replay_validation'] = original.validation
        print(json.dumps({'phase': 'compare_all_edge_slot_paths', 'original_nodes': len(original.nodes)}), flush=True)
        result, mapping = compare(compact, original)
        plan['comparison'] = result
        plan['status'] = ('equivalent_on_compared_fields' if result['equivalent_on_compared_fields']
                          and plan['settings_equal_ignoring_only_abstraction_ids'] else 'differences_found')
        mapping_path = args.report.with_suffix('.node-map.i32')
        with mapping_path.open('wb') as stream: mapping.tofile(stream)
        plan['mapping'] = {'file': str(mapping_path.resolve()), 'format': 'native-endian signed int32, independent ID index -> original ID; -1 unpaired',
            'byteorder': sys.byteorder, 'count': len(mapping), 'bytes': mapping_path.stat().st_size}
    except Exception as exc:
        plan.update(status='failed', error=type(exc).__name__+': '+str(exc)); raise
    finally:
        plan['wall_seconds'] = time.perf_counter()-started
        plan['finished_utc'] = datetime.now(timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'status': plan['status'], 'report': str(args.report),
        'paired': result['paired'], 'first_difference': result['first_difference']}), flush=True)


if __name__ == '__main__': main()
