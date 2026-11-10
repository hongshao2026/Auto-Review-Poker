"""Build isolated node-lock variants from the pinned current solver sources."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ACCEPTED = ROOT / '.research-cache/bubble-round2-20261109/accepted'
HEADER = 'hrc_node_mutex.hpp'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def replace_once(text, old, new):
    if text.count(old)!=1:
        raise ValueError('Unexpected baseline mutex source')
    return text.replace(old,new,1)


def adaptive(text):
    text=replace_once(text,'''    static void backoff(unsigned& spins) noexcept {
        pause_cpu();
        if (++spins == 64) {
            spins = 0;
            std::this_thread::yield();
        }
    }''','''    // Start responsive, then space polls while the holder is still running.
    // Retain a bounded scheduler escape for preempted holders.
    static void backoff(unsigned& delay, unsigned& polls) noexcept {
        for (unsigned i = 0; i < delay; ++i) pause_cpu();
        if (delay < 16) delay *= 2;
        else if (++polls == 32) {
            std::this_thread::yield();
            delay = 4;
            polls = 0;
        }
    }''')
    return replace_once(text, '        unsigned spins = 0;\n        for (;;) {\n            while (state_.load(std::memory_order_relaxed) != 0) backoff(spins);\n            if (state_.exchange(1, std::memory_order_acquire) == 0) return;\n            backoff(spins);',
                        '        unsigned delay = 1, polls = 0;\n        for (;;) {\n            while (state_.load(std::memory_order_relaxed) != 0) backoff(delay, polls);\n            if (state_.exchange(1, std::memory_order_acquire) == 0) return;\n            backoff(delay, polls);')


PARK = r'''
    // 0: free, 1: held, 2: held and possibly parked waiters. Never overwrite
    // state 2 on the fast path: that would lose the release-side wakeup.
    std::atomic<std::uint32_t> state_{0};
    static_assert(sizeof(state_) == sizeof(std::uint32_t));
    struct WaitOps {
        BOOL (WINAPI* wait)(volatile void*, void*, SIZE_T, DWORD);
        VOID (WINAPI* wake)(void*);
    };
    static const WaitOps& wait_ops() noexcept {
        static const WaitOps ops = [] {
            const auto module = GetModuleHandleW(L"KernelBase.dll");
            return WaitOps{
                reinterpret_cast<decltype(WaitOps::wait)>(GetProcAddress(module, "WaitOnAddress")),
                reinterpret_cast<decltype(WaitOps::wake)>(GetProcAddress(module, "WakeByAddressSingle"))};
        }();
        return ops;
    }
public:
    NodeMutex() noexcept = default;
    NodeMutex(const NodeMutex&) = delete;
    NodeMutex& operator=(const NodeMutex&) = delete;
    bool try_lock() noexcept {
        std::uint32_t expected = 0;
        return state_.compare_exchange_strong(expected, 1, std::memory_order_acquire,
                                              std::memory_order_relaxed);
    }
    void lock() noexcept {
        if (try_lock()) return;
        for (unsigned i = 0; i < 128; ++i) {
            pause_cpu();
            if (state_.load(std::memory_order_relaxed) == 0 && try_lock()) return;
        }
        const auto& ops = wait_ops();
        while (state_.exchange(2, std::memory_order_acquire) != 0) {
            std::uint32_t held = 2;
            // The compare closes the gap between marking contention and
            // sleeping. The loop tolerates spurious wakes and barging.
            if (!ops.wait || !ops.wake || !ops.wait(&state_, &held, sizeof(held), INFINITE))
                std::this_thread::yield();
        }
    }
    void unlock() noexcept {
        if (state_.exchange(0, std::memory_order_release) == 2) {
            const auto& ops = wait_ops();
            if (ops.wait && ops.wake) ops.wake(&state_);
        }
    }
'''

SRW = r'''
    SRWLOCK state_ = SRWLOCK_INIT;
public:
    NodeMutex() noexcept = default;
    NodeMutex(const NodeMutex&) = delete;
    NodeMutex& operator=(const NodeMutex&) = delete;
    bool try_lock() noexcept { return TryAcquireSRWLockExclusive(&state_) != 0; }
    void lock() noexcept { AcquireSRWLockExclusive(&state_); }
    void unlock() noexcept { ReleaseSRWLockExclusive(&state_); }
'''


WRITER = r'''
    // Ordinary shared writers only: each action keeps the same multiply/add
    // association and each store the same order within the node lock.
    template<int K>
    void update_atomic_width(Random& rng,int h,const double* p,const double* q,double w,double z,bool preflop){
        if(w<=0)return;
        const int width=K ? K : k;
        double value=0;
        for(int a=0;a<width;++a)if(p[a]>0)value+=p[a]*q[a];
        ++updates;
        ++visits[h];
        double* const data=raw.data();
        double t=hrc_unlocked_read::load(data)+1;
        if(preflop){
            if(rng.integer()%refresh_divisor(t)==0){t=double(updates);hrc_unlocked_read::store(data,t);}
        }else hrc_unlocked_read::store(data,t);
        double* const row=data+(preflop ? 1+size_t(2*width+1)*h : 1+size_t(h+1)*width);
        const double weight=t*w;
        for(int a=0;a<width;++a){
            const double previous=hrc_unlocked_read::load(row+a);
            hrc_unlocked_read::store(row+a,previous+weight*(q[a]-value));
        }
        if(preflop){
            for(int a=0;a<width;++a)row[width+1+a]+=t*p[a];
            row[width]+=weight;
        }else if(z>0){
            for(int a=0;a<width;++a)data[1+a]+=t*z*p[a];
        }
    }
    void update_atomic(Random& rng,int h,const double* p,const double* q,double w,double z){
        const int f=base_format();
        if(f!=23&&f!=25){update_atomic_general(rng,h,p,q,w,z);return;}
        if(k==2)update_atomic_width<2>(rng,h,p,q,w,z,f==23);
        else if(k==3)update_atomic_width<3>(rng,h,p,q,w,z,f==23);
        else update_atomic_width<0>(rng,h,p,q,w,z,f==23);
    }
'''


def short_writer(text):
    anchor='    void update_atomic(Random& rng,int h,const double* p,const double* q,double w,double z){'
    return replace_once(text,anchor,WRITER+anchor.replace('update_atomic(', 'update_atomic_general('))


def prefetch_writer(text):
    anchor='        if(node_mutexes){std::lock_guard<hrc_node_mutex::NodeMutex> guard(node_mutexes[id]);n.update(rng,h,p,q,1,marker);}'
    return replace_once(text,anchor,'''        if(node_mutexes){
#if defined(__clang__) || defined(__GNUC__)
            if(n.unlocked_read){
                __builtin_prefetch(n.raw.data()+n.regret(h),0,3);
                __builtin_prefetch(n.visits.data()+h,0,3);
            }
#endif
            std::lock_guard<hrc_node_mutex::NodeMutex> guard(node_mutexes[id]);
            n.update(rng,h,p,q,1,marker);
        }''')


def windows_lock(text, body, *, pause=False):
    anchor='class alignas(64) NodeMutex {'
    begin=text.index(anchor)+len(anchor)
    end=text.index('\n};', begin)
    old=text[begin:end]
    if pause:
        body=old[old.index('    static void pause_cpu()'):old.index('    static void backoff')]+body
    return (text[:begin]+'\n#if defined(_WIN32)\n'+body+'#else'+old+'\n#endif'+text[end:]).replace(
        '#include <thread>', '#include <thread>\n#if defined(_WIN32)\n#include <windows.h>\n#endif', 1)


def run(command, path, timeout):
    result=subprocess.run(command, capture_output=True, timeout=timeout)
    path.write_text(json.dumps({'command':command,'returncode':result.returncode,
                               'stdout':result.stdout.decode('utf-8','replace'),
                               'stderr':result.stderr.decode('utf-8','replace')},indent=2),encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{path}: {result.stderr.decode("utf-8","replace")}')
    return result.stdout


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--variant',choices=('adaptive','park','srw','short-writer','prefetch'),action='append')
    args=parser.parse_args()
    out=args.output.resolve()
    assert out.is_relative_to(ROOT.resolve())
    out.mkdir(parents=True,exist_ok=False)
    baseline=json.loads((ACCEPTED/'manifest.json').read_text(encoding='utf-8'))
    assert sha(ACCEPTED/'solver.exe')==baseline['executable_sha256']
    spec=baseline['identity_spec']
    snap=Path(spec['translation_unit']).parent
    for name,d in spec['source_files'].items():
        assert sha(snap/name)==d['sha256']
    compiler=baseline['command'][0]
    assert sha(Path(compiler))==spec['compiler']['sha256']
    base=(snap/HEADER).read_text(encoding='utf-8')
    expected=subprocess.check_output([str(ACCEPTED/'solver.exe'),'--self-test'],timeout=30)
    stress=(ROOT/'scripts/native/node_mutex_stress.cpp').read_text(encoding='utf-8')
    stress=replace_once(stress,'"../../native/hrc_node_mutex.hpp"','"hrc_node_mutex.hpp"')
    headers={'adaptive':adaptive(base),'park':windows_lock(base,PARK,pause=True),'srw':windows_lock(base,SRW)}
    writers={'short-writer':short_writer,'prefetch':prefetch_writer}
    for name in args.variant or headers:
        folder=out/name
        src=folder/'source'
        shutil.copytree(snap,src)
        if name in headers:
            (src/HEADER).write_text(headers[name],encoding='utf-8')
        else:
            main_source=src/'hrc_research_solver.cpp'
            main_source.write_text(writers[name](main_source.read_text(encoding='utf-8')),encoding='utf-8')
        exe=folder/'solver.exe'
        cmd=[compiler,'c++',*baseline['ordered_flags'],str(src/'hrc_research_solver.cpp'),'-o',str(exe)]
        print(f'Building {name}',flush=True)
        run(cmd,folder/'build.json',180)
        actual=run([str(exe),'--self-test'],folder/'self-test.json',30)
        assert actual==expected, f'{name} changed the native numerical probes'
        probe=folder/'mutex_stress.cpp'
        probe.write_text(stress,encoding='utf-8')
        probe_exe=folder/'mutex_stress.exe'
        run([compiler,'c++','-O3','-std=c++17','-I',str(src),str(probe),'-o',str(probe_exe)],folder/'stress-build.json',60)
        checked=json.loads(run([str(probe_exe)],folder/'stress-run.json',45))
        assert checked['updates']==64000 and checked['slow_holder_waiters']==32 and checked['lock_bytes']==64
        (folder/'manifest.json').write_text(json.dumps({'variant':name,'executable_sha256':sha(exe),
            'baseline_executable_sha256':baseline['executable_sha256'],'header_sha256':sha(src/HEADER),
            'translation_unit_sha256':sha(src/'hrc_research_solver.cpp'),
            'source_snapshot':str(snap),'self_test_exact':True,'mutex_stress':checked},indent=2),encoding='utf-8')
        print(f'Validated {name}: {sha(exe)}',flush=True)


if __name__=='__main__':
    main()
