"""Summarize existing original HRC CI10 evidence without touching the process."""
from pathlib import Path
import json
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'analysis/hrc-desktop/ci10-original-run-20261106'

def rows(path):
    result=[]
    if path.exists():
        for line in path.read_text(encoding='utf8').splitlines():
            try:result.append(json.loads(line))
            except json.JSONDecodeError:pass
    return result

def main():
    observed=rows(RUN/'win32-observations.jsonl')
    before=next(r for r in observed if r.get('event')=='before_ok')
    ok=next(r for r in observed if r.get('event')=='ok_posted')
    latest=next(r for r in reversed(observed) if 'process_cpu_seconds' in r)
    last_active=next((r for r in reversed(observed) if any('CI:' in x['text'] for x in r.get('rows',[]))),None)
    cancel=next((r for r in observed if r.get('event')=='declared_wall_bound_cancel_posted'),None)
    samples=[r for r in rows(RUN/'original-ci.jsonl') if r['index']>=0 and r['original_epoch_millis']>=ok['epoch_millis']]
    for r in samples:r['elapsed_since_ok_seconds']=(r['original_epoch_millis']-ok['epoch_millis'])/1000
    achieved=next((r for r in samples if r['ci'] is not None and r['ci']<10),None)
    result_path=RUN/'observation-result.json'
    final=json.loads(result_path.read_text(encoding='utf8')) if result_path.exists() else None
    prior=json.loads((ROOT/'reports/hrc-original-40bb-ci-timing.json').read_text(encoding='utf8'))
    artifact=json.loads((ROOT/'analysis/hrc-deep/ci-runtime-observer/build-manifest.json').read_text(encoding='utf8'))
    events=rows(RUN/'agent-events.jsonl')
    installed=next(r for r in events if r['event']=='installed')
    status='running'
    if final:status='completed_target' if final['reason']=='observed_idle_with_ci_below_target' and not final['cancel_sent'] else 'stopped_without_target'
    report={
      'schema':'hrc-nine40bb-ci10-original-benchmark-v1','updated_utc':datetime.now(timezone.utc).isoformat(),
      'status':status,'target_jar_sha256':prior['target_jar_sha256'],
      'configuration':{'players':9,'stack_bb':40,'max_active':4,'algorithm':'HRC 4.0 (Default)',
        'scope':'Full Tree','mode':'Until CI value is reached','ci_target':10,'strict_comparison':'CI < 10',
        'reset_regret':False,'reset_strategies':False,'threads':installed['original_worker_count'],
        'source':prior['initial_archive']['path'],'source_sha256':prior['initial_archive']['sha256'],
        'source_root_counter_float32':prior['initial_archive']['root_counter_float32'],
        'source_initialization_thread_setting':prior['threads'],
        'source_reloaded_after_original_restart':True,'source_policy_quantized_as_saved_float32':True,
        'tree_sha256':prior['initial_archive']['tree_sha256'],'total_nodes':prior['initial_archive']['total_nodes'],
        'decision_nodes':prior['initial_archive']['decision_nodes'],'settings':prior['initial_archive']['settings']},
      'hardware':prior['hardware'],
      'timing':{'ok_epoch_millis':ok['epoch_millis'],'ok_utc':datetime.fromtimestamp(ok['epoch_millis']/1000,timezone.utc).isoformat(),
        'last_observed_elapsed_seconds':latest['elapsed_seconds'],
        'ci_target_reached_elapsed_seconds':achieved['elapsed_since_ok_seconds'] if achieved else None,
        'ci_target_reached':achieved is not None,'last_ci':samples[-1]['ci'] if samples else None,
        'last_ci_run_samples':samples[-1]['original_samples'] if samples else None,
        'last_ci_elapsed_since_ok_seconds':samples[-1]['elapsed_since_ok_seconds'] if samples else None,
        'wall_bound_cancel_elapsed_seconds':cancel['elapsed_seconds'] if cancel else None,
        'count_note':'CI records contain original run-loop counts. The saved root counter is float32, includes initialization and may include work after the last CI snapshot; these are not interchangeable exact counters.',
        'native_solver_wall_seconds':None,
        'native_solver_wall_note':'No original method-boundary timer was installed; GUI OK wall time and process CPU time are reported separately.',
        'process_cpu_seconds_delta':latest['process_cpu_seconds']-before['process_cpu_seconds'],
        'emergency_wall_bound_seconds':3600,'observer_result':final},
      'ci_trajectory':samples,
      'latest_visible_progress':[r['text'] for r in latest['rows'] if 'CI:' in r['text']],
      'last_active_visible_progress':[r['text'] for r in last_active['rows'] if 'CI:' in r['text']] if last_active else [],
      'memory':{'before':before['process_memory'],'last':latest['process_memory'],
        'maximum_observed_working_set_bytes':max(r['process_memory']['WorkingSetSize'] for r in observed if 'process_memory' in r),
        'maximum_observed_commit_bytes':max(r['process_memory']['PagefileUsage'] for r in observed if 'process_memory' in r),
        'scope':'Whole original HRC process with only the selected benchmark hand loaded after restart; commit/PagefileUsage is not a measurement of disk paging.'},
      'observation':{'agent_build':artifact,'agent_events':events,
        'runtime_link_check':json.loads((RUN/'runtime-link-check.json').read_text(encoding='utf8')),
        'method':'Only original mr.<init>(IJJD)V has an appended observer call immediately before RETURN; original fields, inputs, output and solver control flow are unchanged.',
        'values':'Fourth constructor argument is the exact smoothed mq.a:D used by the original CI stopping predicate and display.',
        'overhead':'One small append per CI checkpoint, outside hot traversal; nonzero instrumentation and Win32 polling overhead are disclosed, not subtracted.',
        'polling':'Win32 cached text/process counters once per second, without pywinauto traversal, JDK attach, GC or compilation during sampling.',
        'synthetic_link_check_excluded':True,
        'screenshot_caveat':'The first automatic frame used DPI-virtualized coordinates and is not relied on. progress-dpi-aware-confirmation.png is the verified selected-dialog screenshot; future observer script sets DPI awareness explicitly.'},
      'user_document_preservation':{'path':'analysis/hrc-desktop/user-Hand1-preserved-before-thread-restart-20261106.hrcz',
        'original_unnamed_document_saved_to_new_unique_path':True,'existing_named_files_overwritten':False},
      'thread_preference':{'before':0,'during':8,'requires_restart':True,'runtime_verified':True,
                           'restore_after_measurement':0},
      'limitations':['This is one stochastic original run, not a repeated-run confidence interval.',
        'CI is original recent-policy drift, not statistical confidence or exploitability.',
        'No target-achievement duration may be claimed while ci_target_reached is false.',
        'Original GUI ETA is extrapolation, not a measured completion time.',
        'Source10m initialization was performed previously; this trial excludes initialization and archive loading time.']}
    for filename,key in [('final-archive.json','final_archive'),
                         ('initial-final-tree-identity.json','initial_final_tree_identity'),
                         ('cleanup.json','cleanup')]:
        path=RUN/filename
        if path.exists():report[key]=json.loads(path.read_text(encoding='utf8'))
    if report.get('cleanup',{}).get('thread_preference_restored')==0:
        report['thread_preference'].update({'after':0,'reopened_ui_verified':True,'effective_next_restart':True})
    cleanup=report.get('cleanup',{})
    report['observation']['cleanup']={key:cleanup.get(key) for key in
        ('hook_removed','hook_cleanup_note','test_document_closed','gc_after_timing_and_document_close')}
    report['user_document_preservation'].update({
        'restored_to_display':cleanup.get('user_hand1_restored_to_display',False),
        'restored_idle_verified':cleanup.get('user_hand1_idle_verified',False),
        'restore_screenshot':cleanup.get('user_hand1_restored_screenshot'),
        'backup_sha256':cleanup.get('user_hand1_backup_sha256'),
        'backup_bytes':cleanup.get('user_hand1_backup_bytes'),
        'restore_method':cleanup.get('user_hand1_restored_via')})
    paired=ROOT/'reports/hrc-nine40bb-topology-equivalence-20261106.json'
    if paired.exists():
        audit=json.loads(paired.read_text(encoding='utf8'))
        report['separate_cross_engine_structure_audit']={
            'path':str(paired.relative_to(ROOT)),'status':audit['status'],
            'comparison':audit['comparison'],
            'scope':'Structure, abstraction counts and terminal settlement inputs; not full strategy or convergence equivalence.'}
    output=ROOT/'reports/hrc-nine40bb-ci10-original-20261106.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':status,'last_elapsed':latest['elapsed_seconds'],'last_ci':samples[-1]['ci'] if samples else None,'ci_target_reached':achieved is not None,'report':str(output)}))

if __name__=='__main__':main()
