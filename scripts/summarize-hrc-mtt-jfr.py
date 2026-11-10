"""Name original Java execution samples only inside the paired ETW window."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys

JDK=Path('D:/Tools/REA-Research/jdk-21.0.13+9/bin')


def seconds(text):
    match=re.fullmatch(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?',text)
    assert match,text
    return sum(float(v or 0)*unit for v,unit in zip(match.groups(),(3600,60,1)))


def method(frame):
    item=frame['method']
    return item['type']['name'].replace('/','.')+'.'+item['name']+item.get('descriptor','')


def main():
    out=Path(sys.argv[1]).resolve()
    capture=json.loads((out/'capture.json').read_text())
    assert capture['status']=='completed' and capture['jfr_stop']['returncode']==0
    target=out/'jfr-compact.jsonl'
    if not target.exists():
        source=Path(__file__).resolve().parent/'java/MttJfrRead.java'
        classes=out/'reader-classes';classes.mkdir(exist_ok=True)
        subprocess.run([str(JDK/'javac.exe'),'-d',str(classes),str(source)],check=True,capture_output=True,text=True)
        with target.open('w',encoding='utf8') as stream:
            result=subprocess.run([str(JDK/'java.exe'),'-cp',str(classes),'MttJfrRead',str(out/'original.jfr'),
                capture['capture_begin']['utc'],capture['capture_end']['utc'],','.join(map(str,capture['worker_tids']))],
                stdout=stream,stderr=subprocess.PIPE,text=True,timeout=90)
        result.check_returncode()
    events=[json.loads(line) for line in target.read_text(encoding='utf8').splitlines()]
    low=datetime.fromisoformat(capture['capture_begin']['utc']).timestamp()
    high=datetime.fromisoformat(capture['capture_end']['utc']).timestamp()
    workers=set(capture['worker_tids'])
    exclusive,inclusive,native,counts,types=Counter(),Counter(),Counter(),Counter(),Counter()
    durations=Counter();thread_samples=Counter();truncated=0;total=0
    for event in events:
        kind=event['type']
        start=datetime.fromisoformat(event['startTime']).timestamp()
        tid=event['tid']
        duration=event['durationSeconds']
        if duration:
            overlap=max(0,min(start+duration,high)-max(start,low))
            if tid in workers or kind in ('jdk.GarbageCollection','jdk.GCPhasePause','jdk.Compilation'):
                durations[kind]+=overlap
        if not low<=start<=high:
            continue
        counts[kind]+=1
        if tid not in workers:
            continue
        frames=event['frames']
        if kind=='jdk.ExecutionSample':
            total+=1;thread_samples[tid]+=1
            truncated+=event['truncated']
            if frames:
                exclusive[frames[0]]+=1
                inclusive.update(set(frames))
                types[event['topFrameType']]+=1
        elif kind=='jdk.NativeMethodSample' and frames:
            native[frames[0]]+=1
    assert total>100 and len(thread_samples)>=18, 'Insufficient worker execution sample coverage'
    result={'schema':'mtt-jfr-hotspots-v1','stage':capture['stage'],'window_utc':[capture['capture_begin']['utc'],capture['capture_end']['utc']],
            'worker_execution_samples':total,'workers_observed':len(thread_samples),'per_worker_samples':dict(thread_samples),
            'truncated_execution_stacks':truncated,'top_frame_types':dict(types),'event_counts':dict(counts),
            'overlapping_duration_seconds':dict(durations),
            'exclusive_java':[{'method':m,'samples':v,'percent':100*v/total} for m,v in exclusive.most_common(35)],
            'inclusive_java':[{'method':m,'samples':v,'percent':100*v/total} for m,v in inclusive.most_common(30)],
            'native_method_samples':[{'method':m,'samples':v} for m,v in native.most_common(15)],
            'limitations':['JFR ExecutionSample is not the same sampling mechanism as ETW sampled IP.',
                           'Incoming/outgoing scheduling time is taken from ETW; park durations are supporting associations.',
                           'Inclusive frame counts overlap and must not be added as exclusive CPU percentages.']}
    (out/'java-hotspots.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:result[k] for k in ('stage','worker_execution_samples','workers_observed','overlapping_duration_seconds','exclusive_java')}))


if __name__=='__main__':main()
