"""Native tournament solver: fixed topology with independently evaluated payoffs."""
from pathlib import Path
import json
import uuid

from .hrc_benchmarks import CACHE, config_for
from .hrc_research import HRCResearchSolver
from .tournament import MODEL, equity_spec, validated_config


class HRCTournamentSolver(HRCResearchSolver):
    model = MODEL

    def __init__(self, config):
        validated = validated_config(config)
        super().__init__(config_for(validated['benchmark'], validated['iterations'], validated['seed']))
        self.config = validated
        self.equity_config = equity_spec(validated, self.tree.rules.big_blind)
        from .hrc_training import training_spec
        training_spec(self.config, self.tree)

    def describe_node(self, path=None):
        return {**super().describe_node(path), 'utility_unit': 'currency' if self.equity_config else 'bb',
                'equity_model': self.config['utility']}

    def strategy_for(self, node):
        strategy = super().strategy_for(node)
        if strategy is not None and self.equity_config:
            strategy['utility_unit'] = 'currency'
        return strategy

    def run(self, iterations, progress_callback=None, cancel_check=None):
        from .hrc_abstraction import prepare_resources
        from .hrc_native import run
        progress = progress_callback or (lambda _: None)
        folder = CACHE / 'runs' / uuid.uuid4().hex
        resources = getattr(self, 'resource_dir', CACHE / 'abstractions')
        folder.mkdir(parents=True)
        from .hrc_snapshot import dump_tree
        dump_tree(self.tree, folder / 'tree-snapshot.json')
        progress({'phase': 'preparing', 'message': '校验行动树、抽象数据与奖金权益模型'})
        from .hrc_training import solver_compact, run_options
        compact = solver_compact(self)
        if compact.get('fgs'):
            from .hrc_fgs_config import prepare_chances
            progress({'phase': 'preparing', 'message': '校验 FGS 机会表与未来盲注设置'})
            prepare_chances(Path(r'D:\Program Files\HRC\plugins'), resources)
        if any(n['street'] > 0 and n['children'] for n in compact['nodes']):
            prepare_resources(Path(r'D:\Program Files\HRC\plugins'), resources, save=self.archive)
        result = run(compact, resources, iterations, self.config['seed'], folder,
                     progress_callback=lambda event: progress({**event, 'phase': 'training', 'message': ''}),
                     cancel_check=cancel_check, resume_from=self.resume_from, **run_options(self))
        self.output = folder
        self.index = json.loads((folder / 'index.json').read_text(encoding='utf-8'))
        # ChipEV archive values are never a reference for a tournament run.
        from .hrc_tournament_reference import matching_reference
        self.reference = matching_reference(self)
        root = self.result_node([])
        summary = {**result['summary'], 'iterations_requested': iterations,
                   'iterations_completed': result['summary'].get('iteration', 0),
                   'status': 'cancelled' if result['summary'].get('cancelled') else 'completed',
                   'utility_unit': 'currency' if self.equity_config else 'bb', 'equity_model': self.config['utility'],
                   'bounty_model': self.config['bounty']['mode'],
                   'tree_validation': self.tree.validation}
        if root['strategy'] and 'comparison' in root['strategy']:
            summary['comparison'] = root['strategy']['comparison']
        output = {'config': self.config, 'summary': summary, 'model': self.model,
                  'nodes': {'root': root['strategy']}, 'tree_provenance': self.tree.provenance,
                  'utility_unit': 'currency' if self.equity_config else 'bb', 'equity_config': self.equity_config,
                  'native_artifacts': {key: str(result[key]) for key in ('index_path', 'checkpoint_path', 'manifest_path')},
                  'export_scope': 'Root strategy; all nodes are retained in the checkpoint. No mismatched ChipEV reference is attached.'}
        output['native_artifacts']['resources_path'] = str(resources)
        (folder / 'application-result.json').write_text(json.dumps(output, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        return output
