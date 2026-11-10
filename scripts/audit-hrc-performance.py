"""Bounded local A/B audit; production source and build flags are unchanged.

Compare the current binary, CPU-specific compilation and an experimental
constant-terminal cache. Require identical native checkpoint bytes for every
scene/seed/sample budget. No HRC process or original strategy is used.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_native import build

SCENES={
    'eight15bb_chip':ROOT/'.research-cache/runs/bd7346fe454144f98a80bfd81d1c31c5/tree.bin',
    'eight15bb_pko':ROOT/'.research-cache/runs/17d7a7c0226b491282320cace6306346/tree.bin',
}


class Memory(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[
        (name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize',
        'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]


kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
kernel.GetProcessTimes.restype=wintypes.BOOL
psapi=ctypes.WinDLL('psapi',use_last_error=True)
psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype=wintypes.BOOL


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def cpu_seconds(handle):
    values=[wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle,*[ctypes.byref(v) for v in values]):return None
    return sum((v.dwHighDateTime<<32)|v.dwLowDateTime for v in values[2:])*1e-7


def compile_variant(source,target,flags,include_dir=None):
    zig=Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
    command=[str(zig),'c++','-O3','-std=c++17','-ffp-contract=off',*flags,
             '-I',str(include_dir or ROOT/'native'),str(source),'-o',str(target)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=180)
    if result.returncode:raise RuntimeError(result.stderr[-5000:])
    return command


def constant_variant(text):
    replacements=[
        ('bool synthetic=false;','bool synthetic=false,constant_value=false;'),
        ('if(root<0||root>=int(nn))',
         'for(auto& t:terms)t.constant_value=!raked&&std::all_of(t.pots.begin(),t.pots.end(),[](const Pot& p){return !(p.eligible&(p.eligible-1));});\n        if(root<0||root>=int(nn))'),
        ('if(t.cached_deal==epoch)return t.value.data();',
         'if(t.cached_deal==epoch||(!tree.fgs&&t.constant_value&&t.cached_deal!=UINT64_MAX))return t.value.data();'),
    ]
    for before,after in replacements:
        if text.count(before)!=1:raise ValueError('Performance patch anchor changed: '+before)
        text=text.replace(before,after)
    return text


def lazy_rank_variant(text):
    declaration='bool bucket_ready[4]{},rank_ready=false;'
    reset='bucket_ready[0]=true;for(int st=1;st<4;++st)bucket_ready[st]=false;rank_ready=false;'
    evaluate='if(!rank_ready){for(int p=0;p<tree.players;++p)rank[p]=hrc_cards::rank7(holes[p]|board[3]);rank_ready=true;}'
    if text.count(declaration)!=1 or text.count(reset)!=2 or text.count(evaluate)!=2:
        raise ValueError('Lazy rank patch anchors changed')
    text=text.replace(declaration,declaration+'uint16_t rank_mask=0;')
    text=text.replace(reset,reset+'rank_mask=0;')
    helper='''void ensure_ranks(uint16_t need){
        if(rank_ready)return;
        uint16_t missing=need&~rank_mask;
        while(missing){int p=hrc_cards::lowbit(missing);missing&=missing-1;rank[p]=hrc_cards::rank7(holes[p]|board[3]);}
        rank_mask|=need;rank_ready=rank_mask==((1u<<tree.players)-1);
    }
    '''
    text=text.replace('int hand(const Node& n)',helper+'int hand(const Node& n)')
    text=text.replace(evaluate,'ensure_ranks(uint16_t((1u<<tree.players)-1));',1)
    return text.replace(evaluate,'ensure_ranks(uint16_t(pot.eligible));',1)


def run_case(executable,tree,folder,samples,seed,*,threads=1,max_memory_bytes=1<<30,constant_scalar_shortcuts=True):
    folder.mkdir(parents=True,exist_ok=False)
    command=[str(executable),str(tree),str(ROOT/'.research-cache/abstractions'),
             str(samples),str(seed),str(folder),'v4']
    if threads>1 or max_memory_bytes!=1<<30 or not constant_scalar_shortcuts:
        command.extend(['-','0','0','-1','-1','-1',str(max_memory_bytes),str(threads),str(int(constant_scalar_shortcuts))])
    started=time.perf_counter()
    # Long runs must drain stdout: a full progress pipe would otherwise stall
    # the native process while the resource sampler waits for it to finish.
    with (folder/'stdout.jsonl').open('w',encoding='utf-8') as out, (folder/'stderr.log').open('w',encoding='utf-8') as err:
        process=subprocess.Popen(command,stdout=out,stderr=err,text=True)
        peak=0
        while process.poll() is None:
            memory=Memory();memory.cb=ctypes.sizeof(memory)
            if psapi.GetProcessMemoryInfo(process._handle,ctypes.byref(memory),memory.cb):
                peak=max(peak,memory.PeakWorkingSetSize)
            time.sleep(.04)
        process.wait()
    stdout=(folder/'stdout.jsonl').read_text(encoding='utf-8')
    stderr=(folder/'stderr.log').read_text(encoding='utf-8')
    elapsed=time.perf_counter()-started
    cpu=cpu_seconds(process._handle)
    if process.returncode:raise RuntimeError(stderr[-3000:])
    rows=[json.loads(line) for line in stdout.splitlines() if line.strip().startswith('{')]
    last=next(r for r in reversed(rows) if r['kind']=='finished')
    if last['iteration']!=samples or last.get('cancelled'):raise ValueError('Incomplete benchmark')
    return {'command':command,'wall_seconds':elapsed,'process_cpu_seconds':cpu,
        'average_logical_cpus':cpu/elapsed if cpu is not None else None,
        'peak_working_set_bytes':peak,'native_seconds':last['elapsed_seconds'],
        'samples_per_second':samples/last['elapsed_seconds'],
        'checkpoint_sha256':sha(folder/'checkpoint.bin'),
        'summary':last}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=500000)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--seed',type=int,default=43)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path,help='Native source snapshot before production optimization; use benchmark-hrc-optimization.py for current kernels')
    parser.add_argument('--variants',nargs='+',choices=['baseline','native_cpu','constant_cache','lazy_ranks','combined'],
        default=['baseline','native_cpu','constant_cache'])
    args=parser.parse_args()
    if not 1000<=args.samples<=2000000 or not 1<=args.repeats<=5:parser.error('Bounded audit budget')
    folder=args.output.resolve();folder.mkdir(parents=True,exist_ok=False)
    source_dir=args.source_dir.resolve() if args.source_dir else ROOT/'native'
    source=source_dir/'hrc_research_solver.cpp'
    text=source.read_text(encoding='utf-8')
    if 'card_independent' in text:
        parser.error('This historical audit needs pre-optimization sources via --source-dir; use benchmark-hrc-optimization.py to compare production binaries')
    if args.source_dir:
        baseline=folder/'baseline.exe'
        compile_variant(source,baseline,[],source_dir)
    else:baseline=build()
    binaries={'baseline':baseline}
    commands={}
    for name in args.variants:
        if name=='baseline':continue
        variant_text=text
        if name in ('constant_cache','combined'):variant_text=constant_variant(variant_text)
        if name in ('lazy_ranks','combined'):variant_text=lazy_rank_variant(variant_text)
        src=folder/f'{name}.cpp';src.write_text(variant_text,encoding='utf-8')
        flags=['-march=native'] if name=='native_cpu' else []
        binaries[name]=folder/f'{name}.exe'
        commands[name]=compile_variant(src,binaries[name],flags,source_dir)
        print(json.dumps({'kind':'compiled','variant':name}),flush=True)
    report={'schema':'hrc-local-performance-audit-v1','samples':args.samples,
        'seed':args.seed,'repeats':args.repeats,'production_changed':False,
        'compiler_commands':commands,'source_sha256':sha(source),
        'executables':{n:{'path':str(p),'sha256':sha(p)} for n,p in binaries.items()},
        'scene_sha256':{n:sha(p) for n,p in SCENES.items()},'trials':[]}
    for repeat in range(args.repeats):
        order=list(binaries);order=order[repeat%len(order):]+order[:repeat%len(order)]
        for scene,tree in SCENES.items():
            for variant in order:
                result=run_case(binaries[variant],tree,folder/f'{scene}-{variant}-{repeat}',args.samples,args.seed)
                result.update(scene=scene,variant=variant,repeat=repeat)
                report['trials'].append(result)
                print(json.dumps({'kind':'trial','scene':scene,'variant':variant,'repeat':repeat,
                    'seconds':result['native_seconds'],'peak_mib':result['peak_working_set_bytes']/1048576,
                    'cpus':result['average_logical_cpus']}),flush=True)
    report['results']={}
    for scene in SCENES:
        results={}
        expected=next(t['checkpoint_sha256'] for t in report['trials'] if t['scene']==scene and t['variant']=='baseline')
        for variant in binaries:
            trials=[t for t in report['trials'] if t['scene']==scene and t['variant']==variant]
            results[variant]={'median_native_seconds':statistics.median(t['native_seconds'] for t in trials),
                'minimum_native_seconds':min(t['native_seconds'] for t in trials),
                'maximum_native_seconds':max(t['native_seconds'] for t in trials),
                'identical_checkpoint':all(t['checkpoint_sha256']==expected for t in trials),
                'median_wall_seconds':statistics.median(t['wall_seconds'] for t in trials),
                'median_peak_working_set_bytes':statistics.median(t['peak_working_set_bytes'] for t in trials),
                'median_logical_cpus':statistics.median(t['average_logical_cpus'] for t in trials)}
        base=results['baseline']['median_native_seconds']
        for result in results.values():result['speedup']=base/result['median_native_seconds']
        report['results'][scene]=results
    report['all_checkpoints_identical']=all(r['identical_checkpoint'] for s in report['results'].values() for r in s.values())
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'kind':'completed','report':str(folder/'report.json'),'results':report['results']}),flush=True)
    if not report['all_checkpoints_identical']:raise SystemExit('Numerical equivalence failed; variants are not production candidates')


if __name__=='__main__':main()
