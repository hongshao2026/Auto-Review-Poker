#pragma once
// Shared-policy asynchronous traversal. Engines own chance/RNG/terminal and
// monetary caches; node reads and writes synchronize, never across recursion.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <exception>
#include <thread>

class ParallelTrainer {
    Engine& main_;
    std::vector<std::unique_ptr<Engine>> extra_;
    std::vector<Engine*> engines_;
    std::unique_ptr<hrc_node_mutex::NodeMutex[]> node_locks_;
    std::vector<std::thread> threads_;
    std::mutex control_;
    std::condition_variable start_,done_;
    std::vector<uint64_t> jobs_;
    uint64_t generation_=0;
    size_t pending_=0;
    bool stopping_=false;
    std::atomic<bool> abort_{false};
    // One control slice may contain many independently claimed 250-deal blocks.
    // These fields are published under control_ before waking the workers.
    bool adaptive_=false,failed_=false;
    uint64_t adaptive_budget_=0;
    std::chrono::steady_clock::time_point deadline_;
    std::atomic<uint64_t> next_ticket_{0};
    std::atomic<bool> pause_{false};
    uint64_t control_rounds_=0,adaptive_rounds_=0,claimed_blocks_=0;
    std::exception_ptr error_;
    void adaptive_work(size_t id){
        while(!abort_.load(std::memory_order_relaxed)&&!pause_.load(std::memory_order_relaxed)){
            if(std::chrono::steady_clock::now()>=deadline_){pause_.store(true,std::memory_order_relaxed);break;}
            uint64_t first=next_ticket_.load(std::memory_order_relaxed),count=0;
            for(;;){
                if(first>=adaptive_budget_)return;
                count=std::min(uint64_t(250),adaptive_budget_-first);
                if(next_ticket_.compare_exchange_weak(first,first+count,std::memory_order_relaxed))break;
            }
            // A normal pause finishes already claimed blocks. Exceptions abort
            // promptly; a partial traversal must use the caller's rollback path.
            for(uint64_t i=0;i<count&&!abort_.load(std::memory_order_relaxed);++i)engines_[id]->step();
        }
    }
    void work(size_t id){
        try {if(adaptive_)adaptive_work(id);
            else for(uint64_t i=0;i<jobs_[id]&&!abort_.load(std::memory_order_relaxed);++i)engines_[id]->step();}
        catch(...){std::lock_guard<std::mutex> lock(control_);if(!error_)error_=std::current_exception();abort_.store(true);}
    }
    void worker(size_t id){
        uint64_t seen=0;std::unique_lock<std::mutex> lock(control_);
        for(;;){start_.wait(lock,[&]{return stopping_||generation_!=seen;});if(stopping_)return;seen=generation_;
            lock.unlock();work(id);lock.lock();if(--pending_==0)done_.notify_one();}
    }
    void stop(){
        {std::lock_guard<std::mutex> lock(control_);stopping_=true;}start_.notify_all();
        for(auto& thread:threads_)if(thread.joinable())thread.join();
        main_.node_mutexes=nullptr;
    }
    void capture(){
        for(size_t i=0;i<engines_.size();++i)std::copy(engines_[i]->rng.s,engines_[i]->rng.s+4,main_.parallel_rng[i].begin());
    }
    void collect(){
        for(auto& engine:extra_){for(int p=0;p<main_.tree.players;++p){main_.root_sum[p]+=engine->root_sum[p];engine->root_sum[p]=0;}
            main_.samples+=engine->samples;engine->samples=0;
            main_.scope_samples+=engine->scope_samples;engine->scope_samples=0;
            main_.sampling_attempts+=engine->sampling_attempts;engine->sampling_attempts=0;
            main_.sampling_deals+=engine->sampling_deals;engine->sampling_deals=0;
            main_.scalar_calls+=engine->scalar_calls;main_.vector_calls+=engine->vector_calls;main_.terminal_calls+=engine->terminal_calls;
            main_.terminal_table_lookups+=engine->terminal_table_lookups;engine->terminal_table_lookups=0;
            main_.terminal_settlements+=engine->terminal_settlements;engine->terminal_settlements=0;
            main_.constant_scalar_calls+=engine->constant_scalar_calls;engine->constant_scalar_calls=0;
            engine->scalar_calls=engine->vector_calls=engine->terminal_calls=0;}
        capture();
    }
public:
    ParallelTrainer(Engine& main,int count,uint64_t seed):main_(main){
        if(count<2||count>32)throw std::invalid_argument("Parallel workers require 2..32 threads");
        // Immutable lookup tables/topology are shared. Account for each private
        // terminal set/cache and a conservative 1MiB thread-stack reserve.
        const uint64_t terminal_bytes=main.tree.terms.empty()?0:uint64_t(main.tree.terms.size())*sizeof(Engine::WorkerTerminalCache)+64;
        uint64_t private_bytes=sizeof(Engine)+(uint64_t(1)<<20)+terminal_bytes;
        if(main.tree.equity)private_bytes+=main.tree.equity->cache_bytes();
        if(main.tree.fgs)private_bytes+=main.tree.fgs->cache_memory_bound();
        const uint64_t owner_terminal_bytes=main.worker_terminal_cache?0:terminal_bytes;
        main.tree.reserve_budget(uint64_t(count-1)*private_bytes+main.tree.nodes.size()*sizeof(hrc_node_mutex::NodeMutex)+owner_terminal_bytes);
        // Keep the owner out of the shared metadata's cache lines as well.
        // Preserve any pre-existing owner cache exactly; new workers start
        // cold, matching the prior deep copy followed by cached_deal reset.
        if(owner_terminal_bytes){
            auto pending=std::make_unique<Engine::WorkerTerminalCache[]>(main.tree.terms.size());
            for(size_t id=0;id<main.tree.terms.size();++id){pending[id].value=main.tree.terms[id].value;pending[id].cached_deal=main.tree.terms[id].cached_deal;}
            main.worker_terminal_cache=std::move(pending);main.worker_terminal_bytes=terminal_bytes;
        }
        node_locks_=std::make_unique<hrc_node_mutex::NodeMutex[]>(main.tree.nodes.size());
        auto restored=main.parallel_rng;
        engines_.push_back(&main);jobs_.resize(count);
        for(int i=1;i<count;++i){
            auto engine=std::make_unique<Engine>(Random::mix(seed));auto& t=engine->tree;
            t.players=main.tree.players;t.root=main.tree.root;t.initial=main.tree.initial;t.chip_scale=main.tree.chip_scale;
            t.raked=main.tree.raked;t.rake=main.tree.rake;
            if(!main.tree.terms.empty())engine->worker_terminal_cache=std::make_unique<Engine::WorkerTerminalCache[]>(main.tree.terms.size());
            engine->worker_terminal_bytes=terminal_bytes;
            t.chance_cancel=main.tree.chance_cancel;t.fgs_context=main.tree.fgs_context;t.fgs_baseline=main.tree.fgs_baseline;
            if(main.tree.equity)t.equity=main.tree.equity->fork();
            if(main.tree.fgs)t.fgs=main.tree.fgs->fork();
            engine->v4=main.v4;engine->tables=main.tables;engine->resources_tree=&main.tree;
            engine->scope=main.scope;engine->root_mean_valid=main.root_mean_valid;
            engine->shared_nodes=&main.tree.nodes;engine->node_mutexes=node_locks_.get();
            if(restored.size()==size_t(count))std::copy(restored[i].begin(),restored[i].end(),engine->rng.s);
            engines_.push_back(engine.get());extra_.push_back(std::move(engine));
        }
        main.training_threads=count;main.node_mutexes=node_locks_.get();main.parallel_rng.resize(count);capture();
        try {for(int i=1;i<count;++i)threads_.emplace_back([this,i]{worker(size_t(i));});}
        catch(...){stop();throw;}
    }
    ~ParallelTrainer(){stop();}
    bool prepare_terminal_pointers(){
        std::lock_guard<std::mutex> lock(control_);
        if(pending_)throw std::logic_error("Terminal pointer preparation requires quiescent workers");
        return Engine::prepare_terminal_pointers(engines_,main_.tree);
    }
    bool prepare_unlocked_reads(){
        std::lock_guard<std::mutex> lock(control_);
        if(pending_)throw std::logic_error("Unlocked-read preparation requires quiescent workers");
        return Engine::prepare_unlocked_reads(engines_,main_.tree);
    }
    // Thread-safe request for an active adaptive slice. It is not a permanent
    // cancellation flag; each new slice clears it. Caller may save only on return.
    void request_pause(){pause_.store(true,std::memory_order_relaxed);}
    uint64_t control_rounds()const{return control_rounds_;}
    uint64_t adaptive_rounds()const{return adaptive_rounds_;}
    uint64_t claimed_blocks()const{return claimed_blocks_;}
    void run(uint64_t samples){
        if(failed_)throw std::runtime_error("Failed parallel trainer requires checkpoint rollback");
        {std::lock_guard<std::mutex> lock(control_);error_=nullptr;abort_.store(false);adaptive_=false;
            for(size_t i=0;i<jobs_.size();++i)jobs_[i]=samples/jobs_.size()+(i<samples%jobs_.size());
            pending_=threads_.size();++generation_;++control_rounds_;}
        start_.notify_all();work(0);
        std::exception_ptr error;
        {std::unique_lock<std::mutex> lock(control_);done_.wait(lock,[&]{return pending_==0;});error=error_;}
        collect();
        if(error){failed_=true;std::rethrow_exception(error);}
    }
    // Return the actual completed sample count, never the number of issued
    // tickets. This call returns only after every worker is quiescent, so the
    // existing CI/reset/save/RNG-tail code can safely inspect the whole engine.
    uint64_t run_adaptive(uint64_t maximum_samples,std::chrono::steady_clock::time_point deadline){
        if(failed_)throw std::runtime_error("Failed parallel trainer requires checkpoint rollback");
        if(!maximum_samples||std::chrono::steady_clock::now()>=deadline)return 0;
        const uint64_t before=main_.samples;
        {std::lock_guard<std::mutex> lock(control_);error_=nullptr;abort_.store(false);pause_.store(false);
            adaptive_=true;adaptive_budget_=maximum_samples;deadline_=deadline;next_ticket_.store(0);
            pending_=threads_.size();++generation_;++control_rounds_;++adaptive_rounds_;}
        start_.notify_all();work(0);
        std::exception_ptr error;
        {std::unique_lock<std::mutex> lock(control_);done_.wait(lock,[&]{return pending_==0;});error=error_;}
        const uint64_t claimed=next_ticket_.load(std::memory_order_relaxed);
        claimed_blocks_+=claimed/250+uint64_t(claimed%250!=0);
        collect();
        if(error){failed_=true;std::rethrow_exception(error);}
        return main_.samples-before;
    }
};
