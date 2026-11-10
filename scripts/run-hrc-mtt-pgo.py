"""Isolated IR-PGO pipeline: build, train, merge-build, then validate.

LLVM-MinGW supplies the profile runtime and merger. The final comparison uses
the original Zig driver, flags, libraries and frozen sources on both sides.
Use the same fresh --output directory for all four stages.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.research-cache/mtt-hotspots-pgo-20261109'
TOOLS = Path('D:/Tools/REA-Research/llvm-mingw-20250402-ucrt-x86_64/bin')
CANONICAL = ROOT / '.research-cache/bubble-round2-20261109/accepted/solver.exe'
FLAGS = ['-O3', '-std=c++17', '-ffp-contract=off', '-flto=thin', '-static']


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf8')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(name, extra, *, zig=False):
    folder = OUT / name
    folder.mkdir(exist_ok=False)
    accepted = json.loads((CANONICAL.parent / 'manifest.json').read_text(encoding='utf8'))
    source = Path(accepted['identity_spec']['translation_unit'])
    assert all(sha(source.parent / name) == row['sha256'] for name, row in accepted['identity_spec']['source_files'].items())
    compiler = Path(accepted['compiler']) if zig else TOOLS / 'clang++.exe'
    if zig:
        assert sha(compiler)==accepted['identity_spec']['compiler']['sha256'], 'Canonical compiler changed'
    driver = [str(compiler), 'c++'] if zig else [str(compiler)]
    flags = accepted['ordered_flags'] if zig else FLAGS
    command = [*driver, *flags, *extra, str(source), '-o', str(folder / 'solver.exe')]
    version = subprocess.check_output([*driver, '--version'], text=True)
    print(json.dumps({'event': 'building', 'variant': name}), flush=True)
    result = subprocess.run(command, capture_output=True, text=True, timeout=240)
    record = {'command': command, 'compiler_version': version, 'compiler_sha256': sha(compiler),
              'source_set_sha256': accepted['identity_spec']['source_set_sha256'], 'source_files': accepted['identity_spec']['source_files'],
              'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
              'canonical_build_identity': accepted['build_identity']}
    profile=next((Path(flag.split('=',1)[1]) for flag in extra if flag.startswith('-fprofile-use=')),None)
    if profile:
        record['profile_sha256']=sha(profile)
    dump(folder / 'build.json', record)
    result.check_returncode()
    record['executable_sha256'] = sha(folder / 'solver.exe')
    env = dict(os.environ, LLVM_PROFILE_FILE=str(folder/'self-test-%p.profraw'))
    actual = subprocess.check_output([str(folder/'solver.exe'), '--self-test'], env=env)
    expected = subprocess.check_output([str(CANONICAL), '--self-test'])
    (folder/'self-test.jsonl').write_bytes(actual)
    assert actual == expected, 'Built-in numeric probes changed'
    record['self_test_byte_identical_to_canonical'] = True
    dump(folder / 'build.json', record)
    print(json.dumps({'event':'build_validated','variant':name,'sha256':record['executable_sha256']}),flush=True)


def run(variant, stage, *, samples, threads, name, environment=None, keep_checkpoint=False):
    spec = importlib.util.spec_from_file_location('pgo_monitor', ROOT / 'scripts/benchmark-hrc-ci-target.py')
    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)
    prior = json.loads((ROOT / '.research-cache/bubble-round2-20261109/accepted-confirm/accepted-r0/command.json').read_text())
    source = (ROOT/'.research-cache/hand-bubble-20261108/initialization/checkpoint.bin' if stage == 'early'
              else ROOT/'.research-cache/runs/91504bf5f41e43028c2ed1ce912df1cd/checkpoint.bin')
    with source.open('rb') as stream:
        initial = struct.unpack_from('<Q', stream.read(24), 16)[0]
    digest = sha(source)
    exe = CANONICAL if variant == 'canonical' else OUT/variant/'solver.exe'
    command = list(prior)
    command[0], command[3], command[7], command[14], command[19] = str(exe), str(initial+samples), str(source), str(threads), str(samples)
    command[5] = str(OUT/name)
    def phase_command(*args, **kwargs):
        return command
    monitor.phase_command = phase_command
    plan = {'output':str(OUT),'build':{'executable_path':str(exe)}}
    previous = {key:os.environ.get(key) for key in (environment or {})}
    try:
        os.environ.update(environment or {})
        with (OUT/(name+'.runner.log')).open('x',encoding='utf8') as log, contextlib.redirect_stdout(log):
            result = monitor.run_phase(plan,name,resume=source)
    finally:
        for key,value in previous.items():
            if value is None:
                os.environ.pop(key,None)
            else:
                os.environ[key]=value
    assert sha(source) == digest
    assert result['summary']['iteration']==initial+samples and result['summary']['stop_reason']=='sample_target'
    assert result['summary']['terminal_tables'] and result['summary']['terminal_settlements']==0
    result.update(stage=stage,variant=variant,samples=samples,source_sha256=digest,executable_sha256=sha(exe))
    for filename in ('checkpoint.bin','index.json'):
        path = OUT/name/filename
        result[filename+'_sha256']=sha(path)
        if not keep_checkpoint:
            assert path.resolve().is_relative_to((OUT/name).resolve())
            path.unlink()
    dump(OUT/name/'measurement.json',result)
    print(json.dumps({'event':'run_completed','name':name,'stage':stage,'native_seconds':result['summary']['elapsed_seconds'],
                      'checkpoint_sha256':result['checkpoint.bin_sha256']}),flush=True)
    return result


def main():
    global OUT
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('build','train','merge-build','validate','validate-llvm'))
    p.add_argument('--output',type=Path,default=OUT)
    a=p.parse_args()
    OUT=a.output.resolve()
    if not OUT.is_relative_to(ROOT.resolve()):
        raise ValueError('PGO output must stay inside the workspace')
    OUT.mkdir(parents=True,exist_ok=True)
    if a.stage=='build':
        build('llvm-baseline',[])
        build('llvm-instrumented',['-fprofile-generate','-fprofile-update=atomic'])
    elif a.stage=='train':
        profiles=OUT/'training-profiles';profiles.mkdir(exist_ok=False)
        results=[]
        for stage in ('early','mature'):
            results.append(run('llvm-instrumented',stage,samples=5000000,threads=20,name='pgo-train-'+stage,
                               environment={'LLVM_PROFILE_FILE':str(profiles/(stage+'-%p.profraw'))}))
        files=list(profiles.glob('*.profraw'));assert len(files)==2 and all(f.stat().st_size>0 for f in files)
        dump(OUT/'training-profiles.json',{'profiles':{str(f):sha(f) for f in files},'runs':results})
    elif a.stage=='merge-build':
        files=sorted((OUT/'training-profiles').glob('*.profraw'));assert len(files)==2
        merged=OUT/'mtt-early-mature.profdata'
        command=[str(TOOLS/'llvm-profdata.exe'),'merge',*map(str,files),'-o',str(merged)]
        result=subprocess.run(command,capture_output=True,text=True,check=True)
        dump(OUT/'merge.json',{'command':command,'stdout':result.stdout,'stderr':result.stderr,'sha256':sha(merged)})
        show=subprocess.check_output([str(TOOLS/'llvm-profdata.exe'),'show','--all-functions','--counts',str(merged)],text=True)
        (OUT/'profile-show.txt').write_text(show,encoding='utf8')
        build('llvm-pgo',['-fprofile-use='+str(merged),'-Werror=profile-instr-out-of-date'])
        build('zig-pgo',['-fprofile-use='+str(merged),'-Werror=profile-instr-out-of-date'],zig=True)
    else:
        variants=('canonical','zig-pgo') if a.stage=='validate' else ('llvm-baseline','llvm-pgo')
        results=[]
        for variant in variants:
            results.append(run(variant,'mature',samples=100000,threads=1,name='serial-'+variant))
        equal=len({row['checkpoint.bin_sha256'] for row in results})==1
        dump(OUT/(a.stage+'-serial-validation.json'),{'all_checkpoint_bytes_equal':equal,'runs':results})
        assert equal, 'Complete serial checkpoint mismatch'


if __name__=='__main__':
    main()
