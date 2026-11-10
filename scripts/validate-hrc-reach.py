"""Isolated original lq recursive reach and lO/lQ range roundtrip validation."""
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_dynamic import COMBOS
from preflop_lab.hrc_subtree_ranges import extract_reach, range_text
from preflop_lab.hrc_tree import HRCAction,HRCNode,ReplayRules,ReplayState,ImportedTree

BUCKETS=(169,7,11,13)


def probability(node,bucket,edge):
    row=[((node+1)*7+(bucket+3)*(a+1))%11 for a in range(3)]
    return row[edge]/sum(row) if sum(row) else 1/3


def fixture_tree(streets):
    count=len(streets);nodes=[None]*count
    for i,street in enumerate(streets):
        children=[]
        for edge in range(3):
            if i+1<count and edge==i%3:children.append(i+1)
            else:
                child=len(nodes);children.append(child);nodes.append(HRCNode(child,i,None,None,(),(HRCAction(1,(i//2+i)%3,street,0),)))
        nodes[i]=HRCNode(i,i-1,(i//2+i)%3,street,tuple(children),() if i==0 else (HRCAction(1,((i-1)//2+i-1)%3,streets[i-1],0),))
    states=tuple(ReplayState((10000,)*3,(0,)*3,(0,)*3,(False,)*3,n.street or 0,0,10000,(True,)*3,(0,)*3,n.actor) for n in nodes)
    return ImportedTree({},ReplayRules((10000,)*3,10000,5000,BUCKETS),tuple(nodes),states,0,{}, {})


def initial(players,street):
    return [[1.]*169 if street==0 else [(c+3*p)%17/16 for c in range(1326)] for p in range(players)]


def mapping(street,board,player):
    return [-1 if hole&board[street] else (c+player*3+street*5)%BUCKETS[street] for c,hole in enumerate(COMBOS)]


def cases():
    sequences=[(0,0,0,1,1,2,2,3,3),(0,1,2,3),(1,1,1,2,2,3,3),(2,2,3,3),(3,3,3)]
    cards=[(51,28,22,4,1),(0,16,32,44,48),(0,1,2,3,48),(48,49,24,25,26)]
    output=[]
    for si,streets in enumerate(sequences):
        for bi,values in enumerate(cards):
            flop=sum(1<<c for c in values[:3]);board=(0,flop,flop|(1<<values[3]),flop|(1<<values[3])|(1<<values[4]))
            output.append(dict(id=f'chain_{si}_{bi}',streets=streets,board=board))
    return output


def main():
    out=ROOT/'analysis/hrc-deep/reach';out.mkdir(parents=True,exist_ok=True);original=out/'original';original.mkdir(exist_ok=True)
    fixtures=cases();inputs=out/'inputs.tsv';inputs.write_text('\n'.join('\t'.join((c['id'],','.join(map(str,c['streets'])),','.join(map(str,c['board'])))) for c in fixtures)+'\n')
    java=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe');asm=Path(r'D:\Tools\REA-Research\ghidra_12.1.4_PUBLIC\Ghidra\Framework\Emulation\lib\asm-9.7.1.jar')
    classes=out/'classes';classes.mkdir(exist_ok=True);source=ROOT/'scripts/java/OriginalReachProbe.java'
    compile_command=[str(java.with_name('javac.exe')),'-cp',str(asm),'-d',str(classes),str(source)]
    built=subprocess.run(compile_command,capture_output=True,text=True)
    if built.returncode:raise RuntimeError(built.stderr)
    command=[str(java),'-Xmx512m','-cp',str(classes)+';'+str(asm),'OriginalReachProbe',r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar',str(inputs),str(original)]
    run=subprocess.run(command,capture_output=True,text=True,timeout=90);(out/'original.jsonl').write_text(run.stdout)
    if run.returncode:raise RuntimeError(run.stderr)
    records=[json.loads(line) for line in run.stdout.splitlines()];references={r['id']:r for r in records if r['kind']=='result'}
    results=[]
    for case in fixtures:
        tree=fixture_tree(case['streets'])
        for i,street in enumerate(case['streets']):
            if not street:continue
            row=extract_reach(tree,tree.node_path(i),case['board'],lambda node,edge:[probability(node,b,edge) for b in range(BUCKETS[tree.nodes[node].street])],mapping,
                initial_ranges=initial(3,case['streets'][0]))
            payload=struct.pack('<3978d',*(value for seat in row.ranges for value in seat));digest=hashlib.sha256(payload).hexdigest();key=case['id']+'_'+str(i)
            expected=struct.unpack('<3978d',(original/(key+'.bin')).read_bytes());actual=struct.unpack('<3978d',payload)
            results.append(dict(id=key,passed=digest==references[key]['sha256'],original_sha256=references[key]['sha256'],independent_sha256=digest,max_error=max(abs(a-b) for a,b in zip(actual,expected))))
    formatting=[]
    for precision in (0,1,2,3,4,5,6,12):
        threshold=.5*10.**(-precision);values=[0.,math.nextafter(threshold,-math.inf),threshold,math.nextafter(threshold,math.inf),.125,.375,.9999999,1,1.25,1e-20,.2675]+[0.]*(1326-11)
        text,parsed=range_text(values,precision);expected=(original/f'format_{precision}.txt').read_text();expected_bytes=(original/f'format_{precision}.bin').read_bytes()
        formatting.append(dict(precision=precision,passed=text==expected and struct.pack('<1326d',*parsed)==expected_bytes,original_text=expected,independent_text=text))
    report=dict(scope='Original lq full recursive range traversal and lR/lU default ancestry over synthetic policy adapters; final original lq.b board conditioning. Original lO formatting+lQ parse. No application, checkpoint, worker or training.',
        passed=all(r['passed'] for r in results+formatting),chain_count=len(fixtures),query_count=len(results),double_count=len(results)*3978,max_error=max(r['max_error'] for r in results),queries=results,formatting=formatting,
        loaded_class_hashes=[r for r in records if r['kind']=='class'],command=command,compile_command=compile_command,asm_sha256=hashlib.sha256(asm.read_bytes()).hexdigest(),input_sha256=hashlib.sha256(inputs.read_bytes()).hexdigest(),
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,ROOT/'preflop_lab/hrc_subtree_ranges.py',Path(__file__)]})
    (ROOT/'reports/hrc-original-reach-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('passed','chain_count','query_count','double_count','max_error','formatting')},indent=2))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
