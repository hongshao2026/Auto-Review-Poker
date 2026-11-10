"""Build the exact-owner lock probe from the frozen MTT baseline."""
import argparse
import json
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = runpy.run_path(str(ROOT / 'scripts/build-hrc-mtt-writer-candidates.py'))
ACCEPTED = BUILD['ACCEPTED']
sha, run, replace_once = (BUILD[name] for name in ('sha', 'run', 'replace_once'))

TAGGED = '''
    // Diagnostic lock only. A failed CAS returns the exact tag of the holder
    // at the first acquisition attempt, with no second owner lookup or ABA gap.
    uint32_t try_tagged(uint32_t tag) noexcept {
        uint32_t holder = 0;
        state_.compare_exchange_strong(holder, tag, std::memory_order_acquire,
                                       std::memory_order_relaxed);
        return holder;
    }
    void wait_tagged(uint32_t tag) noexcept {
        unsigned spins = 0;
        for (;;) {
            while (state_.load(std::memory_order_relaxed) != 0) backoff(spins);
            if (try_tagged(tag) == 0) return;
            backoff(spins);
        }
    }
'''


def edit(path, replacements):
    content = path.read_text(encoding='utf-8')
    for old, new in replacements:
        content = replace_once(content, old, new)
    path.write_text(content, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    if not output.is_relative_to(ROOT.resolve()):
        raise ValueError('Probe artifacts must stay inside the workspace')
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
    shutil.copy2(ROOT / 'scripts/native/hrc_node_contention_probe.hpp', source)
    edit(source / 'hrc_node_mutex.hpp', [
        ('    bool try_lock() noexcept {', TAGGED + '    bool try_lock() noexcept {'),
    ])
    edit(source / 'hrc_research_solver.cpp', [
        ('#include "hrc_node_mutex.hpp"', '#include "hrc_node_mutex.hpp"\n#include "hrc_node_contention_probe.hpp"'),
        ('    hrc_node_mutex::NodeMutex* node_mutexes=nullptr;',
         '    hrc_node_mutex::NodeMutex* node_mutexes=nullptr;\n    hrc_lock_probe::Worker lock_probe;'),
        ('std::lock_guard<hrc_node_mutex::NodeMutex> guard(node_mutexes[id]);n.strategy(h,p);',
         'hrc_lock_probe::Guard guard(node_mutexes[id],lock_probe,id,h,hrc_lock_probe::Access::read);n.strategy(h,p);'),
        ('std::lock_guard<hrc_node_mutex::NodeMutex> guard(node_mutexes[id]);n.update(rng,h,p,q,1,marker);',
         'const auto access=n.street>0&&marker>0?hrc_lock_probe::Access::write_with_average:hrc_lock_probe::Access::write;'
         'hrc_lock_probe::Guard guard(node_mutexes[id],lock_probe,id,h,access);n.update(rng,h,p,q,1,marker);'),
        ('    std::cout<<"{\\"kind\\":\\"finished\\",\\"iteration\\":"<<e.samples',
         '    if(parallel)parallel->write_lock_probe(output/"lock-probe.bin");\n'
         '    std::cout<<"{\\"kind\\":\\"finished\\",\\"iteration\\":"<<e.samples'),
    ])
    edit(source / 'hrc_parallel.hpp', [
        ('        try {for(int i=1;i<count;++i)threads_.emplace_back',
         '        main.tree.reserve_budget(uint64_t(count)*hrc_lock_probe::Worker::capacity*sizeof(hrc_lock_probe::Event));\n'
         '        for(int i=0;i<count;++i)engines_[i]->lock_probe.init(uint32_t(i));\n'
         '        try {for(int i=1;i<count;++i)threads_.emplace_back'),
        ('    ~ParallelTrainer(){stop();}',
         '''    ~ParallelTrainer(){stop();}
    void write_lock_probe(const fs::path& path) {
        std::lock_guard<std::mutex> lock(control_);
        if(pending_)throw std::logic_error("Lock probe export requires quiescent workers");
        std::ofstream out(path,std::ios::binary|std::ios::trunc);
        out.exceptions(std::ios::failbit|std::ios::badbit);
        const uint32_t header[]={0x314b4c48u,uint32_t(engines_.size()),hrc_lock_probe::Worker::interval};
        out.write(reinterpret_cast<const char*>(header),sizeof(header));
        for(auto* engine:engines_)engine->lock_probe.write(out);
        out.close();
    }'''),
    ])
    exe = output / 'solver.exe'
    run([compiler, 'c++', *baseline['ordered_flags'], str(source / 'hrc_research_solver.cpp'), '-o', str(exe)],
        output / 'build.json', 180)
    actual = run([str(exe), '--self-test'], output / 'self-test.json', 30)
    assert actual == subprocess.check_output([str(baseline_exe), '--self-test'], timeout=30)
    manifest = {'executable_sha256': sha(exe), 'baseline_executable_sha256': sha(baseline_exe),
                'self_test_exact': True, 'sources': {name: sha(source / name) for name in (
                    'hrc_node_mutex.hpp', 'hrc_node_contention_probe.hpp', 'hrc_research_solver.cpp', 'hrc_parallel.hpp')}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest), flush=True)


if __name__ == '__main__':
    main()
