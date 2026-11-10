// Production unlocked-read, layout and locked-fallback regression harness.
#define main production_main_not_called
#include "../../native/hrc_research_solver.cpp"
#undef main

static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
static bool bytes(const std::vector<double>& a,const std::vector<double>& b){return a.size()==b.size()&&std::memcmp(a.data(),b.data(),a.size()*8)==0;}
static void same_rng(const Random& a,const Random& b){check(std::equal(a.s,a.s+4,b.s)&&a.bounded_calls==b.bounded_calls&&a.double_calls==b.double_calls&&a.int_calls==b.int_calls,"RNG tape differs");}
static void same_node(const Node& a,const Node& b){check(bytes(a.raw,b.raw)&&bytes(a.shared_sums,b.shared_sums)&&a.visits==b.visits&&a.updates==b.updates,"Node state differs");}
static void same(const Engine& a,const Engine& b,bool stores){
    check(a.samples==b.samples&&a.scalar_calls==b.scalar_calls&&a.vector_calls==b.vector_calls&&a.terminal_calls==b.terminal_calls,"Traversal counters differ");
    check(a.terminal_table_lookups==b.terminal_table_lookups&&a.terminal_settlements==b.terminal_settlements,"Terminal counters differ");same_rng(a.rng,b.rng);
    check(std::memcmp(a.root_sum.data(),b.root_sum.data(),a.tree.players*sizeof(double))==0,"Root values differ");
    if(stores)for(size_t id=0;id<a.tree.nodes.size();++id)same_node(a.tree.nodes[id],b.tree.nodes[id]);
}
static void tiny(Engine& e){
    e.tree.players=3;e.tree.chip_scale=1;e.tree.initial={100,100,100};e.tree.max_memory=256ULL<<20;e.tree.estimated_memory=4096;
    e.tree.nodes.resize(3);e.tree.children={1,2};auto& n=e.tree.nodes[0];n.actor=0;n.k=2;n.buckets=169;n.init();
    for(int i=0;i<2;++i){e.tree.nodes[i+1].terminal=i;Terminal t;t.paid={10,10,10};t.base={-10,-10,-10};t.remaining={90,90,90};t.participants=i?1:3;t.folded=i?6:0;t.card_independent=i!=0;t.pots={{30,i?1u:7u,7}};e.tree.terms.push_back(t);}
}
static void table(Engine& e){auto t=hrc_terminal_table::Tables::build(e.tree.terms,e.tree.players,e.tree.chip_scale,64ULL<<20);check(bool(t),"No table");e.tree.reserve_budget(t->bytes());e.tree.terminal_tables=std::move(t);}
static bool samefile(const fs::path& a,const fs::path& b){std::ifstream x(a,std::ios::binary),y(b,std::ios::binary);return std::vector<char>(std::istreambuf_iterator<char>(x),{})==std::vector<char>(std::istreambuf_iterator<char>(y),{});}

int main(int argc,char**argv){try{
    check(argc>=2,"mode required");std::string mode=argv[1];
    if(mode=="fallback"){
        check(!hrc_unlocked_read::supported,"Fallback probe requires unsupported/forced-disabled build");
        Engine e(43);tiny(e);ParallelTrainer p(e,8,43);const auto before=e.tree.estimated_memory;
        check(!p.prepare_unlocked_reads(),"Unsupported compiler enabled unlocked reads");
        check(!e.unlocked_epsilon&&e.unlocked_cache_bytes==0&&e.tree.estimated_memory==before,"Fallback allocated read cache");
        for(const auto& n:e.tree.nodes)check(!n.unlocked_read&&!n.can_unlock_read(),"Fallback published a node flag");
        p.run(2000);uint64_t visits=0;for(auto v:e.tree.nodes[0].visits)visits+=v;
        check(e.samples==2000&&e.tree.nodes[0].updates==2000&&visits==2000,"Locked fallback lost updates");
        bool threw=false;try{(void)hrc_unlocked_read::load(e.tree.nodes[0].raw.data());}catch(const std::logic_error&){threw=true;}check(threw,"Unsupported helper silently used ordinary reads");
        std::cout<<"{\"supported\":false,\"cache_bytes\":0,\"flags\":0,\"locked_samples\":2000,\"misuse_rejected\":true}\n";
    }else if(mode=="state"){
        check(argc==3,"state output directory required");Engine e(43);tiny(e);table(e);
        const auto before=e.tree.estimated_memory;bool enabled=Engine::prepare_unlocked_reads({&e},e.tree);
        check(enabled==hrc_unlocked_read::supported,"Compiler eligibility mismatch");
        check(bool(e.unlocked_epsilon)==enabled&&e.tree.nodes[0].unlocked_read==enabled,"Cache/flag publication mismatch");
        if(!enabled)check(e.tree.estimated_memory==before,"Unsupported cache changed memory budget");
        check(Engine::prepare_terminal_pointers({&e},e.tree),"Terminal cache preparation failed");
        for(int i=0;i<1000;++i)e.step();fs::path out(argv[2]);e.save(out/"initial");
        Engine resumed(43);tiny(resumed);resumed.resume((out/"initial/checkpoint.bin").string());table(resumed);
        check(Engine::prepare_unlocked_reads({&resumed},resumed.tree)==enabled,"Resume support changed");
        check(Engine::prepare_terminal_pointers({&resumed},resumed.tree),"Resume terminal cache failed");
        for(int i=0;i<100;++i){e.step();resumed.step();check(std::equal(e.rng.s,e.rng.s+4,resumed.rng.s),"Resumed RNG mismatch");}
        for(size_t i=0;i<e.tree.nodes.size();++i)same_node(e.tree.nodes[i],resumed.tree.nodes[i]);
        e.save(out/"continuous");resumed.save(out/"resumed");check(samefile(out/"continuous/checkpoint.bin",out/"resumed/checkpoint.bin"),"Resume checkpoint differs");
        std::cout<<"{\"supported\":"<<(enabled?"true":"false")<<",\"cache_bytes\":"<<e.unlocked_cache_bytes<<",\"resume_equal\":true,\"samples\":1100}\n";
    }else if(mode=="layout"){

        Node n;const auto* base=reinterpret_cast<const char*>(&n);auto offset=[&](const void* p){return static_cast<const char*>(p)-base;};
        check(sizeof(Node)==256&&alignof(Node)==64,"Unexpected Node size/alignment");
        check(offset(&n.updates)==192,"Unexpected writer offset");
        check(offset(&n.frequency)+sizeof(n.frequency)<=192,"Readonly metadata overlaps writer line");
        check(offset(&n.divisor_cached)+sizeof(n.divisor_cached)<=256,"Writer fields cross node boundary");
        std::vector<Node> nodes(100);for(size_t i=0;i<nodes.size();++i){check(reinterpret_cast<uintptr_t>(&nodes[i])%64==0,"Vector does not honor alignment");if(i)check(reinterpret_cast<const char*>(&nodes[i])-reinterpret_cast<const char*>(&nodes[i-1])==256,"Wrong vector stride");}
        std::cout<<"{\"node_bytes\":"<<sizeof(Node)<<",\"node_alignment\":"<<alignof(Node)<<",\"updates_offset\":"<<offset(&n.updates)<<",\"vector_stride_verified\":true}\n";
    }else if(mode=="edges"){

        const uint64_t bits[]={0,0x8000000000000000ULL,1,0x8000000000000001ULL,0x0010000000000000ULL,0x8010000000000000ULL,0x3ff0000000000000ULL,0xbff0000000000000ULL,0x7fefffffffffffffULL,0xffefffffffffffffULL,0x7ff0000000000000ULL,0xfff0000000000000ULL,0x7ff8000000000001ULL,0xfff8000000002345ULL};
        uint64_t count=0;Random random(772);
        for(int k:{2,3,4,16})for(int special:{0,1,2}){
            Node n;n.k=k;n.buckets=1;n.special=special;n.init();
            const int fixed=k<=3?int(std::pow(double(std::size(bits)),k)):0;
            for(int i=0;i<fixed+10000;++i){int number=i;double r[MAXA],expected[MAXA],actual[MAXA];
                for(int a=0;a<k;++a){uint64_t value=i<fixed?bits[number%std::size(bits)]:random.next();number/=std::size(bits);std::memcpy(r+a,&value,8);n.raw[n.regret(0)+a]=r[a];}
                normalize(r,k,special>0,expected);n.strategy_atomic(0,actual);
                if(std::memcmp(expected,actual,k*8)!=0){std::cerr<<"Edge mismatch k="<<k<<" special="<<special<<" sample="<<i<<'\n';for(int a=0;a<k;++a){uint64_t x,y;std::memcpy(&x,expected+a,8);std::memcpy(&y,actual+a,8);std::cerr<<a<<':'<<std::hex<<x<<'/'<<y<<std::dec<<' ';}throw std::runtime_error("Normalization edge bytes differ");}
                ++count;
            }
        }
        std::cout<<"{\"normalization_edge_vectors\":"<<count<<",\"bitwise_equal\":true,\"signed_zero_nan_infinity_subnormal\":true}\n";
    }else if(mode=="unit"){

        uint64_t snapshots=0;
        for(int format:{23,25})for(int k:{2,3,4,16})for(int special:{0,1,2})for(bool scripted:{false,true}){
            Node old,n;old.k=n.k=k;old.buckets=n.buckets=3;old.store_format=n.store_format=format;old.special=n.special=special;old.init();n.init();n.unlocked_read=true;
            Random x(1543+k),y(1543+k);x.scripted=y.scripted=scripted;
            for(int i=0;i<300;++i){int h=i%3;double p[MAXA],q[MAXA],expected[MAXA];for(int a=0;a<k;++a)q[a]=double((i*7+a*11)%37-18)/3;
                old.strategy(h,expected);n.strategy_atomic(h,p);check(std::memcmp(p,expected,k*8)==0,"Atomic normalization differs");
                x.scripted_integer=y.scripted_integer=i%4==0?INT32_MIN:i%4==1?0:i%4==2?-17:19;
                double w=i%7==0?0:i%11==0?2.5:1,z=i%3==0?0:i%3==1?.25:1;
                old.update(x,h,p,q,w,z);n.update(y,h,p,q,w,z);same_node(old,n);same_rng(x,y);++snapshots;
                if(i%71==0){old.flush();n.flush();same_node(old,n);}
                if(i==90||i==150||i==210){bool r=i!=90,a=i!=150;old.reset(r,a);n.reset(r,a);same_node(old,n);}
            }
        }
        Engine old(433),e(433);uint64_t samples=0,exploration_draws=0;
        for(int k:{2,3,4,16})for(int shape=0;shape<4;++shape)for(double count:{0.,100.,1e6,1e9}){
            Node n;n.k=k;n.buckets=1;n.init();n.raw[0]=count;double p[MAXA]{};
            if(shape==0)p[k-1]=1;else if(shape==1)for(int a=0;a<k;++a)p[a]=1./k;else if(shape==2){p[0]=.1;p[k-1]=.2;}
            for(int i=0;i<4096;++i){int a=old.sample(n,p),b=e.sample_snapshot(k,p,1/std::sqrt(count+10000));check(a==b,"Sample result differs");same_rng(old.rng,e.rng);++samples;}
        }
        exploration_draws=e.rng.bounded_calls;check(exploration_draws>0,"Exploration not covered");
        std::cout<<"{\"node_update_snapshots\":"<<snapshots<<",\"sample_rng_tapes\":"<<samples<<",\"exploration_draws\":"<<exploration_draws<<",\"cache_entry_bytes\":"<<sizeof(hrc_unlocked_read::EpsilonCache)<<",\"node_bytes\":"<<sizeof(Node)<<"}\n";
    }else if(mode=="budget"){
        Engine a(43),b(44);tiny(a);tiny(b);b.shared_nodes=&a.tree.nodes;b.resources_tree=&a.tree;
        const uint64_t before=a.tree.estimated_memory,total=2*(a.tree.nodes.size()*sizeof(hrc_unlocked_read::EpsilonCache)+64);
        a.tree.max_memory=before+total-1;check(!Engine::prepare_unlocked_reads({&a,&b},a.tree),"One-byte-short budget accepted");
        check(!a.unlocked_epsilon&&!b.unlocked_epsilon&&a.tree.estimated_memory==before&&!a.tree.nodes[0].unlocked_read,"Partial failed publication");
        a.tree.max_memory=before+total;const Random before_rng=a.rng;check(Engine::prepare_unlocked_reads({&a,&b},a.tree),"Exact budget failed");check(a.tree.estimated_memory==before+total,"All-worker charge wrong");same_rng(before_rng,a.rng);
        check(Engine::prepare_unlocked_reads({&a,&b},a.tree)&&a.tree.estimated_memory==before+total,"Preparation not idempotent");
        Engine e(1);e.tree.nodes.resize(7);e.tree.max_memory=1ULL<<20;
        for(auto& n:e.tree.nodes){n.k=2;n.buckets=3;n.init();}
        e.tree.nodes[1].store_format=25;e.tree.nodes[1].init();
        e.tree.nodes[2].store_format=27;e.tree.nodes[2].init();e.tree.nodes[3].store_format=31;e.tree.nodes[3].init();
        e.tree.nodes[4].frequency=std::make_unique<hrc_policy::FrequencyStore>(3,2);
        e.tree.nodes[5].locks=std::make_unique<hrc_policy::BucketLocks>(2,3,std::vector<std::vector<double>>{{.2,.2,.2},{}});
        e.tree.nodes[6].locks=std::make_unique<hrc_policy::BucketLocks>(2,3);
        check(Engine::prepare_unlocked_reads({&e},e.tree),"Mixed tree failed");
        for(int i=0;i<7;++i)check(e.tree.nodes[i].unlocked_read==(i==0||i==1||i==6),"Eligibility mismatch");
        for(int i=2;i<6;++i){double p[MAXA],expected[MAXA];e.tree.nodes[i].strategy(0,expected);e.choose(i,e.tree.nodes[i],0,p);check(std::memcmp(p,expected,16)==0,"Fallback strategy differs");}
        std::cout<<"{\"budget\":true,\"two_worker_bytes\":"<<total<<",\"eligibility_and_fallback\":true,\"rng_untouched\":true}\n";
    }else if(mode=="parallel"){
        Engine e(43);tiny(e);ParallelTrainer p(e,8,43);table(e);const uint64_t before=e.tree.estimated_memory,bytes=8*(e.tree.nodes.size()*sizeof(hrc_unlocked_read::EpsilonCache)+64);
        check(p.prepare_unlocked_reads(),"Late publication failed");check(e.tree.estimated_memory==before+bytes,"Worker caches not fully charged");
        const uint64_t terminal_bytes=8*(e.tree.terms.size()*sizeof(Engine::TerminalPointer)+64);
        const uint64_t reclaimed=8*(e.tree.terms.size()*sizeof(Engine::WorkerTerminalCache)+64);
        check(e.worker_terminal_cache&&e.worker_terminal_bytes==reclaimed/8,"Owner fallback cache was not charged");
        const uint64_t maximum=e.tree.max_memory,after_unlocked=e.tree.estimated_memory;
        e.tree.max_memory=after_unlocked+terminal_bytes-1;
        check(!p.prepare_terminal_pointers(),"Pointer preparation borrowed future cache refunds");
        check(e.tree.estimated_memory==after_unlocked&&e.worker_terminal_cache&&e.worker_terminal_bytes==reclaimed/8&&!e.terminal_pointer_cache,"Failed pointer preparation changed cache ownership or budget");
        e.tree.max_memory=after_unlocked+terminal_bytes;
        check(p.prepare_terminal_pointers(),"Combined terminal preparation failed");
        const uint64_t expected=before+bytes+terminal_bytes-reclaimed;
        check(e.tree.estimated_memory==expected,"Combined scratch budget wrong");
        check(!e.worker_terminal_cache&&!e.worker_terminal_bytes,"Published terminal pointers retained owner fallback cache");
        check(e.terminal_pointer_bytes==terminal_bytes/8&&e.terminal_pointer_table==e.tree.terminal_tables,"Pointer-cache publication mismatch");
        e.tree.max_memory=maximum;
        p.run(5000);check(p.run_adaptive(5000,std::chrono::steady_clock::now()+std::chrono::seconds(5))==5000,"Adaptive sample count differs");
        check(e.samples==10000,"Parallel count failed");uint64_t visits=0;for(auto x:e.tree.nodes[0].visits)visits+=x;check(visits==10000&&e.tree.nodes[0].updates==10000,"Writer updates were lost");
        for(double x:e.tree.nodes[0].raw)check(std::isfinite(x),"Nonfinite parallel raw");
        e.tree.nodes[0].flush();check(e.tree.nodes[0].raw[0]==10000,"Quiescent flush failed");e.tree.nodes[0].reset(true,true);p.run(1000);
        check(e.tree.nodes[0].updates==1000,"Reset writer clock failed");visits=0;for(auto x:e.tree.nodes[0].visits)visits+=x;check(visits==1000,"Reset visits failed");
        check(p.prepare_unlocked_reads()&&p.prepare_terminal_pointers()&&e.tree.estimated_memory==expected,"Parallel preparation not idempotent");
        std::cout<<"{\"parallel_late_publication\":true,\"samples\":11000,\"no_lost_updates\":true,\"reset_quiescence\":true,\"worker_terminal_caches_reclaimed\":true,\"reclaimed_terminal_bytes\":"<<reclaimed<<",\"cache_bytes\":"<<bytes<<"}\n";
    }else if(mode=="tree"){
        check(argc==5,"tree.bin resources output required");Engine old(43),e(43);
        old.tree.load(argv[2],argv[3],{},2ULL<<30);e.tree.load(argv[2],argv[3],{},2ULL<<30);old.tree.prepare_constant_scalars(true);e.tree.prepare_constant_scalars(true);
        hrc_cards::AbstractionTables cards(argv[3]);old.tables=e.tables=&cards;table(old);e.tree.terminal_tables=old.tree.terminal_tables;e.tree.reserve_budget(e.tree.terminal_tables->bytes());
        check(Engine::prepare_unlocked_reads({&e},e.tree),"Tree preparation failed");check(Engine::prepare_terminal_pointers({&e},e.tree),"Tree pointer preparation failed");
        for(int i=0;i<1000;++i){old.step();e.step();same(old,e,i%10==0);}same(old,e,true);
        fs::path out(argv[4]);old.save(out/"baseline");e.save(out/"candidate");check(samefile(out/"baseline/checkpoint.bin",out/"candidate/checkpoint.bin"),"Checkpoint differs");
        Engine resumed(43);resumed.tree.load(argv[2],argv[3],{},2ULL<<30);resumed.tree.prepare_constant_scalars(true);resumed.tables=&cards;resumed.resume((out/"candidate/checkpoint.bin").string());table(resumed);check(Engine::prepare_unlocked_reads({&resumed},resumed.tree),"Resumed preparation failed");check(Engine::prepare_terminal_pointers({&resumed},resumed.tree),"Resume pointer preparation failed");
        for(int i=0;i<100;++i){old.step();e.step();resumed.step();same(old,e,i%10==0);check(std::equal(e.rng.s,e.rng.s+4,resumed.rng.s),"Resume RNG differs");}same(old,e,true);
        e.save(out/"continuous");resumed.save(out/"resumed");check(samefile(out/"continuous/checkpoint.bin",out/"resumed/checkpoint.bin"),"Resume checkpoint differs");
        std::cout<<"{\"real_tree_steps\":1100,\"full_checkpoint_equal\":true,\"resume_equal\":true,\"cache_bytes\":"<<e.unlocked_cache_bytes<<",\"scalar_calls\":"<<e.scalar_calls<<"}\n";
    }else throw std::runtime_error("Unknown mode");return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
