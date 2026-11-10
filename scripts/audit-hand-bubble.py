"""Reproduce the user's case input audit without loading saved policies."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preflop_lab.hrc_custom import HRCCustomSolver
from preflop_lab.hrc_hrcz_settings import config_to_settings, settings_to_config
from preflop_lab.hrc_hrcz_tree import load_archive_tree
from preflop_lab.hrc_presets import scenario_presets
from preflop_lab.hrc_restore import TOPOLOGY_KEYS
from preflop_lab.mtt_equity import mtt_icm_equities


def main():
    source = Path('C:/Users/Shao/HoldemResources/SavedHands/Hand bubble.hrcz')
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    with zipfile.ZipFile(source) as archive:
        settings = json.loads(archive.read('settings.json'))
        state = json.loads(archive.read('state.json'))
    config = scenario_presets()[0]['config']
    mapped = settings_to_config(settings, chip_scale=100)
    fields = ('big_blind', 'small_blind', 'ante', 'ante_type', 'straddle', 'skip_small_blind',
              'moving_button', 'max_active', 'payouts', 'other_stacks', 'utility', 'bounty')
    exact = {field: config[field] == mapped[field] for field in fields}
    exact['stacks'] = [p['stack'] for p in config['players']] == [p['stack'] for p in mapped['players']]
    exact['abstractions'] = config_to_settings(config)['engine']['configuration'] == settings['engine']['configuration']
    observed = load_archive_tree(source)
    solver = HRCCustomSolver(config)
    nodes_equal = observed.nodes == solver.tree.nodes
    original, generated = observed.compact_export(), solver.tree.compact_export()
    # ArchiveTree also exports diagnostic action context absent from GeneratedTree.
    # Compare every native terminal field, then check the extra context via states.
    extra = {'street', 'raise_count', 'participant_mask', 'street_contributions'}
    assert all(set(row) - set(generated['terminals'][i]) == extra for i, row in enumerate(original['terminals']))
    normalized = [{k: v for k, v in row.items() if k not in extra} for row in original['terminals']]
    topology_equal = {key: original[key] == generated[key] for key in TOPOLOGY_KEYS if key != 'terminals'}
    topology_equal['terminals'] = normalized == generated['terminals']
    context_equal = all(
        observed.states[n.id].remaining == solver.tree.states[n.id].remaining
        and observed.states[n.id].contributions == solver.tree.states[n.id].contributions
        and observed.states[n.id].street == solver.tree.states[n.id].street
        and observed.states[n.id].participant_mask == solver.tree.states[n.id].participant_mask
        for n in observed.nodes)
    diagnostic_differences = [dict(node_id=n.id, terminal=not bool(n.children),
        archive=list(observed.states[n.id].street_contributions),
        generated=list(solver.tree.states[n.id].street_contributions))
        for n in observed.nodes
        if observed.states[n.id].street_contributions != solver.tree.states[n.id].street_contributions]
    baseline = mtt_icm_equities([p['stack'] for p in config['players']], config['payouts'], config['other_stacks'])
    error = max(abs(a-b) for a, b in zip(baseline, state['eqpre']))
    selected = solver.tree.nodes[solver.tree.nodes[0].children[0]]
    report = dict(source=str(source), source_sha256=digest, read_saved_policy=False,
                  supported=mapped['hrcz_metadata']['unsupported'] == [],
                  configuration_equal=exact, all_nodes_equal=nodes_equal,
                  topology_and_terminal_states_equal=topology_equal,
                  all_node_chip_and_street_context_equal=context_equal,
                  diagnostic_street_contribution_differences=diagnostic_differences,
                  diagnostic_difference_effect='Node 9 is a terminal walk; remaining chips, total contributions and native terminal payoffs are identical. The per-street diagnostic is not part of this native training input.',
                  total_nodes=len(observed.nodes), decision_nodes=sum(bool(n.children) for n in observed.nodes),
                  decision_nodes_by_street=dict(Counter(n.street for n in observed.nodes if n.children)),
                  selected_path=[0], selected_node=asdict(selected),
                  initial_equity_expected=state['eqpre'], initial_equity_actual=baseline,
                  initial_equity_max_absolute_error=error,
                  limitations=['Input/tree/baseline equivalence does not establish converged strategy equivalence.',
                               'Independent initialization creates its own frozen UTG prefix strategy.'])
    target = ROOT / 'reports/hrc-hand-bubble-input-audit-20261108.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('selected_node', 'initial_equity_expected', 'initial_equity_actual')}, ensure_ascii=False))
    assert report['supported'] and all(exact.values()) and nodes_equal and all(topology_equal.values()) and context_equal and error < 1e-10
    assert [row['node_id'] for row in diagnostic_differences] == [9] and diagnostic_differences[0]['terminal']
    assert selected.id == 1 and selected.actor == 1 and len(selected.children) == 3


if __name__ == '__main__':
    main()
