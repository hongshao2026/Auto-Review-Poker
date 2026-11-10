"""Portable data-only calculation archives with checked paths, hashes and shapes."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

from .hrc_benchmarks import CACHE
from .hrc_native import prepare
from .hrc_snapshot import dump_tree, load_tree

MAX_ARCHIVE = 1024 * 1024 * 1024
NATIVE_FILES = ('tree.bin', 'tree.json', 'checkpoint.bin', 'index.json', 'manifest.json', 'tree-snapshot.json')
ABSTRACTION_FILES = ('manifest.json',) + tuple(f'street{s}.{suffix}' for s in (1, 2, 3) for suffix in ('boards.u64', 'buckets.u16'))
RESOURCE_FILES = ABSTRACTION_FILES + ('fgs-chance-v1.bin',)
ALLOWED = {'result.json', 'archive.json'} | {f'native/{p}' for p in NATIVE_FILES} | {f'resources/{p}' for p in RESOURCE_FILES}
ALLOWED |= {'native/source.hrcz', 'native/import-history.json'}


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def export_archive(job, include_resources=False):
    if job.result is None or getattr(job.solver, 'output', None) is None or job.status in ('running', 'cancelling'):
        raise ValueError('完整存档需要已完成或停止的原生检查点。')
    folder = job.solver.output
    if not (folder / 'tree-snapshot.json').is_file():
        dump_tree(job.solver.tree, folder / 'tree-snapshot.json')
    if not (folder / 'tree.json').is_file():
        from .hrc_training import solver_compact
        compact = solver_compact(job.solver)
        (folder / 'tree.json').write_text(json.dumps(compact, sort_keys=True, separators=(',', ':')), encoding='utf-8')
    files = {f'native/{name}': folder / name for name in NATIVE_FILES}
    if getattr(job.solver, 'source', None) is not None:
        files['native/source.hrcz'] = job.solver.source.path
    if (folder / 'import-history.json').is_file():
        files['native/import-history.json'] = folder / 'import-history.json'
    has_post = any(n.actor is not None and n.street > 0 for n in job.solver.tree.nodes)
    resources = Path(getattr(job.solver, 'resource_dir', CACHE / 'abstractions'))
    if include_resources and has_post:
        from .hrc_abstraction import verify_cached_resources
        verify_cached_resources(resources)
        files.update({f'resources/{name}': resources / name for name in ABSTRACTION_FILES})
    has_fgs = bool(job.config.get('fgs', {}).get('enabled'))
    if include_resources and has_fgs:
        from .hrc_fgs_config import prepare_chances
        prepare_chances(Path(r'D:\Program Files\HRC\plugins'), resources)
        files['resources/fgs-chance-v1.bin'] = resources / 'fgs-chance-v1.bin'
    result = deepcopy(job.result)
    result['native_artifacts'] = {'checkpoint_path': 'native/checkpoint.bin', 'index_path': 'native/index.json', 'manifest_path': 'native/manifest.json'}
    result_bytes = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    checks = {name: {'bytes': path.stat().st_size, 'sha256': _sha(path)} for name, path in files.items()}
    checks['result.json'] = {'bytes': len(result_bytes), 'sha256': hashlib.sha256(result_bytes).hexdigest()}
    metadata = {'schema': 'preflop-calculation-v1', 'source_job_id': job.id,
                'includes_abstractions': bool(include_resources and has_post), 'requires_abstractions': has_post,
                'includes_fgs_chance': bool(include_resources and has_fgs), 'requires_fgs_chance': has_fgs,
                'files': checks, 'note': 'Stores complete tree, monetary model and native training state. Resource bytes, when included, are local research inputs.'}
    target = folder / ('calculation-with-resources.plabz' if include_resources else 'calculation.plabz')
    pending = target.with_suffix('.pending')
    with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        archive.writestr('archive.json', json.dumps(metadata))
        archive.writestr('result.json', result_bytes)
        for name, path in files.items():
            archive.write(path, name)
    pending.replace(target)
    return target


def _validate_checkpoint(folder, compact):
    index = json.loads((folder / 'index.json').read_text(encoding='utf-8'))
    serial = json.dumps(compact, sort_keys=True, separators=(',', ':')).encode()
    identity = int.from_bytes(hashlib.sha256(serial).digest()[:8], 'little')
    policies = {row['node_id']: row for row in compact.get('policies', {}).get('nodes', [])}
    with (folder / 'checkpoint.bin').open('rb') as stream:
        version = stream.read(8)
        if version not in (b'HRSOLV01', b'HRSOLV02', b'HRSOLV03'):
            raise ValueError('未知原生检查点格式。')
        got_identity, samples, nn, players, mode = struct.unpack('<QQIII', stream.read(28))
        if got_identity != identity or nn != len(compact['nodes']) or players != compact['players'] or mode not in (0, 1):
            raise ValueError('检查点与保存的行动树或收益模型不匹配。')
        if samples != index['samples'] or len(index['nodes']) != nn:
            raise ValueError('检查点索引和采样计数不一致。')
        primary_rng=struct.unpack('<4Q', stream.read(32))
        if not any(primary_rng):
            raise ValueError('检查点随机数状态无效。')
        values = struct.unpack(f'<{players}d', stream.read(8 * players))
        if not all(math.isfinite(x) for x in values):
            raise ValueError('检查点包含非有限收益。')
        for row, node in zip(index['nodes'], compact['nodes']):
            k, buckets = len(node['children']), node['buckets']
            policy = policies.get(node['id'], {})
            frequency = 'frequency' in policy
            underlying = compact.get('stores', {}).get('street_formats', [23, 25, 25, 25])[node['street']]
            expected_format = (63 if frequency else underlying) if k else 0
            count = (1 + k + (2 * k + 1) * buckets if expected_format in (31, 63) else
                     1 + (2 * k + 1) * buckets if expected_format == 23 else
                     1 + k + 2 * k * buckets if expected_format == 27 else 1 + (buckets + 1) * k) if k else 0
            updates = struct.unpack('<Q', stream.read(8))[0]
            if version != b'HRSOLV01' and struct.unpack('<I', stream.read(4))[0] != expected_format:
                raise ValueError('检查点存储格式与策略约束不符。')
            if version == b'HRSOLV01' and policy:
                raise ValueError('旧检查点不包含策略约束存储。')
            if (row['id'] != node['id'] or row['actor'] != node['actor'] or row['street'] != node['street']
                or row['buckets'] != buckets or row['actions'] != k or row['updates'] != updates
                or row['format'] != expected_format):
                raise ValueError('检查点节点索引不一致。')
            if row['visits_offset'] != stream.tell() or row['raw_count'] != count:
                raise ValueError('检查点偏移或长度无效。')
            visits = struct.unpack(f'<{buckets}Q', stream.read(8 * buckets))
            baseline = updates - sum(visits)
            provenance = compact.get('import_provenance', {})
            counters = provenance.get('saved_update_counters', [])
            saved = counters[node['id']] if len(counters) == nn else None
            imported_clock = (max(0, math.floor(saved + .5)) if isinstance(saved, (float, int)) and math.isfinite(saved) else 0)
            proven = (provenance.get('format') == 'hrcz' and isinstance(provenance.get('source_sha256'), str)
                      and len(provenance['source_sha256']) == 64 and len(counters) == nn)
            if baseline != 0 and not (proven and baseline == imported_clock):
                raise ValueError('节点访问计数不一致。')
            if row['raw_offset'] != stream.tell():
                raise ValueError('检查点数据偏移无效。')
            raw = stream.read(8 * count)
            if len(raw) != 8 * count or not all(math.isfinite(x[0]) for x in struct.iter_unpack('<d', raw)):
                raise ValueError('检查点策略数据不完整或非有限。')
            if frequency:
                if row.get('frequency_state_offset') != stream.tell():
                    raise ValueError('行动频率状态或目标不匹配。')
                state = stream.read(8 * (2 + 3 * k))
                if len(state) != 8 * (2 + 3 * k) or not all(math.isfinite(x[0]) for x in struct.iter_unpack('<d', state)):
                    raise ValueError('行动频率状态不完整或非有限。')
                if version == b'HRSOLV03':
                    targets = struct.unpack(f'<{k}d', stream.read(8 * k))
                    targets = [None if math.isnan(t) else t for t in targets]
                    if row.get('targets') != targets:
                        raise ValueError('频率目标索引与检查点运行状态不一致。')
                    for value, configured in zip(targets, policy['frequency']['targets']):
                        allowed = [None] if configured is None else [configured, struct.unpack('<f', struct.pack('<f', configured))[0]]
                        if value not in allowed:
                            raise ValueError('频率目标与场景配置不一致。')
                elif row.get('targets') != policy['frequency']['targets']:
                    raise ValueError('行动频率目标与场景配置不一致。')
            if expected_format == 31:
                if row.get('shared_state_offset') != stream.tell():
                    raise ValueError('共享累计状态偏移无效。')
                shared = stream.read(8 * k)
                if len(shared) != 8 * k or not all(math.isfinite(x[0]) for x in struct.iter_unpack('<d', shared)):
                    raise ValueError('共享累计状态不完整或非有限。')
            if row.get('locks') != policy.get('locks'):
                raise ValueError('节点锁定索引与训练配置不一致。')
        from .hrc_parallel import validate_trailer
        validate_trailer(stream.read(),primary_rng,expected_threads=index.get('training_threads',1))
    return samples


def import_archive(source, run_root):
    if Path(source).stat().st_size > MAX_ARCHIVE:
        raise ValueError('存档超过 1 GiB 上限。')
    CACHE.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='import-', dir=CACHE) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(source) as archive:
            info = archive.infolist()
            names = [item.filename for item in info]
            if len(names) != len(set(names)) or not set(names) <= ALLOWED or sum(i.file_size for i in info) > MAX_ARCHIVE:
                raise ValueError('存档文件路径、重复项或展开大小无效。')
            if 'archive.json' not in names or archive.getinfo('archive.json').file_size > 65536:
                raise ValueError('缺少存档清单。')
            meta = json.loads(archive.read('archive.json'))
            if meta.get('schema') != 'preflop-calculation-v1' or set(meta['files']) != set(names) - {'archive.json'}:
                raise ValueError('未知存档版本或清单不匹配。')
            required = {'result.json'} | {f'native/{name}' for name in NATIVE_FILES}
            if not required <= set(names):
                raise ValueError('存档缺少完整行动树或检查点。')
            for item in info:
                if item.filename == 'archive.json':
                    continue
                expected = meta['files'][item.filename]
                if item.file_size != expected['bytes']:
                    raise ValueError('存档文件长度不匹配。')
                target = staging / item.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                if _sha(target) != expected['sha256']:
                    raise ValueError('存档文件 SHA-256 校验失败。')
        folder = staging / 'native'
        tree = load_tree(folder / 'tree-snapshot.json')
        compact = json.loads((folder / 'tree.json').read_text(encoding='utf-8'))
        topology = tree.compact_export()
        snapshot_topology = deepcopy(compact)
        if compact.get('rake'):
            for expected_terminal, terminal in zip(topology['terminals'], snapshot_topology['terminals']):
                for field in ('street', 'raise_count'):
                    if field not in expected_terminal:
                        terminal.pop(field, None)
        if any(topology[key] != snapshot_topology[key] for key in ('root', 'players', 'big_blind', 'initial_stacks', 'nodes', 'terminals')):
            raise ValueError('浏览树与训练树不匹配。')
        prepared = prepare(compact, staging / 'check')
        if _sha(prepared['tree_binary']) != _sha(folder / 'tree.bin'):
            raise ValueError('原生输入与保存的行动树不匹配。')
        samples = _validate_checkpoint(folder, compact)
        result = json.loads((staging / 'result.json').read_text(encoding='utf-8'))
        if result['summary']['iterations_completed'] != samples:
            raise ValueError('结果与检查点采样次数不匹配。')
        if result['config'].get('engine') == 'hrc_imported':
            from .hrc_hrcz import cache_source
            if not (folder / 'source.hrcz').is_file() or cache_source(folder / 'source.hrcz') != result['config'].get('source_sha256'):
                raise ValueError('HRC 导入检查点缺少可验证的源存档。')
        from .hrc_restore import restore_solver
        solver = restore_solver(result['config'], tree)
        if compact.get('equity') != getattr(solver, 'equity_config', None):
            raise ValueError('场景配置与收益模型不匹配。')
        from .hrc_training import solver_compact
        expected = solver_compact(solver)
        # CI tracking is a run option. Its historical input flag may be retained
        # to preserve checkpoint identity when tracking was enabled on resume.
        if any(expected.get(key) != compact.get(key) for key in ('policies', 'fgs', 'stores', 'rake', 'terminals', 'import_provenance')):
            raise ValueError('场景配置与保存的策略约束或未来手模型不匹配。')
        resources = staging / 'resources'
        if (resources / 'manifest.json').exists():
            from .hrc_abstraction import verify_cached_resources
            verify_cached_resources(resources)
        if (resources / 'fgs-chance-v1.bin').exists():
            from .hrc_fgs_config import prepare_chances
            prepare_chances(Path('unused-original-installation'), resources)
        identity = uuid.uuid4().hex
        destination = CACHE / 'runs' / identity
        destination.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(destination)
        if resources.exists():
            resources.rename(destination / 'resources')
        result['imported_from_job_id'] = result.get('job_id')
        result['source_created_at'] = result.get('created_at')
        result['created_at'] = datetime.now(timezone.utc).isoformat()
        result['job_id'] = identity
        result['imported_archive'] = True
        result['native_artifacts'] = {f'{key}_path': str(destination / f'{key}.{ext}') for key, ext in [('checkpoint', 'bin'), ('index', 'json'), ('manifest', 'json')]}
        result['native_artifacts']['resources_path'] = str(destination / 'resources' if (destination / 'resources').exists() else CACHE / 'abstractions')
        solver.tree, solver.output, solver.index, solver.reference = tree, destination, json.loads((destination / 'index.json').read_text()), None
        result['nodes'] = {'root': solver.result_node([])['strategy']}
        result['summary'].pop('comparison', None)
        Path(run_root).mkdir(parents=True, exist_ok=True)
        (Path(run_root) / f'{identity}.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        return identity
