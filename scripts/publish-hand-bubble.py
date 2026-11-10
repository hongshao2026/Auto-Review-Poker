"""Expose a completed independent native phase through the local application.

No training is launched. Only completed phase files are accepted; original
HRC nodedata and saved terminal utilities are never loaded.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_benchmarks import MAX_SAMPLES
from preflop_lab.hrc_restore import restore_solver
from preflop_lab.hrc_snapshot import load_tree
from preflop_lab.server import RUN_ROOT

JOB_IDS = {'initialization': 'c91b410871fa4388851c857bf6dca100', 'formal': 'c91b410871fa4388851c857bf6dca101'}


def publish(phase):
    case = ROOT / '.research-cache/hand-bubble-20261108'
    folder = case / phase
    summary = json.loads((folder / 'summary.json').read_text())
    if summary.get('kind') != 'finished':
        raise ValueError('Only a finished native checkpoint can be published')
    config = json.loads((case / 'config.json').read_text())
    config['constant_scalar_shortcuts'] = summary.get('constant_scalar_shortcuts', False)
    if phase == 'formal':
        if summary['iteration'] > MAX_SAMPLES:
            raise ValueError('Completed phase exceeds application sample domain; retain raw results')
        config.update(iterations=summary['total'], stopping_mode='ci', target_ci=10,
                      track_ci=True, sampling_stage='calculation',
                      sampling_scope='selected_subtree', sampling_path=[0])
    solver = restore_solver(config, load_tree(case / 'tree-snapshot.json'))
    solver.output = folder
    solver.index = json.loads((folder / 'index.json').read_text())
    root = solver.result_node([])
    config = solver.config
    summary = {**summary, 'iterations_requested': summary['total'],
               'iterations_completed': summary['iteration'],
               'status': 'cancelled' if summary.get('cancelled') else 'completed',
               'native': True, 'original_solver_called': False, 'fresh_zero_origin': True,
               'resumed': phase == 'formal', 'seed': config['seed'], 'mode': 'v4',
               'stopping_mode': config['stopping_mode'], 'sampling_stage': config['sampling_stage'],
               'sampling_selection': {'sampling_scope': config['sampling_scope'],
                   'sampling_path': config['sampling_path'], 'root_node_id': 1 if phase == 'formal' else 0, 'street': 0},
               'precision_target_reached': phase == 'formal' and summary.get('stop_reason') == 'ci_target' and summary.get('target_reached', False),
               'utility_unit': 'currency', 'equity_model': config['utility'],
               'bounty_model': config['bounty']['mode'], 'tree_validation': solver.tree.validation}
    shutil.copyfile(case / 'tree-snapshot.json', folder / 'tree-snapshot.json')
    # Match the historical binary/checkpoint identity exactly for valid resume.
    for name in ('tree.json', 'manifest.json'):
        shutil.copyfile(case / 'input' / name, folder / name)
    output = dict(config=config, summary=summary, model=solver.model,
        nodes={'root': root['strategy']}, tree_provenance=solver.tree.provenance,
        utility_unit='currency', equity_config=solver.equity_config,
        native_artifacts=dict(index_path=str(folder / 'index.json'),
            checkpoint_path=str(folder / 'checkpoint.bin'), manifest_path=str(folder / 'manifest.json'),
            resources_path=str(ROOT / '.research-cache/abstractions')),
        job_id=JOB_IDS[phase], created_at=datetime.now(timezone.utc).isoformat(),
        parent_job_id=JOB_IDS['initialization'] if phase == 'formal' else None,
        research_provenance=dict(independent_zero_initialization=True, source_policy_used=False,
            saved_leaf_utilities_used=False, original_cli_cap=summary['total'],
            application_resume_cap=config['iterations'], selected_path=[0] if phase == 'formal' else []),
        export_scope='Independent native checkpoint; the summary records whether CI10 was actually reached.')
    encoded = json.dumps(output, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    (folder / 'application-result.json').write_text(encoded, encoding='utf-8')
    RUN_ROOT.mkdir(exist_ok=True)
    target = RUN_ROOT / (JOB_IDS[phase] + '.json')
    if target.exists():
        raise FileExistsError('Published phase already exists; it is immutable')
    target.write_text(encoded, encoding='utf-8')
    print(json.dumps(dict(job_id=JOB_IDS[phase], phase=phase, samples=summary['iteration']), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=JOB_IDS)
    publish(parser.parse_args().phase)
