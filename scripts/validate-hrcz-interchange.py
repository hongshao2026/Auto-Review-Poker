"""Compare an exported HRC core with a real HRC re-save by action path."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_hrcz import SourceArchive
from preflop_lab.hrc_research import decoder


def validate(before,after):
    a,b=SourceArchive(before),SourceArchive(after)
    right={n['path']:i for i,n in b.nodes.items()}
    if set(n['path'] for n in a.nodes.values())!=set(right):
        raise ValueError('Tree paths differ')
    d=decoder();policy_rows=ev_rows=leaf_values=0
    frequency_max=ev_max=leaf_max=0.
    for i,node in a.nodes.items():
        j=right[node['path']];other=b.nodes[j]
        if any(node[k]!=other[k] for k in ('kind','actor','street','incoming_actions')):
            raise ValueError('Saved action differs at '+node['path'])
        if node['kind']=='leaf':
            x,y=a.records[i]['vectors'],b.records[j]['vectors']
            if len(x)!=len(y):raise ValueError('Terminal outcome count differs')
            for p,q in zip(x,y):
                if len(p)!=len(q):raise ValueError('Terminal payoff width differs')
                leaf_max=max(leaf_max,max((abs(v-w) for v,w in zip(p,q)),default=0))
                leaf_values+=len(p)
            continue
        x=d.decode_storage(a.decoder_records[i],node)['buckets']
        y=d.decode_storage(b.decoder_records[j],other)['buckets']
        if len(x)!=len(y):raise ValueError('Strategy bucket count differs')
        for p,q in zip(x,y):
            for field in ('display_strategy','relative_ev_to_action0'):
                v,w=p[field],q[field]
                if (v is None)!=(w is None):raise ValueError('Saved observation coverage differs')
                if v is None:continue
                if len(v)!=len(w):raise ValueError('Strategy dimensions differ')
                difference=max(abs(r-s) for r,s in zip(v,w))
                if field=='display_strategy':frequency_max=max(frequency_max,difference);policy_rows+=1
                else:ev_max=max(ev_max,difference);ev_rows+=1
    return {'schema':'hrcz-real-program-roundtrip-v1',
        'exported':{'path':str(a.path.resolve()),'sha256':a.sha256},
        'resaved_by_hrc':{'path':str(b.path.resolve()),'sha256':b.sha256},
        'nodes':len(a.nodes),'policy_buckets':policy_rows,'relative_ev_buckets':ev_rows,
        'terminal_values':leaf_values,'maximum_frequency_difference':frequency_max,
        'maximum_relative_ev_difference':ev_max,'maximum_terminal_value_difference':leaf_max,
        'state_equal':a.state==b.state,
        'passed':frequency_max==ev_max==leaf_max==0 and a.state==b.state,
        'gui_evidence':'analysis/hrc-desktop/screens/hrcz-our-pko60m-loaded.png',
        'scope':'Core archive tree/actions/policies/payoffs/state after a real desktop HRC Save As; no original RNG equivalence is asserted.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('exported');parser.add_argument('resaved');parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    result=validate(args.exported,args.resaved)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2,allow_nan=False))
    raise SystemExit(0 if result['passed'] else 1)
