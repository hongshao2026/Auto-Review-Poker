"""Compose measured, isolated round-three factors without editing production."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / '.research-cache/throughput-round3-20261108'
BASE = ROUND / 'baseline'


def change(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Nonunique composition anchor: {old[:120]!r}')
    return text.replace(old, new, 1)


def terminal(cpp, parallel):
    candidate = (ROUND / 'terminal-pointer-candidate/hrc_research_solver.cpp').read_text(encoding='utf-8')
    start = candidate.index('    struct TerminalPointer ')
    end = candidate.index('    int combo[MAXP]', start)
    cpp = change(cpp, '    int combo[MAXP]', candidate[start:end] + '    int combo[MAXP]')
    old = '        ++terminal_calls;auto& t=tree.terms[id];if(t.synthetic)return t.value.data();'
    start = candidate.index('        ++terminal_calls;\n')
    end = candidate.index('        if(t.cached_deal', start)
    cpp = change(cpp, old + '\n', candidate[start:end])
    anchor = '    const double terminal_table_setup_seconds='
    cpp = change(cpp, anchor,
                 '    const bool terminal_pointer_enabled=parallel?parallel->prepare_terminal_pointers():Engine::prepare_terminal_pointers({&e},e.tree);\n' + anchor)
    anchor = '    auto write_optimization=[&](){const auto& table=e.tree.terminal_tables;\n'
    cpp = change(cpp, anchor, anchor +
                 '        std::cout<<",\\\"terminal_pointer_cache\\\":"<<(terminal_pointer_enabled?"true":"false")<<",\\\"terminal_pointer_cache_bytes\\\":"<<(e.terminal_pointer_bytes*training_threads);\n')
    anchor = '    ~ParallelTrainer(){stop();}\n'
    parallel = change(parallel, anchor, anchor + '''    bool prepare_terminal_pointers(){
        std::lock_guard<std::mutex> lock(control_);
        if(pending_)throw std::logic_error("Terminal pointer preparation requires quiescent workers");
        return Engine::prepare_terminal_pointers(engines_,main_.tree);
    }
''')
    return cpp, parallel


def flat_map(cpp, out):
    folder = ROUND / 'flat-board-map-candidate'
    for name in ('hrc_cards.hpp', 'hrc_flat_board_map.hpp'):
        shutil.copy2(folder / name, out / name)
    baseline = (BASE / 'hrc_research_solver.cpp').read_text(encoding='utf-8')
    candidate = (folder / 'hrc_research_solver.cpp').read_text(encoding='utf-8')
    old = next(line for line in baseline.splitlines(True) if 'bytes=32768;for(int st=1' in line)
    new = next(line for line in candidate.splitlines(True) if 'bytes=32768;for(int st=1' in line)
    return change(cpp, old, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--source', type=Path, default=ROUND/'read-unlocked-candidate')
    parser.add_argument('--eager', action='store_true')
    args = parser.parse_args()
    out = ROUND / args.name
    out.mkdir(parents=True, exist_ok=False)
    for path in args.source.glob('*.hpp'):
        shutil.copy2(path, out/path.name)
    cpp = (args.source/'hrc_research_solver.cpp').read_text(encoding='utf-8')
    parallel = (args.source/'hrc_parallel.hpp').read_text(encoding='utf-8')
    cpp, parallel = terminal(cpp, parallel)
    cpp = flat_map(cpp, out)
    if args.eager:
        module_path = ROOT/'scripts/build-hrc-abstraction-candidate.py'
        import importlib.util
        spec = importlib.util.spec_from_file_location('eager_factor', module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        anchor='    int hand(const Node& n){\n        '
        cpp=change(cpp, anchor, anchor+module.EAGER)
    (out/'hrc_research_solver.cpp').write_text(cpp, encoding='utf-8')
    (out/'hrc_parallel.hpp').write_text(parallel, encoding='utf-8')
    exe=out/'solver-combined.exe'
    command=['D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe',
             'c++','-O3','-std=c++17','-ffp-contract=off',str(out/'hrc_research_solver.cpp'),'-o',str(exe)]
    subprocess.run(command,check=True,capture_output=True,text=True)
    manifest={'source':str(args.source),'terminal_pointer':True,'flat_map':True,'eager':args.eager,
              'command':command,'production_modified':False,
              'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}}
    (out/'build.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'exe':str(exe),'sha256':manifest['files'][exe.name]}),flush=True)


if __name__=='__main__':
    main()
