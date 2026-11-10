"""Isolated sentinel/immutable-topology factors applied to the measured combination."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
ROUND=ROOT/'.research-cache/throughput-round3-20261108'


def replace(text, old, new):
    assert text.count(old)==1, old[:100]
    return text.replace(old,new,1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',required=True)
    parser.add_argument('--source',type=Path,default=ROUND/'combined-direct23-zero')
    parser.add_argument('--sentinel',action='store_true')
    parser.add_argument('--hoist',action='store_true')
    args=parser.parse_args();out=ROUND/args.name
    out.mkdir(parents=True,exist_ok=False)
    for p in args.source.glob('*.hpp'):shutil.copy2(p,out/p.name)
    cpp=(args.source/'hrc_research_solver.cpp').read_text(encoding='utf-8');original=cpp
    if args.sentinel:
        baseline=(ROUND/'baseline/hrc_research_solver.cpp').read_text(encoding='utf-8')
        candidate=(ROUND/'bucket-sentinel-candidate/hrc_research_solver.cpp').read_text(encoding='utf-8')
        # The worker constructor and both deal-entry resets are independent of
        # the composed atomic/table changes. Copy their exact audited deltas.
        b=baseline.splitlines(True);c=candidate.splitlines(True)
        hand_line=next(i for i,line in enumerate(b) if '    int hand(const Node& n){' in line)
        for tag,a,z,i,j in reversed(difflib.SequenceMatcher(None,b,c,autojunk=False).get_opcodes()):
            if tag=='equal':continue
            old=''.join(b[a:z]);new=''.join(c[i:j])
            # The hand function below replaces the complete eager variant.
            if a>=hand_line or 'hand(' in old or 'hand_cold' in new:continue
            if old:cpp=replace(cpp,old,new)
            else:
                anchor=''.join(b[z:z+3]);cpp=replace(cpp,anchor,new+anchor)
        start=cpp.index('    int hand(const Node& n){')
        end=cpp.index('    const double* terminal(',start)
        begin=candidate.index('    int hand(const Node& n){')
        finish=candidate.index('    const double* terminal(',begin)
        cpp=cpp[:start]+candidate[begin:finish]+cpp[end:]
    if args.hoist:
        start=cpp.index('    double scalar(int id,int target,int depth,double marker){')
        end=cpp.index('    void step(){',start)
        traversal=cpp[start:end]
        traversal=traversal.replace('double p[MAXA],q[MAXA];int h=hand(n);',
                                    'const int actor=n.actor,k=n.k;const int* children=resources().children.data()+n.first;\n        double p[MAXA],q[MAXA];int h=hand(n);')
        traversal=traversal.replace('n.actor','actor').replace('n.k','k')
        # Undo uses preceding the immutable aliases and the alias initializers.
        traversal=traversal.replace('if(!k)return terminal','if(!n.k)return terminal')
        traversal=traversal.replace('const int actor=actor,k=k;','const int actor=n.actor,k=n.k;')
        traversal=traversal.replace('resources().children[n.first+a]','children[a]')
        traversal=traversal.replace('resources().children[n.first+chosen]','children[chosen]')
        cpp=cpp[:start]+traversal+cpp[end:]
    (out/'hrc_research_solver.cpp').write_text(cpp,encoding='utf-8')
    (out/'candidate.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),cpp.splitlines(True),fromfile='source.cpp',tofile='candidate.cpp')),encoding='utf-8')
    exe=out/'solver-hotcache.exe'
    command=['D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe','c++','-O3','-std=c++17','-ffp-contract=off',str(out/'hrc_research_solver.cpp'),'-o',str(exe)]
    subprocess.run(command,check=True,capture_output=True,text=True)
    result={'source':str(args.source),'sentinel':args.sentinel,'hoist':args.hoist,'command':command,
            'production_modified':False,'executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}
    (out/'build.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'exe':str(exe),**result}),flush=True)


if __name__=='__main__':main()
