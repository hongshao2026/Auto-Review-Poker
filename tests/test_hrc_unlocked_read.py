"""Production policy-read atomics, exact serial state, and compiler fallback.

All native sources/headers participate in the isolated compile-cache digest.
Real-profile coverage is optional on machines without the local research data;
unit, concurrency and cross-build checkpoint checks require no such resources.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/native/unlocked_read_probe.cpp'


def _compiler():
    candidates = [Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe'),
                  Path('D:/Tools/REA-Research/zig-x86_64-windows-0.15.2/zig.exe')]
    manifest = ROOT / 'analysis/hrc-native/build/build.json'
    if manifest.is_file():
        configured = json.loads(manifest.read_text()).get('compiler')
        if configured:
            candidates.insert(0, Path(configured))
    for path in candidates:
        if path.is_file() and path.stem.lower() == 'zig':
            return [str(path), 'c++']
    for name in ('clang++', 'g++'):
        if path := shutil.which(name):
            return [path]
    pytest.skip('Existing C++17 compiler unavailable')


def _cache(command, flags):
    digest = hashlib.sha256(json.dumps([command, flags]).encode())
    inputs = [SOURCE] + sorted(p for p in (ROOT / 'native').rglob('*')
                               if p.suffix in ('.cpp', '.hpp', '.h') and p.is_file())
    for path in inputs:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
    compiler = Path(command[0])
    if compiler.is_file():
        stat = compiler.stat()
        digest.update(f'{stat.st_size}:{stat.st_mtime_ns}'.encode())
    directory = ROOT / '.research-cache/unlocked-read-tests' / digest.hexdigest()[:24]
    directory.mkdir(parents=True, exist_ok=True)
    return directory, inputs


def build_probe(disabled=False):
    command = _compiler()
    flags = ['-O3', '-std=c++17', '-ffp-contract=off', '-pthread']
    if disabled:
        flags.append('-DHRC_DISABLE_UNLOCKED_READS=1')
    directory, inputs = _cache(command, flags)
    executable = directory / ('probe.exe' if os.name == 'nt' else 'probe')
    if not executable.exists():
        result = subprocess.run(command + flags + [str(SOURCE), '-o', str(executable)],
                                capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + '\n' + result.stderr
        (directory / 'build.json').write_text(json.dumps({
            'command': command + flags, 'source': str(SOURCE),
            'inputs': [str(p.relative_to(ROOT)) for p in inputs],
            'disabled': disabled,
            'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        }, indent=2) + '\n')
    return executable


@pytest.fixture(scope='module')
def probe():
    return build_probe()


@pytest.fixture(scope='module')
def disabled_probe():
    return build_probe(disabled=True)


def invoke(executable, mode, *arguments):
    result = subprocess.run([str(executable), mode, *map(str, arguments)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    return json.loads(result.stdout)


def test_readonly_metadata_and_writer_cache_line_are_separate(probe):
    row = invoke(probe, 'layout')
    assert row == dict(node_bytes=256, node_alignment=64, updates_offset=192,
                       vector_stride_verified=True)


def test_atomic_normalization_signed_zero_nan_infinity_and_random_bits(probe):
    row = invoke(probe, 'edges')
    assert row['normalization_edge_vectors'] == 128820 and row['bitwise_equal']


def test_exact_update_snapshots_and_sampling_rng_tapes(probe):
    row = invoke(probe, 'unit')
    assert row['node_update_snapshots'] == 14400
    assert row['sample_rng_tapes'] == 262144 and row['exploration_draws'] > 0


def test_all_workers_budget_atomic_publication_and_format_policy_fallback(probe):
    row = invoke(probe, 'budget')
    assert row['budget'] and row['eligibility_and_fallback'] and row['rng_untouched']


def test_two_scratch_caches_parallel_counts_and_quiescent_reset(probe):
    row = invoke(probe, 'parallel')
    assert row['samples'] == 11000 and row['no_lost_updates'] and row['reset_quiescence']
    assert row['worker_terminal_caches_reclaimed'] and row['reclaimed_terminal_bytes'] > 0


def test_forced_disabled_path_has_no_flags_cache_or_lost_updates(disabled_probe):
    row = invoke(disabled_probe, 'fallback')
    assert not row['supported'] and row['cache_bytes'] == row['flags'] == 0
    assert row['locked_samples'] == 2000 and row['misuse_rejected']


def test_forced_disabled_and_normal_serial_checkpoints_are_identical(probe, disabled_probe, tmp_path):
    normal, disabled = tmp_path / 'normal', tmp_path / 'disabled'
    a, b = invoke(probe, 'state', normal), invoke(disabled_probe, 'state', disabled)
    assert a['supported'] and a['cache_bytes'] > 0
    assert not b['supported'] and b['cache_bytes'] == 0
    assert a['resume_equal'] and b['resume_equal']
    for name in ('initial', 'continuous', 'resumed'):
        assert (normal / name / 'checkpoint.bin').read_bytes() == (disabled / name / 'checkpoint.bin').read_bytes()


def test_real_three_player_static_tree_and_resources_keep_checkpoint_and_resume(probe, tmp_path):
    tree = ROOT / '.research-cache/three40bb-ci10-independent-20261107/input/tree.bin'
    resources = ROOT / '.research-cache/abstractions'
    needed = [resources / f'street{s}.{suffix}' for s in (1, 2, 3)
              for suffix in ('boards.u64', 'buckets.u16')]
    if not tree.is_file() or not all(p.is_file() for p in needed):
        pytest.skip('Local independent 3p tree/static abstraction resources unavailable')
    row = invoke(probe, 'tree', tree, resources, tmp_path)
    assert row['real_tree_steps'] == 1100 and row['full_checkpoint_equal'] and row['resume_equal']


def _msvc_installation():
    if os.name != 'nt':
        pytest.skip('MSVC smoke requires Windows')
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.is_file():
        pytest.skip('Existing Visual Studio discovery tool unavailable')
    result = subprocess.run([str(vswhere), '-latest', '-products', '*', '-requires',
                             'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                             '-property', 'installationPath'], capture_output=True, text=True, timeout=15)
    if result.returncode or not result.stdout.strip():
        pytest.skip('No installed MSVC C++ toolset')
    installation = Path(result.stdout.strip())
    candidates = sorted((installation / 'VC/Tools/MSVC').glob('*/bin/Hostx64/x64/cl.exe'))
    if not candidates:
        pytest.skip('Installed native x64 MSVC compiler unavailable')
    # A compiler-only installation cannot build even <cstdlib>. Check the
    # existing SDK/UCRT rather than installing it or hiding source build errors.
    sdk_roots = [Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Windows Kits/10']
    for variable in ('WindowsSdkDir', 'UniversalCRTSdkDir'):
        if os.environ.get(variable):
            sdk_roots.append(Path(os.environ[variable]))
    import winreg
    for access in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r'SOFTWARE\Microsoft\Windows Kits\Installed Roots',
                                0, winreg.KEY_READ | access) as key:
                sdk_roots.append(Path(winreg.QueryValueEx(key, 'KitsRoot10')[0]))
        except OSError:
            pass
    sdk_ready = any((sdk / 'Include').is_dir()
                    and any((sdk / 'Include').glob('*/ucrt/math.h'))
                    and any((sdk / 'Lib').glob('*/ucrt/x64/ucrt.lib'))
                    and any((sdk / 'Lib').glob('*/um/x64/kernel32.lib'))
                    for sdk in sdk_roots)
    if not sdk_ready:
        pytest.skip('MSVC toolset exists but Windows SDK/UCRT headers and libraries are unavailable (math.h); no installation performed')
    return installation, candidates[-1]


@pytest.fixture(scope='module')
def msvc_probe():
    installation, compiler = _msvc_installation()
    flags = ['/nologo', '/O2', '/std:c++17', '/fp:strict', '/EHsc']
    directory, inputs = _cache([str(compiler)], flags)
    executable = directory / 'probe.exe'
    if not executable.exists():
        script = directory / 'build.cmd'
        setup = installation / 'Common7/Tools/VsDevCmd.bat'
        script.write_text('@echo off\n'
                          f'call "{setup}" -arch=x64 -host_arch=x64 >nul\n'
                          'if errorlevel 1 exit /b 1\n'
                          f'"{compiler}" {" ".join(flags)} "{SOURCE}" '
                          f'/Fe:"{executable}" /Fo:"{directory / "probe.obj"}" '
                          f'/Fd:"{directory / "probe.pdb"}"\n')
        result = subprocess.run(['cmd.exe', '/d', '/c', str(script)], cwd=directory,
                                capture_output=True, text=True, errors='replace', timeout=180)
        assert result.returncode == 0, result.stdout + '\n' + result.stderr
        (directory / 'build.json').write_text(json.dumps({
            'compiler': str(compiler), 'flags': flags,
            'inputs': [str(p.relative_to(ROOT)) for p in inputs],
            'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'stdout': result.stdout, 'stderr': result.stderr,
        }, indent=2) + '\n')
    return executable


def test_existing_native_msvc_uses_locked_fallback_and_resumes(msvc_probe, tmp_path):
    row = invoke(msvc_probe, 'fallback')
    assert not row['supported'] and row['cache_bytes'] == 0
    state = invoke(msvc_probe, 'state', tmp_path)
    assert not state['supported'] and state['cache_bytes'] == 0 and state['resume_equal']
