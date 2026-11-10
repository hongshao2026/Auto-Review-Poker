"""Isolated eager-street and full-column abstraction reader experiments."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/throughput-round3-20261108/baseline'
EXPAND=r'''
template<class T> inline void expand_columns(const std::vector<uint64_t>& boards,std::vector<T>& packed,int columns){
    std::vector<T> wide(boards.size()*1326);
    for(size_t row=0;row<boards.size();++row){size_t col=0;
        for(int hi=1;hi<52;++hi)if(!(boards[row]&(uint64_t(1)<<hi)))
            for(int lo=0;lo<hi;++lo)if(!(boards[row]&(uint64_t(1)<<lo)))
                wide[row*1326+size_t(hi*(hi-1)/2+lo)]=packed[row*columns+col++];
        if(col!=size_t(columns))throw std::runtime_error("Expanded abstraction column count mismatch");
    }
    packed.swap(wide);
}
'''
EAGER=r'''if(!bucket_ready[n.street]&&n.street>0&&!resources().chance){
            if(!tables)throw std::runtime_error("Missing abstraction tables");
            bucket_rows[n.street]=hrc_cards::prepare_bucket_row(n.street,board[n.street],*tables);
            for(int seat=0;seat<tree.players;++seat)
                bucket[n.street][seat]=hrc_cards::bucket_from_row(combo[seat],board[n.street],bucket_rows[n.street],tables->streets[n.street]);
            bucket_mask[n.street]=(1u<<tree.players)-1;bucket_ready[n.street]=true;
        }
        '''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('eager','wide','eager-wide'),required=True)
    args=parser.parse_args();out=BASE.parent/f'abstraction-{args.mode}-candidate'
    out.mkdir(parents=True,exist_ok=False)
    for path in BASE.glob('hrc_*.hpp'):shutil.copy2(path,out/path.name)
    cpp=(BASE/'hrc_research_solver.cpp').read_text(encoding='utf-8')
    if 'eager' in args.mode:
        anchor='    int hand(const Node& n){\n        '
        assert cpp.count(anchor)==1;cpp=cpp.replace(anchor,anchor+EAGER,1)
    if 'wide' in args.mode:
        header=(out/'hrc_cards.hpp').read_text(encoding='utf-8')
        header=header.replace('class AbstractionTables {',EXPAND+'\nclass AbstractionTables {',1)
        anchor='            streets[s]=std::move(data);'
        extra=('            if(buckets[s]<=256)expand_columns(boards,data.compact_values,cols[s]);\n'
               '            else expand_columns(boards,data.values,cols[s]);\n'
               '            data.hole_columns=1326;\n')
        assert header.count(anchor)==1;header=header.replace(anchor,extra+anchor,1)
        anchor='    return data.value(row.offset+legal_hole_column(row.canonical.mask,l,h));'
        replacement=('    if(data.hole_columns==1326){if(l>h)std::swap(l,h);return data.value(row.offset+size_t(h*(h-1)/2+l));}\n'+anchor)
        assert header.count(anchor)==1;header=header.replace(anchor,replacement,1)
        (out/'hrc_cards.hpp').write_text(header,encoding='utf-8')
        # Conservatively charge all expanded buffers in addition to the old
        # compressed resource estimate, covering expansion's temporary peak.
        anchor='e.tree.reserve_budget(bytes);tables=std::make_unique<hrc_cards::AbstractionTables>(argv[2]);'
        replacement=('e.tree.reserve_budget(bytes+uint64_t(1755)*1326*2+uint64_t(16432+134459)*1326);'
                     'tables=std::make_unique<hrc_cards::AbstractionTables>(argv[2]);')
        assert cpp.count(anchor)==1;cpp=cpp.replace(anchor,replacement,1)
    (out/'hrc_research_solver.cpp').write_text(cpp,encoding='utf-8')
    compiler=Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')
    exe=out/f'hrc_research_solver-{args.mode}.exe'
    subprocess.run([str(compiler),'c++','-O3','-std=c++17','-ffp-contract=off',str(out/'hrc_research_solver.cpp'),'-o',str(exe)],
                   check=True,capture_output=True,text=True)
    print(exe,flush=True)


if __name__=='__main__':main()
