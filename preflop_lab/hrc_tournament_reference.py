"""Only expose a monetary reference whose model and complete tree are verified."""
import hashlib
import json
from pathlib import Path
import zipfile

from .hrc_research import Reference, ROOT
from .hrc_benchmarks import BENCHMARKS
from .hrc_tree import ImportedTree, parse_gametree, replay_tree

PKO_REFERENCE = ROOT / 'analysis/hrc-desktop/eight15bb-pko-50-30-20-60m.hrcz'
PKO_SHA = '139ce6e706e9574dcfed430642bd0d0251d8ef0dc53017079a010853200cc259'


def matching_reference(solver):
    cfg = solver.config
    if (getattr(solver, 'archive', None) is None or not Path(solver.archive).is_file()
        or cfg.get('policies', {}).get('nodes') or cfg.get('fgs', {}).get('enabled')):
        return None
    if (cfg.get('engine') != 'hrc_tournament' or cfg.get('benchmark') != 'eight15bb'
        or cfg.get('utility') != 'icm' or cfg.get('payouts') != [50, 30, 20] or cfg.get('other_stacks')
        or cfg.get('bounty') != {'mode': 'pko', 'amounts': [10]*8, 'other_amounts': [], 'immediate_fraction': .5}):
        return None
    if not PKO_REFERENCE.is_file():
        return None
    if hashlib.sha256(PKO_REFERENCE.read_bytes()).hexdigest() != PKO_SHA:
        raise ValueError('PKO 对照存档身份发生变化。')
    if hashlib.sha256(solver.archive.read_bytes()).hexdigest() != BENCHMARKS['eight15bb']['sha256']:
        raise ValueError('固定行动树存档身份发生变化。')
    with zipfile.ZipFile(PKO_REFERENCE) as archive, zipfile.ZipFile(solver.archive) as topology:
        settings = json.loads(archive.read('settings.json'))
        source_settings = json.loads(topology.read('settings.json'))
        if (settings['engine'] != source_settings['engine'] or settings['treeconfig'] != source_settings['treeconfig']
            or {k: v for k, v in settings['handdata'].items() if k != 'bounties'} != source_settings['handdata']):
            raise ValueError('PKO 对照的建树、牌抽象或盲注规则不一致。')
        # The archive stores node records in hash-map iteration order. Compare
        # every semantic field and replayed state; physical record offsets are
        # not node/action order. Neither reference policy nor leaf EV is read.
        nodes, root = parse_gametree(archive.read('gametree.dat'))
        states, validation = replay_tree(nodes, root, solver.tree.rules)
        if root != solver.tree.root or nodes != solver.tree.nodes or states != solver.tree.states:
            raise ValueError('PKO 对照行动树、强制行动或终局状态不同。')
        observed = ImportedTree(settings, solver.tree.rules, nodes, states, root, {}, validation).compact_export()
        expected = solver.tree.compact_export()
        if any(observed[key] != expected[key] for key in ('root', 'players', 'big_blind', 'initial_stacks', 'nodes', 'terminals')):
            raise ValueError('PKO 对照的原生节点、special 标记或结算输入不同。')
        hand, equity = settings['handdata'], settings['eqmodel']
        if (hand['stacks'] != [150000]*8 or hand['blinds'] != [10000, 5000, 0] or hand['bounties'] != [10]*8
            or equity['id'] != 'icm' or equity['structure']['bountyType'] != 'PKO'
            or equity['structure']['progressiveFactor'] != .5
            or equity['structure']['prizes'] != {'1': 50., '2': 30., '3': 20., '4': 0., '8': 0.}):
            raise ValueError('PKO 对照配置不一致。')
    return Reference(PKO_REFERENCE)
