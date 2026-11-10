"""Measure shared-policy scaling and descriptive strategy drift on fixed scenes."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import runpy
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_native import build,read_node


def distance(left,right):
    rows=[];aggregate_left=[0.]*left['actions'];aggregate_right=[0.]*left['actions']
    for a,b in zip(left['hands'],right['hands']):
        h=a['bucket'];r,c=divmod(h,13);weight=6 if r==c else 4 if r>c else 12
        pa,pb=a['display_strategy'],b['display_strategy']
        rows.append((weight,sum(abs(x-y) for x,y in zip(pa,pb))/len(pa)))
        for i in range(len(pa)):aggregate_left[i]+=weight*pa[i]/1326;aggregate_right[i]+=weight*pb[i]/1326
    return {'combo_weighted_hand_action_mae_pp':100*sum(w*d for w,d in rows)/sum(w for w,_ in rows),
        'action_totals_left':aggregate_left,'action_totals_right':aggregate_right,
        'aggregate_action_mae_pp':100*sum(abs(x-y) for x,y in zip(aggregate_left,aggregate_right))/len(aggregate_left)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples',type=int,default=2_000_000);p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--finalize-existing',action='store_true',help='Finish postprocessing existing partial measurements without rerunning trials')
    args=p.parse_args()
    if not 1000<=args.samples<=10_000_000 or not 1<=args.repeats<=5:p.error('Invalid benchmark budget')
    folder=args.output.resolve();folder.mkdir(parents=True,exist_ok=args.finalize_existing)
    helper=runpy.run_path(str(ROOT/'scripts/audit-hrc-performance.py'));exe=build()
    report={'schema':'hrc-shared-policy-parallel-benchmark-v1','samples_per_run':args.samples,
        'repeats':args.repeats,'seed':43,'executable':str(exe),'executable_sha256':helper['sha'](exe),
        'source_sha256':{str(f.relative_to(ROOT)):helper['sha'](f) for f in (ROOT/'native').iterdir() if f.is_file()},
        'trials':[],'limits':['Different thread schedules change the strategy and RNG consumption; parallel checkpoints are not expected to match.',
            'Strategy distances are descriptive conditional differences, not exploitability or a convergence guarantee.',
            'Fixed trees, no affinity/clock control; memory/CPU metrics include native startup, training timer excludes startup.']}
    if args.finalize_existing:
        report=json.loads((folder/'partial.json').read_text(encoding='utf-8'))
        if report['executable_sha256']!=helper['sha'](exe) or len(report['trials'])!=8*args.repeats:
            raise ValueError('Different executable or incomplete measurements')
    for repeat in range(0 if args.finalize_existing else args.repeats):
        order=[1,2,4,8];order=order[repeat:]+order[:repeat]
        for scene,tree in helper['SCENES'].items():
            for count in order:
                out=folder/f'{scene}-{count}-{repeat}'
                row=helper['run_case'](exe,tree,out,args.samples,43,threads=count)
                root=read_node(out,0)
                if root['updates']!=args.samples or sum(h['visits'] for h in root['hands'])!=args.samples:
                    raise ValueError('Lost shared updates')
                row.update(scene=scene,threads=count,repeat=repeat,output=str(out));report['trials'].append(row)
                (folder/'partial.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps({'scene':scene,'threads':count,'repeat':repeat,'seconds':row['native_seconds'],
                    'peak_mib':row['peak_working_set_bytes']/1048576,'cpus':row['average_logical_cpus']}),flush=True)
    report['results']={};report['strategy_comparisons']={}
    for scene,tree in helper['SCENES'].items():
        data={}
        for count in (1,2,4,8):
            rows=[r for r in report['trials'] if r['scene']==scene and r['threads']==count]
            data[count]={'median_seconds':statistics.median(r['native_seconds'] for r in rows),
                'median_peak_mib':statistics.median(r['peak_working_set_bytes']/1048576 for r in rows),
                'median_logical_cpus':statistics.median(r['average_logical_cpus'] for r in rows)}
        for value in data.values():value['speedup']=data[1]['median_seconds']/value['median_seconds']
        report['results'][scene]=data
        if (tree.parent/'tree.json').exists():compact=json.loads((tree.parent/'tree.json').read_text(encoding='utf-8'))
        else:
            from preflop_lab.hrc_tree import load_hrc_tree
            manifest=json.loads((tree.parent/'manifest.json').read_text(encoding='utf-8'))
            compact=load_hrc_tree(manifest['topology_source']['source_path']).compact_export()
        nodes=compact['nodes'];btn=compact['root']
        while nodes[btn]['children'] and nodes[btn]['actor']!=compact['players']-3:btn=nodes[btn]['children'][0]
        ids={'root':compact['root'],'btn_folded_to':btn}
        base=next(r for r in report['trials'] if r['scene']==scene and r['threads']==1)
        noise_folder=folder/f'{scene}-serial-seed44'
        helper['run_case'](exe,tree,noise_folder,args.samples,44)
        comparisons={}
        for label,id in ids.items():
            reference=read_node(base['output'],id)
            comparisons[label]={'node_id':id,'serial_seed43_vs44':distance(reference,read_node(noise_folder,id)),
                'parallel_vs_serial':[{'threads':r['threads'],'repeat':r['repeat'],**distance(reference,read_node(r['output'],id))}
                    for r in report['trials'] if r['scene']==scene and r['threads']>1]}
        report['strategy_comparisons'][scene]=comparisons
    (folder/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'completed':True,'results':report['results'],'report':str(folder/'report.json')}),flush=True)


if __name__=='__main__':main()
