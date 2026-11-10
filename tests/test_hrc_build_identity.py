"""Exercise cache invalidation with a real, small compiled dependency."""
import json
import subprocess

import pytest

from preflop_lab import hrc_native as native


def test_build_cache_tracks_headers_flags_and_rejects_modified_executable(tmp_path, monkeypatch):
    compiler = native._native_toolchain()
    if compiler['kind'] != 'zig':
        pytest.skip('This small fixture uses the production Zig flags')
    source = tmp_path / 'native'
    source.mkdir()
    # Keep the legacy compatibility tuple complete, while compiling only this
    # tiny translation unit and its actual include dependency.
    for path in native.SOURCE.parent.iterdir():
        if path.suffix in ('.cpp', '.hpp', '.h'):
            (source / path.name).write_text('')
    main = source / native.SOURCE.name
    main.write_text('#include "actual_dependency.hpp"\n'
                    '#ifndef CACHE_MARK\n#define CACHE_MARK 0\n#endif\n'
                    'int main() { return DEPENDENCY_VALUE + CACHE_MARK; }\n')
    dependency = source / 'actual_dependency.hpp'
    dependency.write_text('#define DEPENDENCY_VALUE 0\n')
    monkeypatch.setattr(native, 'SOURCE', main)
    monkeypatch.setattr(native, 'BUILD', tmp_path / 'build')
    monkeypatch.setattr(native, '_native_toolchain', lambda: compiler)

    first = native.build()
    record = json.loads((native.BUILD / 'build.json').read_text())
    manifest = first.with_name('build.json')
    original_mtime = manifest.stat().st_mtime_ns
    assert subprocess.run([str(first)]).returncode == 0
    assert native.build() == first
    assert manifest.stat().st_mtime_ns == original_mtime

    dependency.write_text('#define DEPENDENCY_VALUE 1\n')
    second = native.build()
    assert second != first and subprocess.run([str(second)]).returncode == 1
    assert json.loads(manifest.read_text()) == record
    assert record['identity_spec']['source_files']['actual_dependency.hpp']['bytes'] > 0

    monkeypatch.setattr(native, '_NATIVE_ZIG_FLAGS', (*native._NATIVE_ZIG_FLAGS, '-DCACHE_MARK=2'))
    third = native.build()
    assert third not in (first, second)
    assert subprocess.run([str(third)]).returncode == 3
    with third.open('ab') as stream:
        stream.write(b'tampered-cache')
    with pytest.raises(RuntimeError, match='invalid identity'):
        native.build()
