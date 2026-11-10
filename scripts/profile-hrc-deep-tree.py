"""Bounded single-thread instrumentation against an immutable native snapshot.

Timers sample every 64th call independently of the solver RNG. Their extrapolated
totals are diagnostic estimates, not benchmark timings. Checkpoint SHA parity is
required against the uninstrumented binary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def instrument(source):
    support = r'''
struct ProfileCell { uint64_t calls=0, measured=0, nanos=0; };
struct ProfileScope {
    ProfileCell& cell; bool enabled; std::chrono::steady_clock::time_point start;
    explicit ProfileScope(ProfileCell& c):cell(c),enabled((++c.calls&63)==1){
        if(enabled)start=std::chrono::steady_clock::now();
    }
    ~ProfileScope(){if(enabled){cell.nanos+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();++cell.measured;}}
};
'''
    source = source.replace('struct Engine {', support + '\nstruct Engine {', 1)
    source = source.replace('Tree tree;Random rng;', '''
    ProfileCell profile[7];
    uint64_t profile_fills[4]{}, profile_used[4]{}, profile_terminal_hits=0;
    uint64_t profile_pots=0, profile_unique_pots=0, profile_pot_epoch[1<<MAXP]{};
    uint32_t profile_seen[4]{};
    void emit_profile(){
        const char* names[]={"deal","hand","choose","update","terminal","save","ranks"};
        std::cout<<"{\\"kind\\":\\"profile\\",\\"timers\\":{";
        for(int i=0;i<7;++i){if(i)std::cout<<',';auto& c=profile[i];std::cout<<'"'<<names[i]<<"\\":{\\"calls\\":"<<c.calls<<",\\"measured\\":"<<c.measured<<",\\"estimated_seconds\\":"<<(c.measured?double(c.nanos)*c.calls/c.measured/1e9:0)<<'}';}
        std::cout<<"},\\"fills\\":[";for(int i=0;i<4;++i){if(i)std::cout<<',';std::cout<<profile_fills[i];}
        std::cout<<"],\\"used_players\\":[";for(int i=0;i<4;++i){if(i)std::cout<<',';std::cout<<profile_used[i];}
        std::cout<<"],\\"terminal_hits\\":"<<profile_terminal_hits<<",\\"pot_comparisons\\":"<<profile_pots<<",\\"unique_pot_comparisons\\":"<<profile_unique_pots<<"}"<<std::endl;
    }
    Tree tree;Random rng;''', 1)
    anchors = [
        ('void deal(){', 'ProfileScope prof(profile[0]);for(auto& mask:profile_seen)mask=0;'),
        ('int hand(const Node& n){', 'ProfileScope prof(profile[1]);if(!(profile_seen[n.street]&(1u<<n.actor))){++profile_used[n.street];profile_seen[n.street]|=1u<<n.actor;}'),
        ('int choose(int id,Node& n,int h,double* p){', 'ProfileScope prof(profile[2]);'),
        ('void update(int id,Node& n,int h,const double* p,const double* q,double marker){', 'ProfileScope prof(profile[3]);'),
        ('const double* terminal(int id){', 'ProfileScope prof(profile[4]);'),
        ('void save(const fs::path& folder){', 'ProfileScope prof(profile[5]);'),
        ('void ensure_ranks(uint32_t need){', 'ProfileScope prof(profile[6]);'),
    ]
    for before, body in anchors:
        if source.count(before) != 1:
            raise ValueError('Profile anchor changed: ' + before)
        source = source.replace(before, before + body, 1)
    source = source.replace('if(!bucket_ready[n.street]){', 'if(!bucket_ready[n.street]){profile_fills[n.street]+=tree.players;', 1)
    source = source.replace('return t.value.data();t.value=t.base;', '{++profile_terminal_hits;return t.value.data();}t.value=t.base;', 1)
    source = source.replace('if(winners&(winners-1)){ensure_ranks(pot.eligible);', '''if(winners&(winners-1)){++profile_pots;if(profile_pot_epoch[winners]!=epoch){++profile_unique_pots;profile_pot_epoch[winners]=epoch;}ensure_ranks(pot.eligible);''', 1)
    source = source.replace('e.save(output);double elapsed=', 'e.save(output);e.emit_profile();double elapsed=', 1)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=100000)
    args = parser.parse_args()
    if not 1000 <= args.samples <= 1000000:
        parser.error('Bounded profiling samples must be 1000..1000000')
    args.output.mkdir(parents=True, exist_ok=False)
    helper = runpy.run_path(str(ROOT / 'scripts/audit-hrc-performance.py'))
    source = args.snapshot / 'native/hrc_research_solver.cpp'
    patched = args.output / 'profile.cpp'
    patched.write_text(instrument(source.read_text(encoding='utf-8')), encoding='utf-8')
    executable = args.output / 'profile.exe'
    command = helper['compile_variant'](patched, executable, [], args.snapshot / 'native')
    results = {}
    for label, exe in [('baseline', args.snapshot / 'solver.exe'), ('profile', executable)]:
        # Full tree memory is bounded by the CLI default; profile smaller scenes
        # unless a dedicated larger-tree runner explicitly budgets more memory.
        results[label] = helper['run_case'](exe.resolve(), args.tree.resolve(), args.output / label,
                                            args.samples, 43)
        print(json.dumps({'kind': label, 'seconds': results[label]['native_seconds']}), flush=True)
    rows = [json.loads(line) for line in (args.output/'profile/stdout.jsonl').read_text().splitlines()]
    report = {'schema': 'hrc-deep-tree-profile-v1', 'compiler': command,
              'tree_sha256': helper['sha'](args.tree), 'samples': args.samples,
              'profile': next(row for row in rows if row['kind'] == 'profile'),
              'runs': results, 'checkpoint_identical': results['baseline']['checkpoint_sha256'] == results['profile']['checkpoint_sha256'],
              'limits': ['Sampled timers are extrapolated diagnostic estimates and overlap for terminal/ranks.',
                         'Use uninstrumented interleaved runs to measure speed.']}
    (args.output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report['profile']), flush=True)
    if not report['checkpoint_identical']:
        raise RuntimeError('Profiling changed checkpoint bytes')


if __name__ == '__main__':
    main()
