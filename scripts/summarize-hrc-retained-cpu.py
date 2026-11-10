"""CPU-only analysis of a circular trace whose thread starts were overwritten.

Does not infer thread lifetimes, CPU utilization, wait causes or off-CPU times.
Training samples require an exactly matched user stack containing traversal.
"""
from collections import Counter,defaultdict
import bisect
import hashlib
import importlib.util
import json
import re
import html
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.research-cache/cpu-round4-20261108/nine-etw'

def main():
    cache=OUT/'parsed-solver-events.json'
    p=json.loads(cache.read_text());run=json.loads((OUT/'report.json').read_text())
    assert all(int(h['EventsLost'])==int(h['BuffersLost'])==0 for h in p['headers'])
    spec=importlib.util.spec_from_file_location('etw_symbols',ROOT/'scripts/summarize-hrc-etw.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    tids=set(map(int,p['threads']));samples=[x for x in p['samples'] if x[2] in tids]
    by_key=defaultdict(list)
    for when,cpu,tid,ip in samples:by_key[tid,ip].append(when)
    for times in by_key.values():times.sort()
    offsets=Counter()
    for when,qpc,tid,frames in p['stacks']:
        if not frames:continue
        times=by_key.get((tid,frames[0]),[]);at=bisect.bisect_right(times,when)
        for i in range(max(0,at-3),at):
            if when-times[i]<=100_000:offsets[times[i]-qpc]+=1
    offset,votes=offsets.most_common(1)[0]
    stacks=defaultdict(list)
    for when,qpc,tid,frames in p['stacks']:stacks[qpc+offset,tid].extend(frames)
    name=Path(run['plan']['build']['executable_path']).name.lower()
    images=p['images']
    if not images:
        # Circular capture retained Image UnLoad (opcode 2), which the lifecycle
        # parser deliberately did not use as a load event. Recover its declared
        # address range with explicit PID and filename checks, not an IP guess.
        context=subprocess.check_output(['rg','-m','1','-B','40','-A','10',name+'</Data>',str(OUT/'events.xml')],text=True)
        event=context[context.rfind('<Event xmlns='):]
        data={key:html.unescape(value) for key,value in re.findall(r'<Data Name="([^"]+)">(.*?)</Data>',event)}
        assert int(data['ProcessId'])==run['native']['pid']
        assert data['FileName'].replace('\\','/').split('/')[-1].lower()==name
        images=[dict(base=int(data['ImageBase'],16),size=int(data['ImageSize'],16),path=data['FileName'])]
        (OUT/'recovered-unload-image.json').write_text(json.dumps({'images':images,'event_excerpt':event,'pid':run['native']['pid']},indent=2))
    symbols=m.Symbols(images)
    own=next(x for x in images if x['path'].replace('\\','/').split('/')[-1].lower()==name)
    exclusive,inclusive,lines=Counter(),Counter(),Counter();matched=0;training=0
    for when,cpu,tid,ip in samples:
        frames=stacks.get((when,tid),[])
        if not frames:continue
        matched+=1
        functions={symbols.resolve(x)['symbol'] for x in frames if own['base']<=x<own['base']+own['size']}
        if not any(any(token in function for token in ('Engine::vector','Engine::scalar','ParallelTrainer::adaptive_work','ParallelTrainer::work','Engine::step')) for function in functions):continue
        training+=1;resolved=symbols.resolve(ip);exclusive[resolved['symbol']]+=1;inclusive.update(functions)
        if resolved['line']:lines[resolved['line']['file'],resolved['line']['line']]+=1
    coverage=matched/len(samples)
    if coverage<.99 or training<1000:raise ValueError(f'Insufficient exact stacks: {coverage}, training={training}')
    result={'status':'validated_cpu_only','schema':'retained-training-cpu-v1','pid':run['native']['pid'],
        'input_cache_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'trace_identity':p['source_identity'],
        'executable_sha256':run['executable_sha256'],'all_retained_own_samples':len(samples),
        'matched_own_stacks':matched,'exact_stack_coverage':coverage,'training_stack_samples':training,
        'offset_ticks':offset,'offset_exact_votes':votes,
        'exclusive':[dict(symbol=s,samples=n,percent=100*n/training) for s,n in exclusive.most_common(30)],
        'inclusive_own':[dict(symbol=s,samples=n,percent=100*n/training) for s,n in inclusive.most_common(30)],
        'lines':[dict(file=f,line=l,samples=n,percent=100*n/training) for (f,l),n in lines.most_common(30)],
        'limitations':['Circular trace overwrote thread start events: full lifecycle/off-CPU analysis was rejected.',
            'Only retained exact stacks with traversal are used; this is not a uniformly sampled full-run wall-time share.',
            'Exclusive sampled IP percentages are not cache-miss measurements or recoverable speedup percentages.']}
    (ROOT/'reports/hrc-round4-nine-cpu-stacks-20261108.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','exact_stack_coverage','training_stack_samples','exclusive')},indent=2))

if __name__=='__main__':main()
