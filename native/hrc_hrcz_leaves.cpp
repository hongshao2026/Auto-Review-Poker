// Enumerate the saved mh/me terminal-vector order using the independent
// production settlement and equity implementation. No original code is run.
#define main hrc_training_entry_unused
#include "hrc_research_solver.cpp"
#undef main
#include <numeric>

int main(int argc,char**argv){
  try{
    if(argc!=4&&argc!=5)throw std::runtime_error("Expected tree.bin, resource directory, output.bin, [live-masks.bin]");
    Engine engine(42);engine.tree.load(argv[1],fs::path(argv[2]));
    auto& tree=engine.tree;
    if(tree.fgs)tree.fgs_baseline=tree.fgs->equities(tree.fgs_context);
    Values baseline{};
    double scale=tree.equity?1:tree.chip_scale/100.;
    for(int p=0;p<tree.players;++p)baseline[p]=tree.equity?
      (tree.fgs?tree.fgs_baseline[p]:tree.equity->baseline().total[p]):tree.initial[p]/100.;
    const bool baseline_only=argc==4;
    std::vector<uint32_t> live_masks(tree.terms.size());
    if(!baseline_only){
      std::ifstream live_input(argv[4],std::ios::binary);
      if(read<uint32_t>(live_input)!=tree.terms.size())throw std::runtime_error("Terminal live-mask count mismatch");
      read_array(live_input,live_masks.data(),live_masks.size());
      char extra;if(live_input.read(&extra,1))throw std::runtime_error("Trailing terminal live-mask data");
    }
    uint32_t leaf_count=0;for(const auto&node:tree.nodes)if(!node.k)++leaf_count;
    if(leaf_count!=tree.terms.size())throw std::runtime_error("Leaf/terminal count mismatch");
    std::ofstream out(argv[3],std::ios::binary);out.write("HRLEAF01",8);
    write(out,uint32_t(tree.players));write(out,baseline_only?uint32_t(0):leaf_count);
    write_array(out,baseline.data(),tree.players);
    if(baseline_only){if(!out)throw std::runtime_error("Baseline export write failed");std::cout<<"{\"terminals\":0,\"vectors\":0,\"baseline_only\":true,\"original_code_called\":false}";return 0;}
    uint64_t vectors=0;
    for(size_t id=0;id<tree.nodes.size();++id){
      const auto& node=tree.nodes[id];if(node.k)continue;
      const auto& terminal=tree.terms[node.terminal];
      std::vector<int> live;
      // Preserve even live zero-contribution seats; the original mh dimension
      // is based on lK's live array, not the union of eligible pot layers.
      uint32_t live_mask=live_masks[node.terminal];
      for(int p=0;p<tree.players;++p)if(live_mask&(1u<<p))live.push_back(p);
      if(live.empty())throw std::runtime_error("Terminal has no live players");
      std::vector<int> order(live.size());std::iota(order.begin(),order.end(),0);
      std::stable_sort(order.begin(),order.end(),[&](int a,int b){return terminal.paid[live[a]]>terminal.paid[live[b]];});
      uint32_t count=1;for(size_t p=1;p<live.size();++p)count*=3;
      if(vectors+count>2000000)throw std::runtime_error("HRC leaf export vector budget exceeded");
      write(out,uint32_t(id));write(out,count);
      for(uint32_t index=0;index<count;++index){
        std::fill(engine.rank,engine.rank+MAXP,0);uint32_t code=index;int best=9;
        for(size_t p=0;p<order.size();++p){
          int target=live[order[order.size()-1-p]],digit=int(code%3)-1;code/=3;
          engine.rank[target]=digit<0?0:best;if(digit>0)--best;
        }
        engine.rank[live[order[0]]]=best;
        engine.rank_ready=true;++engine.epoch;
        const double* value=engine.terminal(node.terminal);
        for(int p=0;p<tree.players;++p){double absolute=value[p]*scale+baseline[p];
          if(!std::isfinite(absolute))throw std::runtime_error("Nonfinite leaf utility");write(out,absolute);}
      }
      vectors+=count;
    }
    if(!out)throw std::runtime_error("Leaf export write failed");
    std::cout<<"{\"terminals\":"<<tree.terms.size()<<",\"vectors\":"<<vectors<<",\"original_code_called\":false}";
    return 0;
  }catch(const std::exception&error){std::cerr<<error.what()<<'\n';return 1;}
}
