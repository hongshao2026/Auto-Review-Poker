// Read-only harness around the actual production Node, not a second update implementation.
#define main hrc_production_entry_unused
#include "../../native/hrc_research_solver.cpp"
#undef main

int main(int argc,char**argv){
    if(argc!=3)return 2;
    std::ifstream in(argv[1],std::ios::binary);std::ofstream out(argv[2],std::ios::binary);
    auto count=read<uint32_t>(in);write(out,count);
    for(uint32_t i=0;i<count;++i){
        Node node;node.street=1;node.store_format=read<int32_t>(in);node.buckets=read<int32_t>(in);node.k=read<int32_t>(in);node.init();node.updates=read<uint64_t>(in);
        auto n=read<uint32_t>(in);if(n!=node.raw.size())throw std::runtime_error("Fixture raw dimensions");read_array(in,node.raw.data(),n);
        auto extra=read<uint32_t>(in);if(extra!=node.shared_sums.size())throw std::runtime_error("Fixture shared dimensions");read_array(in,node.shared_sums.data(),extra);
        int operation=read<int32_t>(in);
        if(operation==0){int bucket=read<int32_t>(in);double w=read<double>(in),z=read<double>(in);Random rng;rng.scripted=true;rng.scripted_integer=read<int32_t>(in);Values probabilities{},utilities{};read_array(in,probabilities.data(),node.k);read_array(in,utilities.data(),node.k);node.update(rng,bucket,probabilities.data(),utilities.data(),w,z);}
        else if(operation==1){int regret=read<int32_t>(in),average=read<int32_t>(in);node.reset(regret,average);}
        else if(operation==2)node.flush();
        else throw std::runtime_error("Unknown fixture operation");
        write(out,node.updates);write(out,n);write_array(out,node.raw.data(),n);write(out,extra);write_array(out,node.shared_sums.data(),extra);
    }
}
