"""Compare independently generated terminal vectors with saved original HRC data.

Saved format1024 arrays are only the oracle after generation; they never enter
the native input. Settings and generic independently replayed topology are input.
"""
from array import array
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_hrcz_tree import load_archive_tree
from preflop_lab.hrc_hrcz_settings import settings_to_config
from preflop_lab.hrc_hrcz_storage import decode_nodedata,storage_configuration,encode_payload
from preflop_lab.hrc_hrcz_leaves import generate_leaves,evaluate_baseline,build
from preflop_lab.hrc_rake import rake_spec,add_terminal_context

FILES=['hu10bb-pushfold-initial.hrcz','eight15bb-raise-call-postflop-60m.hrcz',
       'eight15bb-pko-50-30-20-initial.hrcz']


def independent_input(path):
    tree=load_archive_tree(path);compact=tree.compact_export()
    cfg=settings_to_config(tree.settings,tree.archive_state)
    if cfg['utility']!='chips':
        compact['equity']={'mode':cfg['utility'],'payouts':cfg['payouts'],
                          'other_stacks':[v*10000 for v in cfg['other_stacks']],
                          'bounty':deepcopy(cfg['bounty'])}
    if cfg.get('fgs',{}).get('enabled'):
        from preflop_lab.hrc_fgs_config import fgs_spec
        compact['fgs']=fgs_spec(cfg['fgs'],compact['equity'],tree,chip_scale=10000)
    add_terminal_context(compact,tree,rake_spec(cfg))
    return tree,compact,cfg


def check_archive(name,folder):
    path=ROOT/'analysis/hrc-desktop'/name
    tree,compact,cfg=independent_input(path)
    start=time.perf_counter()
    generated,baseline,metadata=generate_leaves(compact,ROOT/'.research-cache/abstractions',folder/name[:-5])
    seconds=time.perf_counter()-start
    # Only now read the original payoffs/policies for comparison.
    with zipfile.ZipFile(path) as archive:data=archive.read('nodedata.dat')
    original,_=decode_nodedata(data,{n['id']:len(n['children']) for n in compact['nodes']})
    storage=storage_configuration(original,compact,utility_scale=compact['big_blind']/100 if cfg['utility']=='chips' else 1.,utility_offsets=baseline)
    mismatches=[];max_error=0.;values=0;equal=0;source_hash=hashlib.sha256();generated_hash=hashlib.sha256()
    for node,record in generated.items():
        expected=original[node]
        a,b=encode_payload(record),encode_payload(expected)
        source_hash.update(node.to_bytes(4,'little')+b);generated_hash.update(node.to_bytes(4,'little')+a)
        if a==b:equal+=1
        aa,bb=array('f'),array('f');aa.frombytes(a);bb.frombytes(b)
        if len(aa)!=len(bb):raise AssertionError('Terminal dimensions differ')
        error=max((abs(x-y) for x,y in zip(aa,bb)),default=0.);max_error=max(max_error,error);values+=len(aa)
        if a!=b and len(mismatches)<20:
            mismatches.append({'node_id':node,'max_abs_error':error,'first_differences':
                [{'vector':i//compact['players'],'seat':i%compact['players'],'independent':x,'original':y}
                 for i,(x,y) in enumerate(zip(aa,bb)) if x!=y][:8],
                'terminal':compact['terminals'][compact['nodes'][node]['terminal_id']]})
    baseline_only=evaluate_baseline(compact,ROOT/'.research-cache/abstractions',folder/(name[:-5]+'-baseline'))
    original_baseline=tree.archive_state.get('eqpre')
    baseline_error=max(abs(a-b) for a,b in zip(baseline,original_baseline)) if original_baseline else None
    return {'archive':name,'archive_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'utility':cfg['utility'],'bounty':cfg['bounty'],'terminal_records':len(generated),
            'vectors':metadata['vectors'],'float32_values':values,'exact_records':equal,
            'max_abs_float32_error':max_error,'baseline':baseline,'original_baseline':original_baseline,
            'baseline_max_error':baseline_error,'baseline_only_equal':baseline_only==baseline,
            'storage_trainable':storage['trainable'],'storage_reasons':storage['reasons'],
            'original_payloads_sha256':source_hash.hexdigest(),'generated_payloads_sha256':generated_hash.hexdigest(),
            'seconds':seconds,'first_mismatches':mismatches,
            'passed':equal==len(generated) and baseline_only==baseline and (baseline_error or 0)<1e-9}


def main():
    folder=ROOT/'analysis/hrc-deep/hrcz-leaves';folder.mkdir(parents=True,exist_ok=True)
    results=[check_archive(name,folder) for name in FILES]
    report={'scope':'Original saved format1024 vectors versus independent production settlement/equity; no original class or original terminal value used by generation.',
            'ordering':'mh live seats sorted by cumulative paid descending, seat ascending; me base-3 best-so-far rank representatives.',
            'native_executable_sha256':hashlib.sha256(build().read_bytes()).hexdigest(),
            'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                 [ROOT/'native/hrc_hrcz_leaves.cpp',ROOT/'preflop_lab/hrc_hrcz_leaves.py',ROOT/'native/hrc_research_solver.cpp',ROOT/'native/hrc_equity.hpp']},
            'cases':results,'passed':all(x['passed'] for x in results),
            'terminal_records':sum(x['terminal_records'] for x in results),
            'float32_values':sum(x['float32_values'] for x in results)}
    target=ROOT/'reports/hrc-original-hrcz-leaves-validation.json';target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({**{k:v for k,v in report.items() if k not in ('source_sha256','cases')},'cases':[{k:v for k,v in c.items() if k not in ('first_mismatches','bounty','original_baseline','baseline')} for c in results]},indent=2))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
