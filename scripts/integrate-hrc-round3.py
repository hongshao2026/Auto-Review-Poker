"""Install the measured combination; preserve all frozen candidate artifacts."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
ROUND=ROOT/'.research-cache/throughput-round3-20261108'
SOURCE=ROUND/'combined-direct23-zero-alignnode'


def replace(text,old,new):
    assert text.count(old)==1,old[:120]
    return text.replace(old,new,1)


def main():
    original=ROOT/'native/hrc_research_solver.cpp'
    assert hashlib.sha256(original.read_bytes()).hexdigest()=='60924af9de656cea69cf52845eb2051ac9b23a9bdb095dbef866f508ec36569e'
    names=('hrc_research_solver.cpp','hrc_parallel.hpp','hrc_cards.hpp','hrc_flat_board_map.hpp','hrc_unlocked_read.hpp')
    for name in names:shutil.copy2(SOURCE/name,ROOT/'native'/name)
    header=(ROUND/'combined-review-text/hrc_unlocked_read.hpp.proposed.txt').read_text(encoding='utf-8')
    (ROOT/'native/hrc_unlocked_read.hpp').write_text(header,encoding='utf-8')
    cpp=original.read_text(encoding='utf-8')
    cpp=replace(cpp,'bool can_unlock_read()const{return k&&','bool can_unlock_read()const{return hrc_unlocked_read::supported&&k&&')
    cpp=replace(cpp,'if(!bucket_ready[n.street]&&n.street>0&&!resources().chance){',
                'if(!bucket_ready[n.street]&&n.street>0&&tree.players<=3&&!resources().chance){')
    cpp=replace(cpp,'        pending.reserve(engines.size());\n        try{for(size_t i=0;i<engines.size();++i)',
                '        try{pending.reserve(engines.size());for(size_t i=0;i<engines.size();++i)')
    cpp=replace(cpp,'struct alignas(64) Node {','// Keep immutable traversal metadata separate from the writer-only counters.\nstruct alignas(64) Node {')
    cpp=replace(cpp,'    int hand(const Node& n){\n',
                '    int hand(const Node& n){\n        // For 2/3 seats, fill one static row for all seats once. Larger tables\n        // retain lazy actor mapping; dynamic tables always use their own path.\n')
    original.write_text(cpp,encoding='utf-8')
    manifest={'source':str(SOURCE),'adjustments':['Atomic capability gate and safe locked fallback for unsupported compilers',
              'Eager static buckets restricted to measured 2/3-seat route',
              'Staging allocation failure also uses locked fallback'],
              'files':{name:hashlib.sha256((ROOT/'native'/name).read_bytes()).hexdigest() for name in names}}
    (ROUND/'production-integration.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest),flush=True)


if __name__=='__main__':main()
