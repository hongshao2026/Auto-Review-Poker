"""Three-player wide 40BB independent preparation and measured full-tree CI run.

--prepare builds solely from explicit settings, never saved HRC policies/EVs.
--validate reads only the original settings/gametree for a complete audit.
--execute requires that successful audit and an externally granted CPU slot.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT/'.research-cache/three40bb-ci10-independent-20261107'
REPORT = ROOT/'reports/hrc-three40bb-ci10-independent-20261107.json'
AUDIT = ROOT/'reports/hrc-three40bb-topology-equivalence-20261107.json'
ARCHIVE = ROOT/'analysis/hrc-desktop/three40bb-wide-initial-20261107.hrcz'
RESOURCES = ROOT/'.research-cache/abstractions'


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


monitor = load_script('ci_benchmark_monitor', 'benchmark-hrc-ci-target.py')


def verify_build():
    from preflop_lab import hrc_native as native
    paths = (native.SOURCE, native.CARDS, native.EQUITY, native.MTT, native.POLICY, native.CI,
             native.FGS, native.SETTLEMENT, native.CHANCE, native.DYNAMIC, native.DIGEST, native.PARALLEL, native.SCOPE)
    digest = hashlib.sha256(b''.join(path.read_bytes() for path in paths)).hexdigest()
    build = json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text())
    if build['source_sha256'] != digest or monitor.sha(Path(build['executable_path'])) != build['executable_sha256']:
        raise ValueError('Current source does not match the prebuilt executable; no automatic compile during benchmark')
    return build


def prepare():
    if (OUTPUT/'initialization').exists() or (OUTPUT/'formal').exists():
        raise ValueError('Existing benchmark data; preparation must not overwrite a run')
    settings = json.loads((ROOT/'.research-cache/deep-tree-optimization-20261106/large-settings.json').read_text())
    settings['handdata']['stacks'] = [400000]*3
    settings['engine']['maxactive'] = 3
    OUTPUT.mkdir(parents=True, exist_ok=True)
    monitor.dump(OUTPUT/'settings.json', settings)
    from preflop_lab.hrc_tree_builder import build_tree
    from preflop_lab.hrc_native import prepare as native_prepare
    started = time.perf_counter()
    generated = build_tree(settings)
    prepared = native_prepare(generated, OUTPUT/'input')
    paths = []
    for node in generated.nodes:
        if not node.terminal and node.street == 0:
            path = generated.node_path(node.id)
            description = generated.describe_node(path)
            paths.append({'id': node.id, 'path': path, 'actor': node.actor,
                'actor_name': ['BTN', 'SB', 'BB'][node.actor], 'actions': description['actions']})
    monitor.dump(OUTPUT/'preflop-node-paths.json', paths)
    resource_manifest = json.loads((RESOURCES/'manifest.json').read_text())
    plan = {'schema': 'independent-three40bb-fulltree-ci-benchmark-v1', 'status': 'ready_not_started',
        'prepared_utc': monitor.now(), 'output': str(OUTPUT), 'report': str(REPORT),
        'settings_path': str(OUTPUT/'settings.json'), 'original_archive': str(ARCHIVE),
        'tree': prepared['manifest'], 'tree_binary': str(OUTPUT/'input/tree.bin'),
        'tree_compact': str(OUTPUT/'input/tree.json'), 'resources_dir': str(RESOURCES),
        'resource_profiles': resource_manifest['profiles'], 'build': verify_build(),
        'preparation_seconds': time.perf_counter()-started, 'node_paths': str(OUTPUT/'preflop-node-paths.json'),
        'topology_audit': str(AUDIT), 'fresh_zero': True, 'original_strategy_read': False,
        'original_leaf_values_read': False, 'seed': 43, 'mode': 'v4', 'scope': 'full_tree',
        'training_threads': 8, 'memory_budget_bytes': 6<<30, 'initialization_samples': 10000000,
        'initialization_track_ci': True, 'formal_target_ci': 10, 'formal_total_sample_cap': 3000000000,
        'maximum_additional_samples': 2990000000,
        'hard_seconds_per_phase': 3600, 'reset_regret': False, 'reset_average': False,
        'checkpoint_policy': 'production adaptive_wall_time: clamp(20*last_write_seconds,30,300)',
        'sample_cap_semantics': 'Explicit CLI cumulative cap3b and additional budget2.99b, including unchanged10m initialization; no counter reset. Default CLI/Web/API1b domain remains. Cap is not CI success.',
        'timing_boundaries': {'phase_wall': 'Popen to process exit: load, startup save, CI init, training and all saves',
            'native_elapsed': 'training stage: CI init/poll, sampling, scheduling, periodic/final saves',
            'loading_and_setup': 'Popen to started event: load, allocation, worker setup, startup save and initial CI snapshot',
            'checkpoint_seconds': 'Native timed binary/index serialization and replacement; no fsync',
            'ci_snapshot_duration': 'Not separately instrumented. Adaptive interval records snapshot-only measured duration; original HRC includes entire measurement. No formula/timer change during this run.'},
        'comparability_limits': ['Independent xoshiro RNG stream and asynchronous update order differ from HRC.',
            'CI is recent policy drift, not exploitability or a statistical confidence interval.',
            'Both initialization and formal run track CI; formal restarts Tracker while retaining all learned node arrays.',
            'Original saved strategies and terminal utilities are not training inputs.'], 'phases': {}}
    monitor.dump(OUTPUT/'plan.json', plan); monitor.dump(REPORT, plan)
    print(json.dumps({'status': plan['status'], 'nodes': prepared['manifest']['nodes'],
        'decisions': prepared['manifest']['decision_nodes'], 'preflop_decisions': len(paths),
        'tree': str(OUTPUT/'input'), 'seconds': plan['preparation_seconds']}), flush=True)


def validate():
    plan = json.loads((OUTPUT/'plan.json').read_text())
    if not ARCHIVE.exists(): raise FileNotFoundError('Original initialization archive not ready: '+str(ARCHIVE))
    audit_command = [sys.executable, str(ROOT/'scripts/validate-hrc-nine40bb-topology.py'), '--execute',
        '--compact', plan['tree_compact'], '--settings', plan['settings_path'], '--archive', str(ARCHIVE), '--report', str(AUDIT)]
    if not AUDIT.exists(): subprocess.run(audit_command, check=True)
    audit = json.loads(AUDIT.read_text())
    if audit['status'] != 'equivalent_on_compared_fields': raise ValueError('Original and independent tree audit has differences')
    if audit['compact_sha256'] != monitor.sha(Path(plan['tree_compact'])):
        raise ValueError('Topology audit refers to a different input')
    for profile in plan['resource_profiles']:
        original = next(x for x in audit['original_abstractions'] if x['street'] == profile['street'])
        if (profile['id'], profile['buckets']) != (original['id'], original['buckets']):
            raise ValueError('Original/static abstraction resource mismatch')
    plan['resource_ids_match_original_settings'] = True
    plan['topology_audit_passed'] = True
    monitor.dump(OUTPUT/'plan.json', plan); monitor.dump(REPORT, plan)
    print(json.dumps({'status': 'audit_passed', 'report': str(AUDIT), 'paired': audit['comparison']['paired']}), flush=True)


def execute():
    plan = json.loads((OUTPUT/'plan.json').read_text())
    if not plan.get('topology_audit_passed'): raise ValueError('Run --validate after original initial archive is ready')
    if verify_build() != plan['build']: raise ValueError('Executable changed after preparation; explicitly review before running')
    if any((OUTPUT/name).exists() for name in ('initialization', 'formal')):
        raise ValueError('Existing benchmark phase; refusing overwrite')
    plan.update(status='running', started_utc=monitor.now()); monitor.dump(REPORT, plan)
    started = time.perf_counter()
    try:
        initialization = monitor.run_phase(plan, 'initialization')
        plan['phases']['initialization'] = initialization; monitor.dump(REPORT, plan)
        init = initialization['summary']
        if init['iteration'] != plan['initialization_samples'] or init['stop_reason'] != 'sample_target':
            raise RuntimeError('Initialization incomplete; formal measurement not started')
        formal = monitor.run_phase(plan, 'formal', resume=OUTPUT/'initialization/checkpoint.bin')
        plan['phases']['formal'] = formal
        final = formal['summary']; value = (final.get('ci') or {}).get('value')
        passed = final.get('stop_reason') == 'ci_target' and final.get('target_reached') and value is not None and value < 10
        plan.update(status='ci_target_reached' if passed else 'stopped_without_ci_target',
            ci_target_reached=bool(passed), ci10_training_seconds=final['elapsed_seconds'] if passed else None,
            ci10_phase_wall_seconds=formal['wall_seconds'] if passed else None,
            continuation_required=not passed and final.get('stop_reason') == 'sample_cap')
    except Exception as exc:
        plan.update(status='failed', error=type(exc).__name__+': '+str(exc)); raise
    finally:
        plan.update(finished_utc=monitor.now(), total_wall_seconds=time.perf_counter()-started)
        monitor.dump(REPORT, plan); monitor.dump(OUTPUT/'report.json', plan)
    print(json.dumps({'status': plan['status'], 'report': str(REPORT),
        'continuation_required': plan.get('continuation_required', False)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--validate', action='store_true')
    group.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.prepare: prepare()
    elif args.validate: validate()
    else: execute()


if __name__ == '__main__': main()
