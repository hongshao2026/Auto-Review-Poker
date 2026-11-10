"""Create isolated profiling/optimization executables; never edit production."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.research-cache/bubble-round2-20261109/candidates'
ZIG = Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')


def replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Non-unique source patch: ' + old[:100])
    return source.replace(old, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['profile-on', 'profile-off', 'combo', 'pure3', 'deal-reuse', 'combo-reuse', 'board-rank', 'terminal-dedup', 'terminal-edges'], required=True)
    args = parser.parse_args()
    folder = OUT / args.case
    folder.mkdir(parents=True, exist_ok=False)
    baseline = json.loads((ROOT / 'analysis/hrc-native/build/identities/033dc7741886ae9e70743c99ae3b17d9666db17410f98e3da00c6f04c4b40808/build.json').read_text())
    source_folder = Path(baseline['identity_spec']['translation_unit']).parent
    for path in source_folder.iterdir():
        if path.suffix in ('.hpp', '.cpp', '.h'):
            shutil.copy2(path, folder / path.name)
    path = folder / 'hrc_research_solver.cpp'
    source = path.read_text(encoding='utf-8')
    if args.case.startswith('profile-'):
        source = replace(source, 'struct Engine {', '''
struct PerfCell {uint64_t calls=0,sequence=0,measured=0,ns=0;};
struct PerfScope {
    PerfCell& cell;bool active;std::chrono::steady_clock::time_point start;
    explicit PerfScope(PerfCell& c):cell(c),active((c.sequence++&4095)==0){
        ++cell.calls;if(active){++cell.measured;start=std::chrono::steady_clock::now();}}
    ~PerfScope(){if(active)cell.ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();}
};
''' + ('#define PHASE(i) PerfScope phase_timer(perf[i]);\n' if args.case == 'profile-on' else '#define PHASE(i)\n') + '''
struct Engine {
    std::array<PerfCell,6> perf;
''')
        for index, signature in enumerate([
            'void scope_deal(int skip=-1){', 'int hand(const Node& n){',
            'int choose(int id,Node& n,int h,double* p){',
            'void update(int id,Node& n,int h,const double* p,const double* q,double marker){',
            'const double* terminal(int id){', 'void ensure_ranks(uint32_t need){']):
            source = replace(source, signature, signature + f'PHASE({index})')
        source = replace(source, 'auto write_optimization=[&](){const auto& table=e.tree.terminal_tables;', '''
    auto write_optimization=[&](){const auto& table=e.tree.terminal_tables;
        std::cout<<",\\\"phase_profile\\\":[";
        for(size_t i=0;i<e.perf.size();++i){if(i)std::cout<<',';const auto& p=e.perf[i];
            std::cout<<"{\\\"calls\\\":"<<p.calls<<",\\\"measured\\\":"<<p.measured<<",\\\"ns\\\":"<<p.ns<<"}";}
        std::cout<<']';
''')
        parallel = folder / 'hrc_parallel.hpp'
        text = parallel.read_text(encoding='utf-8')
        text = replace(text, 'for(auto& engine:extra_){for(int p=0;p<main_.tree.players;++p)', '''
        for(auto& engine:extra_){
            for(size_t i=0;i<main_.perf.size();++i){auto& out=main_.perf[i];auto& in=engine->perf[i];
                out.calls+=in.calls;out.measured+=in.measured;out.ns+=in.ns;
                in.calls=in.measured=in.ns=0;}
            for(int p=0;p<main_.tree.players;++p)''')
        parallel.write_text(text, encoding='utf-8')
    if args.case in ('combo', 'combo-reuse'):
        source = replace(source,
            'int high=1;while(high*(high+1)/2<=combo[p])++high;int low=combo[p]-high*(high-1)/2;',
            'const auto& cards=hrc_cards::combo_cards();int high=cards.hi[combo[p]],low=cards.lo[combo[p]];')
    if args.case in ('deal-reuse', 'combo-reuse'):
        chance = folder / 'hrc_chance.hpp'
        text = chance.read_text(encoding='utf-8')
        signature = '''    template<class NextInt,class NextDouble>
    Deal sample(NextInt next_int,NextDouble next_double,
                const std::function<bool()>& cancel={},int skip_player=-1) const {'''
        text = replace(text, signature, '''    template<class NextInt,class NextDouble>
    Deal sample(NextInt next_int,NextDouble next_double,
                const std::function<bool()>& cancel={},int skip_player=-1) const {
        Deal out;sample_into(out,next_int,next_double,cancel,skip_player);return out;
    }
    template<class NextInt,class NextDouble>
    void sample_into(Deal& out,NextInt next_int,NextDouble next_double,
                const std::function<bool()>& cancel={},int skip_player=-1) const {''')
        text = replace(text, 'Deal out;out.combos.assign(players(),-1);',
                       'out.used=out.attempts=out.random_calls=0;out.board.fill(0);out.combos.assign(players(),-1);')
        text = replace(text, '        return out;\n    }', '    }')
        chance.write_text(text, encoding='utf-8')
        source = replace(source, 'void scope_deal(int skip=-1){try{accept_deal(scope->sampler->sample([&](int b){return int(rng.bound(uint32_t(b)));},[&](){return rng.unit();},tree.chance_cancel,skip));}',
                         '''hrc_chance::Deal chance_scratch;
    void scope_deal(int skip=-1){try{scope->sampler->sample_into(chance_scratch,[&](int b){return int(rng.bound(uint32_t(b)));},[&](){return rng.unit();},tree.chance_cancel,skip);accept_deal(chance_scratch);}''')
    if args.case == 'pure3':
        source = replace(source,
            'if(total>0){out[0]/=total;out[1]/=total;out[2]/=total;}',
            '''if(total>0){
                if(std::isfinite(total)){
                    if(out[1]==0&&out[2]==0){out[0]=1;return;}
                    if(out[0]==0&&out[2]==0){out[1]=1;return;}
                    if(out[0]==0&&out[1]==0){out[2]=1;return;}
                }
                out[0]/=total;out[1]/=total;out[2]/=total;
            }''')
    if args.case == 'board-rank':
        cards_path = folder / 'hrc_cards.hpp'
        cards = cards_path.read_text(encoding='utf-8')
        # Keep the original rank7 unchanged as an independent exact oracle.
        original = cards[cards.index('inline int rank7(uint64_t cards) {'):cards.index('\nstruct ComboCards')]
        finish = original[original.index('    if(four)'):original.rindex('}')]
        addition = '''
// Five public cards are common to every seat in a deal.
struct BoardRankState {
    uint32_t suits[4]{},one=0,two=0,three=0,four=0;
    int flush_suit=-1;
    BoardRankState()=default;
    explicit BoardRankState(uint64_t cards){
        while(cards){int c=lowbit(cards);cards&=cards-1;uint32_t bit=1u<<(c>>2);
            four|=three&bit;three|=two&bit;two|=one&bit;one|=bit;suits[c&3]|=bit;}
        for(int s=0;s<4;++s)if(popcount(suits[s])>=3)flush_suit=s;
    }
};
inline int rank7_with_board(const BoardRankState& board,uint64_t holes){
    static const RankTables t;
    uint32_t suits[4]={board.suits[0],board.suits[1],board.suits[2],board.suits[3]};
    uint32_t one=board.one,two=board.two,three=board.three,four=board.four;
    while(holes){int c=lowbit(holes);holes&=holes-1;uint32_t bit=1u<<(c>>2);
        four|=three&bit;three|=two&bit;two|=one&bit;one|=bit;suits[c&3]|=bit;}
    int s=board.flush_suit;
    if(s>=0&&popcount(suits[s])>=5){
        if(t.straight[suits[s]]>=0)return (8<<20)|((t.straight[suits[s]]+2)<<16);
        return (5<<20)|t.top5[suits[s]];
    }
''' + finish + '}\n'
        cards = replace(cards, '\nstruct ComboCards', addition + '\nstruct ComboCards')
        cards_path.write_text(cards, encoding='utf-8')
        source = replace(source, 'bool bucket_ready[4]{},rank_ready=false;uint32_t rank_mask=0;',
                         'bool bucket_ready[4]{},rank_ready=false;uint32_t rank_mask=0;\n    hrc_cards::BoardRankState rank_board;bool rank_board_ready=false;')
        if source.count('rank_ready=false;rank_mask=0;') != 2:
            raise ValueError('Expected both deal resets')
        source = source.replace('rank_ready=false;rank_mask=0;', 'rank_ready=false;rank_mask=0;rank_board_ready=false;')
        source = replace(source, 'uint32_t missing=need&~rank_mask;',
                         'uint32_t missing=need&~rank_mask;\n        if(missing&&!rank_board_ready){rank_board=hrc_cards::BoardRankState(board[3]);rank_board_ready=true;}')
        source = replace(source, 'rank[p]=hrc_cards::rank7(holes[p]|board[3]);',
                         'rank[p]=hrc_cards::rank7_with_board(rank_board,holes[p]);')
    if args.case == 'terminal-edges':
        source = replace(source, 'std::vector<int> children;std::vector<Terminal> terms;',
                         'std::vector<int> children,traversal_children;std::vector<Terminal> terms;')
        source = replace(source, 'Node& node(int id){return (shared_nodes?*shared_nodes:tree.nodes)[id];}',
                         '''Node& node(int id){return (shared_nodes?*shared_nodes:tree.nodes)[id];}
    int traversal_child(int offset)const{const auto& t=resources();return (t.traversal_children.empty()?t.children:t.traversal_children)[offset];}''')
        source = replace(source, '++scalar_calls;Node& n=node(id);',
                         '++scalar_calls;if(id<0)return terminal(-id-1)[target];Node& n=node(id);')
        source = replace(source, '++vector_calls;Node& n=node(id);',
                         '++vector_calls;if(id<0)return terminal(-id-1);Node& n=node(id);')
        # Only traversal edges are encoded. Scope, CI, persistence and export
        # retain the original immutable public tree and positive node IDs.
        start=source.index('    double scalar(int id,int target,int depth,double marker){')
        end=source.index('    void step(){', start)
        segment=source[start:end]
        segment=segment.replace('resources().children[n.first+a]', 'traversal_child(n.first+a)')
        segment=segment.replace('resources().children[n.first+chosen]', 'traversal_child(n.first+chosen)')
        source=source[:start]+segment+source[end:]
        source = replace(source, 'bool reset_r=argc>=9&&std::string(argv[8])=="1",', '''
    e.tree.reserve_budget(e.tree.children.size()*sizeof(int));e.tree.traversal_children=e.tree.children;
    for(auto& child:e.tree.traversal_children)if(!e.tree.nodes[child].k)child=-e.tree.nodes[child].terminal-1;
    bool reset_r=argc>=9&&std::string(argv[8])=="1",''')
    if args.case == 'terminal-dedup':
        table_path = folder / 'hrc_terminal_table.hpp'
        text = table_path.read_text(encoding='utf-8')
        text = replace(text,
            'Transform&& transform,const std::function<bool()>& cancelled={}) {',
            'Transform&& transform,const std::function<bool()>& cancelled={},const std::vector<std::size_t>* aliases=nullptr) {')
        text = replace(text, 'std::size_t bytes=overhead+terminals.size()*sizeof(Entry),elements=0;',
            '''if(aliases&&aliases->size()!=terminals.size())throw std::invalid_argument("Terminal alias count mismatch");
        std::size_t bytes=overhead+terminals.size()*sizeof(Entry),elements=0,id_check=0;''')
        text = replace(text, 'Entry e=describe(t,players);\n            std::size_t n=',
            '''Entry e=describe(t,players);
            if(aliases){std::size_t id=id_check++;if((*aliases)[id]>id)throw std::invalid_argument("Forward terminal alias");if((*aliases)[id]<id)continue;}
            std::size_t n=''')
        text = replace(text, 'Entry e=describe(t,players);e.offset=offset;result->entries_[id++]=e;',
            '''Entry e=describe(t,players);
                if(aliases&&(*aliases)[id]<id){const Entry& prior=result->entries_[(*aliases)[id]];
                    if(e.live!=prior.live||e.needed!=prior.needed||e.count!=prior.count||e.order!=prior.order)
                        throw std::invalid_argument("Terminal alias signature mismatch");
                    e.offset=prior.offset;result->entries_[id++]=e;continue;}
                e.offset=offset;result->entries_[id++]=e;''')
        table_path.write_text(text, encoding='utf-8')
        source = replace(source, '#include <mutex>', '#include <mutex>\n#include <unordered_map>')
        source = replace(source, '    std::shared_ptr<const hrc_terminal_table::Tables> make_terminal_table(', '''
    std::vector<std::size_t> terminal_aliases(std::size_t budget){
        // The exact key includes every field consumed by ChipEV settlement
        // and monetary/bounty transformation. Hash collisions use key equality.
        const auto& terms=tree.terms;std::size_t fixed=terms.size()*3*sizeof(std::size_t);
        if(fixed>budget/2)return {};
        std::vector<std::size_t> aliases(terms.size());
        std::unordered_map<std::string,std::size_t> seen;seen.reserve(terms.size());
        std::size_t used=fixed;
        for(std::size_t id=0;id<terms.size();++id){const auto& t=terms[id];
            std::string key;key.reserve(tree.players*2*sizeof(double)+sizeof(t.folded)+sizeof(std::size_t)+t.pots.size()*16);
            auto append=[&](const auto& x){key.append(reinterpret_cast<const char*>(&x),sizeof(x));};
            for(int p=0;p<tree.players;++p){append(t.base[p]);append(t.paid[p]);}
            append(t.folded);auto count=t.pots.size();append(count);
            for(const auto& pot:t.pots){append(pot.amount);append(pot.eligible);append(pot.contributors);}
            auto found=seen.find(key);
            if(found!=seen.end()){aliases[id]=found->second;continue;}
            std::size_t entry_bytes=key.capacity()+1+128;
            if(entry_bytes>budget/2-used)return {};
            used+=entry_bytes;aliases[id]=id;seen.emplace(std::move(key),id);
        }
        return aliases;
    }
    std::shared_ptr<const hrc_terminal_table::Tables> make_terminal_table(''')
        source = replace(source,
            'if(!tree.equity)return hrc_terminal_table::Tables::build(tree.terms,tree.players,tree.chip_scale,budget,cancelled);',
            '''auto aliases=terminal_aliases(budget);const auto* alias_ptr=aliases.empty()?nullptr:&aliases;
        const auto table_budget=budget-aliases.capacity()*sizeof(std::size_t);
        if(!tree.equity)return hrc_terminal_table::Tables::build_transformed(tree.terms,tree.players,tree.chip_scale,table_budget,
            [](const auto&,const int*,double*){},cancelled,alias_ptr);''')
        source = replace(source,
            'return hrc_terminal_table::Tables::build_transformed(tree.terms,tree.players,1.0,budget,transform,cancelled);',
            'return hrc_terminal_table::Tables::build_transformed(tree.terms,tree.players,1.0,table_budget,transform,cancelled,alias_ptr);')
    path.write_text(source, encoding='utf-8')
    exe = folder / 'solver.exe'
    command = [str(ZIG), 'c++', '-O3', '-std=c++17', '-ffp-contract=off', '-flto=thin', str(path), '-o', str(exe)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    manifest = dict(case=args.case, command=command, executable=str(exe),
                    executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                    source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.suffix in ('.cpp', '.hpp', '.h')})
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest), flush=True)


if __name__ == '__main__':
    main()
