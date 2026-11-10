"""Run prepared round-four candidates sequentially, with frozen source inputs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/cpu-round4-20261108'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scenario',choices=['three','nine'],required=True)
    p.add_argument('--stage',required=True)
    p.add_argument('--samples',type=int,default=10_000_000)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--include',nargs='+')
    p.add_argument('--resume',type=Path)
    p.add_argument('--threads',type=int,default=20)
    p.add_argument('--serial-reference',type=Path)
    p.add_argument('--high-qos',nargs='+',default=[])
    args=p.parse_args()
    cases={'baseline':ROOT/'.research-cache/throughput-round3-20261108/accepted/hrc_round3_accepted.exe',
        'shared':BASE/'sync/shared_metadata_table_release/solver.exe',
        'index':BASE/'layout/index-candidate/solver.exe','split':BASE/'layout/solver.exe',
        'loadcas':BASE/'sync/load_cas_y64/solver.exe',
        'yield16':BASE/'sync/exchange_y16/solver.exe',
        'yield256':BASE/'sync/exchange_y256/solver.exe',
        'prepared':BASE/'sync/private_update_prepared/solver.exe',
        'ci':BASE/'ci/solver.exe'}
    cases.update(highqos=cases['baseline'],block32=BASE/'sync/block32/solver.exe',block64=BASE/'sync/block64/solver.exe',
        hot256=BASE/'layout/hot-metadata-baseline/solver.exe',hot192=BASE/'layout/hot-metadata-baseline192/solver.exe',
        hotindex=BASE/'layout/hot-metadata-index/solver.exe')
    for entry in json.loads((BASE/'compiler/ready-candidates.json').read_text()):
        cases[entry['variant']]=Path(entry['executable'])
    cases['thin_qos']=cases['thin_lto']
    cases.update(foundation_plain=BASE/'combined/foundation-plain/solver.exe',
                 foundation_thin=BASE/'combined/foundation-thin/solver.exe',
                 native_qos=BASE/'sync/native_qos/solver.exe',
                 slice100=BASE/'sync/slice100/solver.exe',
                 slice200=BASE/'sync/slice200/solver.exe')
    if args.include:cases={name:cases[name] for name in args.include}
    if next(iter(cases))!='baseline':raise ValueError('Reference must be baseline')
    prefix=f'{args.scenario}-{args.stage}'
    command=[sys.executable,'-X','utf8',str(ROOT/'scripts/benchmark-hrc-round3.py'),
        '--output',str(BASE/prefix),'--report',str(ROOT/f'reports/hrc-round4-{prefix}-20261108.json'),
        '--samples',str(args.samples),'--repeats',str(args.repeats),'--threads',str(args.threads),
        '--scenario',args.scenario,'--discard-trial-checkpoints']
    if args.resume:command.extend(['--resume',str(args.resume.resolve())])
    if args.serial_reference:command.extend(['--serial-reference',str(args.serial_reference.resolve())])
    for name in args.high_qos:command.extend(['--case-high-qos',name])
    for name,exe in cases.items():
        if not exe.is_file():raise FileNotFoundError(exe)
        command.extend(['--case',name,str(exe)])
    print(json.dumps({'stage':prefix,'cases':list(cases),'samples':args.samples,'repeats':args.repeats}),flush=True)
    subprocess.run(command,check=True)

if __name__=='__main__':main()
