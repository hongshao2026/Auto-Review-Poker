"""Build the three-node, eight-stripe candidate from the pinned native solver."""
import argparse
import json
from pathlib import Path
import runpy
import shutil

ROOT = Path(__file__).resolve().parents[1]
BUILD = runpy.run_path(str(ROOT / 'scripts/build-hrc-mtt-writer-candidates.py'))
ACCEPTED = BUILD['ACCEPTED']
sha, run, replace_once = (BUILD[name] for name in ('sha', 'run', 'replace_once'))


def edit(path, replacements):
    source = path.read_text(encoding='utf-8')
    for old, new in replacements:
        source = replace_once(source, old, new)
    path.write_text(source, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    if not output.is_relative_to(ROOT.resolve()):
        raise ValueError('Candidate artifacts must stay inside the workspace')
    baseline = json.loads((ACCEPTED / 'manifest.json').read_text(encoding='utf-8'))
    baseline_exe = ACCEPTED / 'solver.exe'
    assert sha(baseline_exe) == baseline['executable_sha256']
    identity = baseline['identity_spec']
    frozen = Path(identity['translation_unit']).parent
    for name, item in identity['source_files'].items():
        assert sha(frozen / name) == item['sha256']
        assert sha(ROOT / 'native' / name) == item['sha256']
    compiler = baseline['command'][0]
    assert sha(Path(compiler)) == identity['compiler']['sha256']
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    shutil.copytree(frozen, source)
    for header in ('hrc_hot_bucket_locks.hpp', 'hrc_hot_bucket_test.hpp'):
        shutil.copy2(ROOT / 'scripts/native' / header, source)
    edit(source / 'hrc_research_solver.cpp', [
        ('struct alignas(64) Node {', '#include "hrc_hot_bucket_locks.hpp"\n\nstruct alignas(64) Node {'),
        ('    hrc_node_mutex::NodeMutex* node_mutexes=nullptr;',
         '    hrc_node_mutex::NodeMutex* node_mutexes=nullptr;\n'
         '    hrc_hot_bucket::HotNode* hot_nodes=nullptr;\n'
         '    std::array<hrc_hot_bucket::WorkerNode,hrc_hot_bucket::node_count> hot_worker;'),
        ('    void update(int id,Node& n,int h,const double* p,const double* q,double marker){',
         '''    void update(int id,Node& n,int h,const double* p,const double* q,double marker){
        const unsigned hot_id=unsigned(id-hrc_hot_bucket::first_node);
        if(hot_id<hrc_hot_bucket::node_count&&hot_nodes){
            hrc_hot_bucket::update(n,rng,hot_nodes[hot_id],hot_worker[hot_id],h,p,q);
            return;
        }'''),
        ('int main(int argc,char** argv){', '#include "hrc_hot_bucket_test.hpp"\n\nint main(int argc,char** argv){'),
        ('    if(argc==2&&std::string(argv[1])=="--self-test"){probes();return 0;}',
         '    if(argc==2&&std::string(argv[1])=="--self-test-hot-buckets"){probe_hot_buckets();return 0;}\n'
         '    if(argc==2&&std::string(argv[1])=="--self-test"){probes();return 0;}'),
        ('    auto write_optimization=[&](){const auto& table=e.tree.terminal_tables;',
         '''    auto write_optimization=[&](){const auto& table=e.tree.terminal_tables;
        std::cout<<",\\"hot_bucket_stripes\\":"<<(e.hot_nodes?hrc_hot_bucket::stripe_count:0)
            <<",\\"hot_bucket_node_count\\":"<<(e.hot_nodes?hrc_hot_bucket::node_count:0);'''),
    ])
    edit(source / 'hrc_parallel.hpp', [
        ('    std::unique_ptr<hrc_node_mutex::NodeMutex[]> node_locks_;',
         '    std::unique_ptr<hrc_node_mutex::NodeMutex[]> node_locks_;\n'
         '    std::unique_ptr<hrc_hot_bucket::HotNode[]> hot_nodes_;'),
        ('        main_.node_mutexes=nullptr;', '        main_.hot_nodes=nullptr;\n        main_.node_mutexes=nullptr;'),
        ('        capture();\n    }\npublic:',
         '''        // All workers have finished their current slice. The same exact
        // counters are then consumed by CI, checkpoint saves and resume.
        if(hot_nodes_){
            for(int i=0;i<hrc_hot_bucket::node_count;++i)
                main_.tree.nodes[hrc_hot_bucket::first_node+i].updates=hot_nodes_[i].total_updates();
        }
        capture();
    }
    void prepare_hot_nodes(){
        using namespace hrc_hot_bucket;
        if(hot_nodes_||main_.tree.identity!=tree_identity||!main_.scope||
           !main_.scope->selected||main_.scope->path.size()!=1||main_.scope->path[0]!=0||
           main_.sampling_root()!=first_node||main_.tree.nodes.size()<first_node+node_count)return;
        for(int i=0;i<node_count;++i){
            const auto& node=main_.tree.nodes[first_node+i];
            if(!node.unlocked_read||node.base_format()!=23||node.street!=0||node.actor!=i+1||
               node.special!=0||node.buckets!=169||!std::isfinite(node.raw[0])||
               node.raw[0]<0||node.raw[0]>double(node.updates))return;
        }
        constexpr size_t bytes=node_count*sizeof(HotNode);
        if(bytes>main_.tree.max_memory-main_.tree.estimated_memory)return;
        auto hot=std::make_unique<HotNode[]>(node_count);
        for(int i=0;i<node_count;++i){
            hot[i].initial_updates=main_.tree.nodes[first_node+i].updates;
            hot[i].worker_count=engines_.size();
            for(size_t j=0;j<engines_.size();++j)hot[i].workers[j]=&engines_[j]->hot_worker[i];
        }
        main_.tree.reserve_budget(bytes);
        hot_nodes_=std::move(hot);
        for(auto* engine:engines_)engine->hot_nodes=hot_nodes_.get();
    }
public:'''),
        ('        return Engine::prepare_unlocked_reads(engines_,main_.tree);',
         '        const bool enabled=Engine::prepare_unlocked_reads(engines_,main_.tree);\n'
         '        if(enabled)prepare_hot_nodes();\n        return enabled;'),
    ])
    exe = output / 'solver.exe'
    run([compiler, 'c++', *baseline['ordered_flags'], str(source / 'hrc_research_solver.cpp'), '-o', str(exe)],
        output / 'build.json', 180)
    expected = run([str(baseline_exe), '--self-test'], output / 'baseline-self-test.json', 30)
    assert run([str(exe), '--self-test'], output / 'self-test.json', 30) == expected
    checked = json.loads(run([str(exe), '--self-test-hot-buckets'], output / 'hot-test.json', 60))
    assert checked['serial_parity'] and checked['parallel_updates'] == 320000
    manifest = {'baseline_sha256': sha(baseline_exe), 'candidate_sha256': sha(exe),
                'target_nodes': [1, 2, 3], 'stripes_per_node': 8, 'self_test_exact': True, 'validation': checked,
                'changed_sources': {name: sha(source / name) for name in (
                    'hrc_research_solver.cpp', 'hrc_parallel.hpp', 'hrc_hot_bucket_locks.hpp', 'hrc_hot_bucket_test.hpp')}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest), flush=True)


if __name__ == '__main__':
    main()
