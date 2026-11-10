"""Summarize retained original 3p40BB GUI/CI evidence; never runs the target."""
from pathlib import Path
from datetime import datetime, timezone
import json

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'analysis/hrc-desktop/three40bb-ci10-original-20261107-run'


def rows(path):
    result = []
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    formal = RUN / 'formal'
    observed = rows(formal / 'win32-observations.jsonl')
    before = next(r for r in observed if r.get('event') == 'before_ok')
    ok = next(r for r in observed if r.get('event') == 'ok_posted')
    latest = next(r for r in reversed(observed) if 'process_cpu_seconds' in r)
    active = [r for r in observed if any('CI:' in x['text'] for x in r.get('rows', []))]
    ci = [r for r in rows(formal / 'original-ci.jsonl')
          if r['index'] >= 0 and r['original_epoch_millis'] >= ok['epoch_millis']]
    for r in ci:
        r['elapsed_since_ok_seconds'] = (r['original_epoch_millis'] - ok['epoch_millis']) / 1000
    hit = next((r for r in ci if r['ci'] is not None and r['ci'] < 10), None)
    end = read(formal / 'observation-result.json') if (formal / 'observation-result.json').exists() else None
    status = 'running'
    if end:
        status = ('completed_target' if hit and not end['cancel_sent'] and
                  end['reason'] == 'observed_idle_with_ci_below_target' else 'stopped_without_verified_target')
    initialization = read(RUN / 'initialization-result.json')
    init_rows = rows(RUN / 'initialization-observations.jsonl')
    init_active = [r for r in init_rows if r['active']]
    after_active = [r for r in init_rows if r['no_operations'] and not r['active'] and
                    init_active and r['elapsed_seconds'] > init_active[-1]['elapsed_seconds']]
    initialization.update({
        'start': read(RUN / 'initialization-start.json'),
        'last_observed_active_seconds': init_active[-1]['elapsed_seconds'] if init_active else None,
        'first_observed_idle_seconds': after_active[0]['elapsed_seconds'] if after_active else None,
        'timing_scope': 'Finish click to GUI idle, including tree construction and original nominal 10m initialization; 0.5s polling, not an instrumented solver boundary.',
        'initialized_in_previous_original_pid': 24968,
        'formal_original_pid': before.get('pid', 41348),
        'formal_reloaded_saved_float32_initial_policy': True,
        'reload_reason': 'Clean original JVM restart preserves strict raw-class hash observation guard after a previous JVM reordered method records during retransformation.',
        'formal_did_not_repeat_initialization': True,
    })
    r = {
        'schema': 'hrc-three40bb-ci10-original-benchmark-v1',
        'updated_utc': datetime.now(timezone.utc).isoformat(), 'status': status,
        'target_jar_sha256': '25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43',
        'hardware': {'cpu': 'Intel Core i5-13600KF', 'physical_cores': 14, 'logical_processors': 20},
        'configuration': {'players': 3, 'stack_bb': 40, 'max_active': 3,
                          'algorithm': 'HRC 4.0 (Default)', 'scope': 'Full Tree',
                          'mode': 'Until CI value is reached', 'ci_target': 10,
                          'comparison': 'CI < 10', 'reset_regret': False,
                          'reset_strategies': False, 'workers': 8},
        'initial_archive': read(RUN / 'initial-archive.json'),
        'initialization': initialization,
        'formal': {
            'pid': 41348, 'ok_epoch_millis': ok['epoch_millis'],
            'ok_utc': datetime.fromtimestamp(ok['epoch_millis'] / 1000, timezone.utc).isoformat(),
            'last_observed_elapsed_seconds': latest['elapsed_seconds'],
            'ci_target_reached': hit is not None,
            'ci_target_reached_elapsed_seconds': hit['elapsed_since_ok_seconds'] if hit else None,
            'last_ci': ci[-1]['ci'] if ci else None,
            'last_ci_run_samples': ci[-1]['original_samples'] if ci else None,
            'process_cpu_seconds_delta': latest['process_cpu_seconds'] - before['process_cpu_seconds'],
            'automatic_wall_cancel_limit_seconds': None,
            'native_solver_boundary_wall_seconds': None,
            'cancel_sent': end['cancel_sent'] if end else False,
            'terminal_observer_result': end,
        },
        'ci_trajectory': ci,
        'last_active_progress_text': [x['text'] for x in active[-1]['rows'] if 'CI:' in x['text']] if active else [],
        'memory': {'before': before['process_memory'], 'last': latest['process_memory'],
                   'scope': 'Whole original JVM with only the three-player benchmark document loaded for formal measurement; PagefileUsage is commit, not observed paging I/O.',
                   'max_observed_working_set_bytes': max(x['process_memory']['WorkingSetSize'] for x in observed if 'process_memory' in x)},
        'observation': {'build': read(ROOT / 'analysis/hrc-deep/ci-runtime-observer-v2-20261107/build-manifest.json'),
                        'agent_events': rows(formal / 'agent-events.jsonl'),
                        'runtime_link_check': read(formal / 'runtime-link-check.json'),
                        'synthetic_index_minus_one_excluded': True,
                        'overhead': 'One append per CI checkpoint and 1s Win32 polling; nonzero and not subtracted.'},
        'limitations': ['CI measures original policy drift, not a statistical confidence interval or exploitability.',
                       'One stochastic original run; no repeated-run uncertainty estimate.',
                       'Formal run reloads the original float32 initial archive; it does not share an identical RNG/initial strategy with independent zero-start training.',
                       'Initial archive strategy is validation evidence only, never independent production training input.',
                       'Initialization and formal run are separately measured; restart, preparation and archive I/O are excluded from formal timing.'],
    }
    for file, key in [('final-archive.json', 'final_archive'), ('cleanup.json', 'cleanup')]:
        if (RUN / file).exists():
            r[key] = read(RUN / file)
    audit = ROOT / 'reports/hrc-three40bb-topology-equivalence-20261107.json'
    if audit.exists():
        r['separate_structure_audit'] = {'path': str(audit.relative_to(ROOT)), 'report': read(audit)}
    path = ROOT / 'reports/hrc-three40bb-ci10-original-20261107.json'
    path.write_text(json.dumps(r, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': status, 'elapsed': latest['elapsed_seconds'],
                      'ci': ci[-1]['ci'] if ci else None, 'target_time': r['formal']['ci_target_reached_elapsed_seconds'],
                      'report': str(path)}))


if __name__ == '__main__':
    main()
