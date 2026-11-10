#pragma once
// Preflop selection follows original lU/lR reach extraction and mn mode1/2.
// Included after Tree/Node definitions; no original classes are executed.
struct SamplingScope {
    bool selected=false;
    int root=0,mode=0;
    std::vector<uint32_t> path;
    std::vector<uint8_t> inside;
    std::vector<int> targets;
    std::vector<std::array<double,169>> reach;
    std::unique_ptr<hrc_chance::Sampler> sampler;
    std::string reach_sha256;

    SamplingScope(Tree& tree,const std::string& descriptor):root(tree.root) {
        if(descriptor.empty()||descriptor=="-")return;
        selected=true;
        if(tree.chance)throw std::invalid_argument("Selected preflop scope cannot be combined with a fixed-board/range subtree");
        std::ifstream input(descriptor,std::ios::binary);char magic[8];read_array(input,magic,8);
        if(std::memcmp(magic,"HRSCOPE1",8))throw std::invalid_argument("Invalid sampling scope descriptor");
        auto count=read<uint32_t>(input);if(count>256)throw std::invalid_argument("Sampling path exceeds 256 edges");
        path.resize(count);read_array(input,path.data(),count);if(input.peek()!=std::char_traits<char>::eof())throw std::invalid_argument("Trailing sampling scope data");
        tree.reserve_budget(tree.nodes.size()*(sizeof(uint8_t)+sizeof(int)*2)+tree.players*(169*8+1326*24)+32768);
        reach.resize(tree.players);for(auto& row:reach)row.fill(1.);
        for(auto edge:path){const auto& node=tree.nodes[root];
            if(!node.k||node.street!=0||node.buckets!=169||edge>=uint32_t(node.k))throw std::invalid_argument("Sampling scope requires a valid preflop decision path");
            for(int h=0;h<169;++h){auto p=node.display(h);double value=p[edge];if(!std::isfinite(value)||value<0||value>1)throw std::invalid_argument("Invalid frozen prefix display probability");reach[node.actor][h]*=value;}
            root=tree.children[node.first+edge];
        }
        if(!tree.nodes[root].k||tree.nodes[root].street!=0||tree.nodes[root].buckets!=169)throw std::invalid_argument("Selected Subtree requires a preflop decision, not a terminal/postflop node");
        inside.assign(tree.nodes.size(),0);std::vector<int> stack{root};std::vector<bool> actors(tree.players,false);
        while(!stack.empty()){int id=stack.back();stack.pop_back();if(inside[id])continue;inside[id]=1;const auto& n=tree.nodes[id];if(!n.k)continue;
            if(!actors[n.actor]){actors[n.actor]=true;targets.push_back(n.actor);}
            for(int a=n.k-1;a>=0;--a)stack.push_back(tree.children[n.first+a]);}
        // A shared child reachable without the selected node would break the
        // guarantee that all nodes outside this public subtree stay unchanged.
        std::vector<uint8_t> seen(tree.nodes.size(),0);stack={tree.root};
        while(!stack.empty()){int id=stack.back();stack.pop_back();if(id==root||seen[id])continue;seen[id]=1;
            if(inside[id])throw std::invalid_argument("Selected subtree shares a descendant with an outside branch");
            const auto& n=tree.nodes[id];for(int a=0;a<n.k;++a)stack.push_back(tree.children[n.first+a]);}
        bool active_uniform=true;hrc_chance::Config cfg;cfg.ranges.resize(tree.players);
        std::vector<std::vector<uint64_t>> support;
        hrc_digest::Sha256 hash;
        for(int p=0;p<tree.players;++p){const auto& row=reach[p];hash.update(reinterpret_cast<const char*>(row.data()),169*sizeof(double));
            auto bounds=std::minmax_element(row.begin(),row.end());if(*bounds.second<=0)throw std::invalid_argument("Selected subtree is unreachable: a prefix range has zero mass");
            bool uniform=*bounds.first==*bounds.second;if(actors[p]&&!uniform)active_uniform=false;
            if(uniform)continue;
            auto& weights=cfg.ranges[p];weights.resize(1326);support.emplace_back();
            for(int high=1;high<52;++high)for(int low=0;low<high;++low){int c=high*(high-1)/2+low;weights[c]=row[hrc_cards::preflop_class(c)];if(weights[c]>0)support.back().push_back((1ULL<<high)|(1ULL<<low));}
        }
        reach_sha256=hash.finish();
        // Exact support feasibility when the bounded search completes. Never
        // replace an impossible joint range with independent conditional draws.
        std::stable_sort(support.begin(),support.end(),[](const auto&a,const auto&b){return a.size()<b.size();});
        uint64_t work=0;std::function<bool(size_t,uint64_t)> possible=[&](size_t i,uint64_t used){
            if(i==support.size())return true;
            for(auto cards:support[i]){if(++work>1000000)throw NativeResourceLimit("Scope reachability search budget exhausted; reachability remains unknown");if(!(cards&used)&&possible(i+1,used|cards))return true;}return false;};
        if(!possible(0,0))throw std::invalid_argument("Selected subtree is unreachable: prefix ranges have no collision-free joint deal");
        mode=root==tree.root?0:active_uniform?1:2;
        sampler=std::make_unique<hrc_chance::Sampler>(std::move(cfg));
    }
    bool contains(int id)const{return !selected||inside[id];}
};
