"""Run controls are separate from the immutable poker game and checkpoint data."""
from copy import deepcopy
import math
from pathlib import Path
import shutil
import struct

MAX_SAMPLES = 1_000_000_000
RUN_CONTROLS = ('solver_mode', 'threads', 'constant_scalar_shortcuts', 'track_ci',
                'stopping_mode', 'sampling_scope', 'sampling_path', 'sampling_stage',
                'target_ci', 'stop_after_seconds', 'hard_seconds', 'max_memory_bytes')


def iteration_limit(raw, default=100_000):
    """A CI/time run's sample count is a safety cap, not its completion target."""
    return raw.get('iterations', MAX_SAMPLES if raw.get('stopping_mode') in ('ci', 'time') else default)


def validated_sampling(raw):
    result = {}
    if 'stopping_mode' in raw:
        mode = raw['stopping_mode']
        if mode not in ('samples', 'ci', 'time'):
            raise ValueError('stopping_mode 必须为 samples、ci 或 time。')
        result['stopping_mode'] = mode
        if mode == 'ci':
            if raw.get('stop_after_seconds') is not None:
                raise ValueError('CI 模式不能同时设置目标计算时间；限制运行时间请用 hard_seconds。')
            target = raw.get('target_ci', 10.0)
            if type(target) not in (int, float) or not math.isfinite(target) or not 0 < target <= 1e12:
                raise ValueError('CI Target 必须是大于零的有限数值。')
            result.update(track_ci=True, target_ci=float(target))
        elif mode == 'time':
            if raw.get('target_ci') is not None or raw.get('stop_after_seconds') is None:
                raise ValueError('时间模式需要 stop_after_seconds，不能同时设置 CI 目标。')
        elif raw.get('target_ci') is not None or raw.get('stop_after_seconds') is not None:
            raise ValueError('固定次数模式不能同时设置 CI 或时间目标。')
    if 'sampling_stage' in raw:
        if raw['sampling_stage'] not in ('initialization', 'calculation'):
            raise ValueError('sampling_stage 必须为 initialization 或 calculation。')
        result['sampling_stage'] = raw['sampling_stage']
        if raw['sampling_stage'] == 'initialization' and raw.get('stopping_mode', 'samples') != 'samples':
            raise ValueError('手牌初始化必须使用固定次数模式。')
    if 'sampling_scope' in raw or 'sampling_path' in raw:
        scope, path = raw.get('sampling_scope', 'entire_tree'), raw.get('sampling_path', [])
        if scope not in ('entire_tree', 'selected_subtree'):
            raise ValueError('sampling_scope 必须为 entire_tree 或 selected_subtree。')
        if not isinstance(path, list) or len(path) > 256 or any(type(a) is not int or not 0 <= a < 16 for a in path):
            raise ValueError('sampling_path 必须是最多 256 个合法行动索引组成的数组。')
        if scope == 'entire_tree' and path:
            raise ValueError('Full Tree 不接受非空 sampling_path。')
        result.update(sampling_scope=scope, sampling_path=list(path))
    return result


def sampling_selection(compact, scope='entire_tree', path=None):
    controls = validated_sampling({'sampling_scope': scope, 'sampling_path': [] if path is None else path})
    node_id = compact['root']
    for edge in controls['sampling_path']:
        children = compact['nodes'][node_id]['children']
        if edge >= len(children):
            raise ValueError('所选子树路径不存在，或经过了终局。请重新选择决策点。')
        node_id = children[edge]
    node = compact['nodes'][node_id]
    if scope == 'selected_subtree':
        if not node['children'] or node['actor'] < 0:
            raise ValueError('Selected Subtree 必须选择一个非终局决策点。')
        if node['street'] != 0:
            raise ValueError('与当前 HRC 采样窗口一致，Selected Subtree 仅支持翻前决策点。')
    return {**controls, 'root_node_id': node_id, 'street': node['street']}


def write_scope_descriptor(compact, output, scope, path):
    selection = sampling_selection(compact, scope, path)
    if scope == 'entire_tree':
        return None, selection
    target = Path(output)/'sampling-scope.bin'
    edges = selection['sampling_path']
    target.write_bytes(b'HRSCOPE1' + struct.pack('<I', len(edges)) + struct.pack(f'<{len(edges)}I', *edges))
    return target, selection


def preserve_ci_identity(compact, resume_from):
    """Retain historical CI/provenance metadata without accepting game changes.

    Independently reconstructed settings may have a different source settings
    digest while every computational input is identical. Preserve that original
    diagnostic provenance only after comparing all other portable input fields.
    """
    path = Path(resume_from).parent/'tree.json'
    if not path.is_file():
        return compact
    import json
    source = json.loads(path.read_text(encoding='utf-8'))
    result = deepcopy(compact)
    result.pop('ci', None)
    if 'ci' in source:
        result['ci'] = deepcopy(source['ci'])
    if {k:v for k,v in result.items() if k != 'provenance'} == {k:v for k,v in source.items() if k != 'provenance'}:
        result.pop('provenance', None)
        if 'provenance' in source:
            result['provenance'] = deepcopy(source['provenance'])
    return result


def algorithm_resume(checkpoint, output, mode, allow_change):
    """Copy only for an explicitly selected v3/v4 change; never edit the source."""
    path = Path(checkpoint)
    with path.open('rb') as stream:
        header = stream.read(36)
    if len(header) != 36 or header[:8] not in (b'HRSOLV01', b'HRSOLV02', b'HRSOLV03'):
        raise ValueError('不完整或未知版本的原生检查点。')
    previous = struct.unpack_from('<I', header, 32)[0]
    if previous not in (0, 1):
        raise ValueError('检查点算法标记无效。')
    requested = int(mode == 'v4')
    if previous == requested or not allow_change:
        return checkpoint, None
    target = Path(output)/'algorithm-resume.bin'
    if path.resolve().parent == Path(output).resolve():
        raise ValueError('切换算法必须创建新任务，不能原地覆盖检查点。')
    with path.open('rb') as source, target.open('xb') as dest:
        updated = bytearray(source.read(36))
        struct.pack_into('<I', updated, 32, requested)
        dest.write(updated)
        shutil.copyfileobj(source, dest, length=1024*1024)
    return target, {'from': 'v4' if previous else 'v3', 'to': mode,
                    'node_stores_preserved': True, 'source_preserved': True}
