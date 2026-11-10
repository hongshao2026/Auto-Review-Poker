"""Versioned data-only tree snapshots; never pickle Python or load executable code."""
from dataclasses import asdict
import json
from pathlib import Path

from .hrc_tree import HRCAction, HRCNode, ImportedTree, ReplayRules, ReplayState
from .hrc_tree_builder import GeneratedTree, GeneratedState


def dump_tree(tree, path):
    from .hrc_hrcz_tree import ArchiveTree
    payload = {'schema': 'preflop-tree-snapshot-v1', 'generated': isinstance(tree, (GeneratedTree, ArchiveTree)),
               'archive_tree': isinstance(tree, ArchiveTree), 'tree': asdict(tree)}
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def load_tree(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema') != 'preflop-tree-snapshot-v1' or type(payload.get('generated')) is not bool:
        raise ValueError('Unsupported saved tree schema')
    row = payload['tree']
    if not 1 <= len(row['nodes']) <= 1000000 or len(row['states']) != len(row['nodes']):
        raise ValueError('Invalid saved tree dimensions')
    rules = row['rules']
    rules = ReplayRules(tuple(rules['initial_stacks']), rules['big_blind'], rules['small_blind'], tuple(rules['buckets']))
    if not 2 <= rules.players <= 10 or len(rules.buckets) != 4 or rules.big_blind <= 0:
        raise ValueError('Invalid saved table dimensions')
    nodes = []
    for index, data in enumerate(row['nodes']):
        if data['id'] != index:
            raise ValueError('Saved nodes must be in ID order')
        nodes.append(HRCNode(data['id'], data['parent_id'], data['actor'], data['street'],
                             tuple(data['children']), tuple(HRCAction(**action) for action in data['incoming_actions'])))
    states = []
    kind = GeneratedState if payload['generated'] else ReplayState
    for data in row['states']:
        for field in ('remaining', 'contributions', 'street_contributions', 'folded', 'pending', 'reopen_at'):
            data[field] = tuple(data[field])
            if len(data[field]) != rules.players:
                raise ValueError('Saved chip state does not match table dimensions')
        state = kind(**data)
        if sum(state.remaining) + state.pot != sum(rules.initial_stacks):
            raise ValueError('Saved chip state does not conserve chips')
        states.append(state)
    extra = ()
    if payload.get('archive_tree'):
        from .hrc_hrcz_tree import ArchiveTree
        cls = ArchiveTree
        extra = (tuple(row['record_order']), tuple(row['raise_counts']), row['archive_state'])
    else:
        cls = GeneratedTree if payload['generated'] else ImportedTree
    return cls(row['settings'], rules, tuple(nodes), tuple(states), row['root'], row['provenance'], row['validation'], *extra)
