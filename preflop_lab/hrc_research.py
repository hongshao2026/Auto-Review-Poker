"""Application adapter for fresh native training and separately loaded references."""
from __future__ import annotations

from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import uuid
import zipfile

from .hrc_benchmarks import CACHE, MODEL, ROOT, archive_for, validated_config
from .hrc_tree import load_hrc_tree


@lru_cache(maxsize=3)
def imported_tree(name):
    return load_hrc_tree(archive_for(name))


@lru_cache(maxsize=1)
def decoder():
    spec = importlib.util.spec_from_file_location('hrc_reference_decoder', ROOT / 'scripts/inspect-hrc-save.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Reference:
    """Observation-only baseline. Never passed into the trainer."""
    def __init__(self, archive):
        self.decoder = decoder()
        with zipfile.ZipFile(archive) as z:
            settings = json.loads(z.read('settings.json'))
            # Archive action amounts use 100 internal units per GUI chip;
            # saved mE relative utility is expressed in GUI chips.
            self.gui_chips_per_bb = settings['handdata']['blinds'][0] / 100
            self.monetary = settings['eqmodel']['id'] != 'chipev'
            self.nodes, _ = self.decoder.parse_tree(z.read('gametree.dat'))
            self.records, _ = self.decoder.parse_node_records(z.read('nodedata.dat'), self.nodes)

    def node(self, node_id):
        result = self.decoder.decode_storage(self.records[node_id], self.nodes[node_id])
        return {row['hand']: {'frequencies': row['display_strategy'],
                              'relative_ev' if self.monetary else 'relative_ev_bb': [v if self.monetary else v / self.gui_chips_per_bb for v in row['relative_ev_to_action0']]
                              if row['relative_ev_to_action0'] is not None else None}
                for row in result.get('buckets', []) if 'hand' in row}


def compare_hands(hands, reference, ev_key='relative_ev_bb'):
    """Uniform-combo conditional comparison, never asserted to be reach weighting."""
    weights = total = error = ev_error = ev_weight = 0.0
    ours, theirs = None, None
    max_error = 0.0
    for label, hand in hands.items():
        target = reference.get(label)
        if not target or hand['visits'] <= 0:
            continue
        p, q = hand['frequencies'], target['frequencies']
        if q is None or len(p) != len(q):
            raise ValueError('Reference action dimensions differ')
        w = 6 if len(label) == 2 else 4 if label.endswith('s') else 12
        if ours is None:
            ours, theirs = [0.0] * len(p), [0.0] * len(p)
        for i, (a, b) in enumerate(zip(p, q)):
            ours[i] += w*a
            theirs[i] += w*b
            error += w*abs(a-b)
            max_error = max(max_error, abs(a-b))
        weights += w
        total += w*len(p)
        a, b = hand.get(ev_key), target.get(ev_key)
        if a is not None and b is not None:
            # Exclude the identically zero action-0 baseline.
            ev_error += w*sum(abs(x-y) for x, y in zip(a[1:], b[1:]))
            ev_weight += w*(len(a)-1)
    return {'covered_combos': weights, 'total_combos': 1326,
            'frequency_mae_pp': 100*error/total if total else None,
            'maximum_frequency_error_pp': 100*max_error if total else None,
            'relative_ev_mae_bb' if ev_key == 'relative_ev_bb' else 'relative_ev_mae': ev_error/ev_weight if ev_weight else None,
            'ours_frequency': [x/weights for x in ours] if ours else None,
            'reference_frequency': [x/weights for x in theirs] if theirs else None,
            'weighting': 'uniform hole-card combinations at this node, not downstream reach'}


class HRCResearchSolver:
    model = MODEL

    def __init__(self, config):
        self.config = validated_config(config)
        self.archive = archive_for(self.config['benchmark'])
        self.tree = imported_tree(self.config['benchmark'])
        from .hrc_training import training_spec
        training_spec(self.config, self.tree)
        self.output = None
        self.reference = None
        self.index = None
        self.resume_from = None

    def node_at(self, path):
        node = self.tree.nodes[self.tree.root]
        for edge in path or []:
            if not isinstance(edge, str) or not edge.isascii() or not edge.isdecimal():
                raise ValueError('对照树的行动 ID 必须为子节点序号。')
            index = int(edge)
            if str(index) != edge or index >= len(node.children):
                raise ValueError('此路径没有对应行动。')
            node = self.tree.nodes[node.children[index]]
        return node

    def describe_node(self, path=None):
        path = list(path or [])
        node = self.node_at(path)
        s, bb = self.tree.states[node.id], self.tree.rules.big_blind
        actions = []
        for index, child_id in enumerate(node.children):
            a = self.tree.nodes[child_id].incoming_actions[0]
            kind = 'allin' if a.kind == 3 and a.allin else a.name
            cost = a.amount - s.street_contributions[a.actor] if a.kind == 3 else a.amount
            actions.append({'id': str(index), 'kind': kind, 'amount': a.amount/bb,
                            'cost': cost/bb, 'label': 'all-in' if a.allin else a.name})
        return {'id': 'root' if not path else '/'.join(path), 'native_id': node.id,
                'path': path, 'actor': node.actor,
                'actor_name': self.config['players'][node.actor]['name'] if node.actor is not None else None,
                'street': s.street, 'street_name': ['翻前', '翻牌', '转牌', '河牌'][s.street],
                'buckets': 0 if node.terminal else self.tree.rules.buckets[s.street],
                'pot': s.pot/bb, 'current_bet': s.current_bet/bb,
                'minimum_raise_to': (s.current_bet+s.last_full_raise)/bb,
                'contributions': [x/bb for x in s.contributions],
                'street_contributions': [x/bb for x in s.street_contributions],
                'remaining': [x/bb for x in s.remaining], 'folded': list(s.folded),
                'all_in': [not f and r == 0 for f, r in zip(s.folded, s.remaining)],
                'special': (1 if self.tree.nodes[node.children[1]].terminal else 2)
                    if len(node.children) > 1 and self.tree.nodes[node.children[1]].incoming_actions[0].kind == 1 else 0,
                'policy_bucket_labels': list(decoder().HAND_LABELS) if s.street == 0 and not node.terminal else None,
                'policy': next((row for row in self.config.get('policies', {}).get('nodes', []) if row['node_id'] == node.id), None),
                'terminal': node.terminal,
                'terminal_kind': ('fold_award' if len(s.live) == 1 else 'showdown') if node.terminal else None,
                'actions': actions, 'strategy': None}

    def strategy_for(self, node):
        if self.output is None or node['terminal']:
            return None
        from .hrc_native import read_node
        data = read_node(self.output, node['native_id'], index=self.index)
        labels = decoder().HAND_LABELS
        ev_key = 'relative_ev_bb' if self.config['utility'] == 'chips' else 'relative_ev'
        hands = {}
        for row in data['hands']:
            label = labels[row['bucket']] if node['street'] == 0 else f"桶 {row['bucket']}"
            hands[label] = {'frequencies': row['display_strategy'], 'visits': row['visits'],
                            ev_key: row.get('relative_ev_to_action0')}
        strategy = {'actions': node['actions'], 'visits': data['updates'], 'hands': hands,
                    'basis': 'average' if data['format'] in (23, 27, 31, 63) else 'current_regret_policy',
                    'display_semantics': data['display_semantics'], 'storage_format': data['format'],
                    'utility_unit': 'bb' if ev_key.endswith('_bb') else 'currency'}
        if data.get('frequency_state') is not None:
            strategy['frequency'] = {'targets': data['targets'], 'aggregate': data['global_average'],
                                     **data['frequency_state']}
        if node['street'] == 0 and self.reference is not None:
            baseline = self.reference.node(node['native_id'])
            strategy['comparison'] = compare_hands(hands, baseline, ev_key=ev_key)
            for label, row in hands.items():
                row['reference'] = baseline.get(label)
        return strategy

    def result_node(self, path):
        node = self.describe_node(path)
        node['strategy'] = self.strategy_for(node)
        return node

    def run(self, iterations, progress_callback=None, cancel_check=None):
        from .hrc_abstraction import prepare_resources
        from .hrc_native import run
        progress = progress_callback or (lambda _: None)
        folder = CACHE / 'runs' / uuid.uuid4().hex
        resources = getattr(self, 'resource_dir', CACHE / 'abstractions')
        folder.mkdir(parents=True)
        from .hrc_snapshot import dump_tree
        dump_tree(self.tree, folder / 'tree-snapshot.json')
        progress({'phase': 'preparing', 'message': '校验本机抽象数据并构建原生内核'})
        from .hrc_training import solver_compact, run_options
        compact = solver_compact(self)
        if any(n['street'] > 0 and n['children'] for n in compact['nodes']):
            prepare_resources(Path(r'D:\Program Files\HRC\plugins'), resources, save=self.archive)
        def native_progress(event):
            progress({**event, 'phase': 'training', 'message': ''})
        result = run(compact, resources, iterations, self.config['seed'], folder,
                     progress_callback=native_progress, cancel_check=cancel_check, resume_from=self.resume_from,
                     **run_options(self))
        self.output = folder
        self.index = json.loads((folder / 'index.json').read_text(encoding='utf-8'))
        progress({'phase': 'comparing', 'message': '训练结束，读取原版存档进行独立对照'})
        # This is the first access to any original trained value.
        self.reference = Reference(self.archive) if self.archive and not self.config.get('policies', {}).get('nodes') else None
        root = self.result_node([])
        summary = dict(result['summary'])
        summary.update(iterations_requested=iterations,
                       iterations_completed=summary.get('iterations_completed', summary.get('iteration', 0)),
                       status='cancelled' if summary.get('cancelled') else 'completed',
                       tree_validation=self.tree.validation)
        if root['strategy'] and 'comparison' in root['strategy']:
            summary['comparison'] = root['strategy']['comparison']
        output = {'config': self.config, 'summary': summary, 'model': MODEL,
                  'nodes': {'root': root['strategy']}, 'tree_provenance': self.tree.provenance,
                  'native_artifacts': {key: str(result[key]) for key in ('index_path', 'checkpoint_path', 'manifest_path')},
                  'export_scope': 'Root strategy and comparison; all nodes are retained in the local checkpoint and available in the node API.'}
        output['native_artifacts']['resources_path'] = str(resources)
        (folder / 'application-result.json').write_text(json.dumps(output, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        return output
