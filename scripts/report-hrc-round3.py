"""Report measured throughput, complete CI10 runs and held-out HRC comparisons."""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))


def main():
    matrix=read('reports/hrc-throughput-round3-final-20261108.json')
    assert matrix['status']=='completed' and matrix['serial_equal']
    original=read('reports/hrc-three40bb-ci10-original-20261107.json')
    previous=read('reports/hrc-three40bb-ci10-node-lock-20261108.json')
    old_history=[json.loads(line) for line in (ROOT/'.research-cache/three40bb-ci10-node-lock-20261108/formal/ci-snapshots.jsonl').read_text().splitlines()]
    original_first=original['formal']['ci_target_reached_elapsed_seconds']
    rows=[dict(engine='HRC historical / 8 workers',case='hrc8',threads=8,
               first_ci10_seconds=original_first,ci=original['formal']['last_ci'],
               samples=original['formal']['last_ci_run_samples'],
               cpu_seconds=original['formal']['process_cpu_seconds_delta']),
          dict(engine='Previous native / 8 workers',case='previous8',threads=8,
               first_ci10_seconds=old_history[-1]['timestamp_ms']/1000,ci=previous['ci'],samples=previous['formal_new_samples'],
               cpu_seconds=previous['formal']['process_cpu_seconds'])]
    curves=[];strategies=[]
    formal_paths=[p for p in (ROOT/'reports').glob('hrc-three40bb-ci10-round3-current*-20261108.json')
                  if re.fullmatch(r'hrc-three40bb-ci10-round3-current\d+-20261108.json',p.name)]
    for path in sorted(formal_paths,key=lambda p:int(re.search(r'current(\d+)',p.name).group(1))):
        run=json.loads(path.read_text(encoding='utf-8'))
        assert run['status']=='ci_target_reached' and all(run['preserved_unchanged'].values())
        phase=run['formal'];summary=phase['summary']
        history=[json.loads(line) for line in (Path(phase['output'])/'ci-snapshots.jsonl').read_text().splitlines()]
        threads=run['plan']['training_threads'];case=run['case']
        rows.append(dict(engine=f'Round 3 / {threads} workers',case=case,threads=threads,
                         first_ci10_seconds=history[-1]['timestamp_ms']/1000,
                         training_seconds=summary['elapsed_seconds'],wall_seconds=phase['wall_seconds'],
                         ci=run['ci'],samples=run['formal_new_samples'],
                         cpu_seconds=phase['process_cpu_seconds'],average_cores=phase['average_logical_cpus'],
                         peak_working_set_bytes=phase['peak_working_set_bytes']))
        curves.append((f'Round 3 / {threads} workers',[(r['timestamp_ms']/60000,r['value']) for r in history]))
        policy_path=ROOT/f'reports/hrc-three40bb-ci10-round3-{case}-strategy-20261108.json'
        if policy_path.is_file():
            policy=json.loads(policy_path.read_text(encoding='utf-8'))
            old_policy=read('reports/hrc-three40bb-ci10-node-lock-strategy-20261108.json')
            selected=[]
            for new in policy['selected']:
                old=next(n for n in old_policy['selected'] if n['slug']==new['slug'])
                selected.append(dict(slug=new['slug'],label=new['label'],
                                     hrc_frequency=new['metrics']['hrc_frequency'],frequency=new['metrics']['ours_frequency'],
                                     old_hand_TV_pp=old['metrics']['combo_weighted_hand_TV_pp'],
                                     new_hand_TV_pp=new['metrics']['combo_weighted_hand_TV_pp']))
            strategies.append(dict(case=case,report=str(policy_path),nodes=policy['preflop_nodes_compared'],selected=selected))
    for row in rows:
        row['time_relative_to_historical_hrc8']=row['first_ci10_seconds']/original_first
        row['cpu_seconds_per_million']=row['cpu_seconds']/(row['samples']/1e6)
    result={'schema':'hrc-round3-throughput-and-ci10-v1','fixed_samples':matrix['medians'],
            'fixed_sample_threads':matrix['case_threads'],'formal':rows,'strategies':strategies,
            'accepted':['Atomic strategy reads with serialized writers and locked fallback',
                        'Direct two/three-action reads; finite one-zero division shortcut',
                        'Separate cache lines for immutable metadata and writer scalar counters',
                        'Immutable primitive board-row map, original compressed bucket payload',
                        'Eager static buckets only for two/three seats',
                        'Budgeted immutable terminal-pointer cache'],
            'not_accepted':['Full-column expansion: slower in controlled matrix',
                            'Fixed writer templates: no measured gain',
                            'Sentinel-only bucket path: slower than selected eager combination',
                            'Atomic-all-cell and 16-stripe writers: only about 4% in longer screening',
                            'Hoisted traversal metadata: small isolated signal, no combined acceptance test'],
            'correctness':{'core_regression_passed':282,'atomic_read_passed':8,'flat_map_passed':11,
                           'msvc_skipped':1,'msvc_reason':'Installed toolset lacks Windows SDK/UCRT; forced-disabled GNU route tested instead',
                           'serial_checkpoint_equal':matrix['serial_equal'],'initial_preserved':matrix['initial_unchanged'],
                           'prior_formal_preserved':matrix['formal_unchanged']},
            'evidence':{'jar_sha256':'25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43',
                        'rea_bundle':'analysis/hrc-deep/round3-storage-20261108-rea-evidence.json',
                        'bytecode_review':'research/HRC-ROUND3-ORIGINAL-STORAGE.md',
                        'abstraction_review':'research/HRC-ROUND3-ABSTRACTION-ENGINEERING.md'},
            'limits':['Historical HRC timing was not rerun during this round; clocks/affinity/background user applications differ.',
                      '8-worker comparison separates implementation gains from adding more workers.',
                      'One formal trajectory per worker count; asynchronous interleavings and mixed snapshots differ.',
                      'CI is recent policy drift, not exploitability or confidence-interval error.',
                      'Single-thread parity and held-out strategy comparisons do not prove complete HRC equivalence.',
                      'REA identity/inventory and shell bytecode observations are separate evidence sources; JEB provider unavailable.']}
    mature_path=ROOT/'reports/hrc-throughput-round3-mature-20261108.json'
    if mature_path.is_file():
        mature=json.loads(mature_path.read_text(encoding='utf-8'))
        assert mature['status']=='completed' and mature['serial_equal'] and mature['initial_unchanged']
        result['mature_fixed_samples']={'initial_samples':mature['initial_samples'],'medians':mature['medians'],
                                        'report':str(mature_path)}
        result['limits'].append('Historical full-run wall times do not isolate implementation gains; the interleaved fixed-state matrices do.')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,(left,right)=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
    original_curve=[(p['elapsed_since_ok_seconds']/60,p['ci']) for p in original['ci_trajectory']]
    for label,points in [('HRC historical / 8 workers',original_curve),
                          ('Previous native / 8 workers',[(p['timestamp_ms']/60000,p['value']) for p in old_history]),*curves]:
        left.plot(*zip(*points),label=label,linewidth=1.6)
    left.axhline(10,color='#64748b',linestyle='--',linewidth=1)
    left.set(xlabel='Formal run time (minutes)',ylabel='CI (recent policy drift)',yscale='log',title='3 players / 40BB / full tree')
    left.legend(frameon=False,fontsize=8);left.grid(alpha=.18,which='both')
    chart_medians=result.get('mature_fixed_samples',{}).get('medians',matrix['medians'])
    names=list(chart_medians);values=[chart_medians[n]['million_samples_per_second'] for n in names]
    bars=right.bar(names,values,color=['#94a3b8']+['#2563eb']*(len(names)-1),width=.65)
    right.bar_label(bars,fmt='%.2f',padding=3,fontsize=9)
    right.set(ylabel='Million new samples / second',
              title=('Same mature checkpoint: 20m x 3' if 'mature_fixed_samples' in result else '20m samples per trial, median of 3'),
              ylim=(0,max(values)*1.18))
    right.tick_params(axis='x',labelrotation=25);right.grid(axis='y',alpha=.18);right.set_axisbelow(True)
    fig.text(.5,-.035,'Historical HRC reference; one formal run per implementation/thread count. CI is not exploitability.',ha='center',fontsize=8)
    prefix=ROOT/'reports/hrc-round3-comparison-20261108'
    fig.savefig(prefix.with_suffix('.png'),dpi=170,bbox_inches='tight');plt.close(fig)
    result['figure']=str(prefix.with_suffix('.png'))
    prefix.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'formal':rows,'fixed_samples':matrix['medians'],'report':str(prefix.with_suffix('.json'))},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
