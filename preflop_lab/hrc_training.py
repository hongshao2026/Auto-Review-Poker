"""Validated controls shared by the native application adapters."""
from copy import deepcopy
import math


def _probability(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('策略概率必须为 0–1 的有限数值。')
    return float(value)


def validated_training(raw):
    from .hrc_sampling import validated_sampling
    result = validated_sampling(raw)
    # An explicit CI stopping mode owns its tracker and default target. Legacy
    # target_ci without a mode still requires the explicit track_ci setting.
    raw = {**raw, **result}
    if 'constant_scalar_shortcuts' in raw:
        if type(raw['constant_scalar_shortcuts']) is not bool:
            raise ValueError('constant_scalar_shortcuts 必须是布尔值。')
        result['constant_scalar_shortcuts']=raw['constant_scalar_shortcuts']
    if 'threads' in raw:
        if type(raw['threads']) is not int or not 1<=raw['threads']<=32:
            raise ValueError('threads 必须是 1–32 的整数。')
        result['threads']=raw['threads']
    if 'max_memory_bytes' in raw:
        if type(raw['max_memory_bytes']) is not int or not (1<<20)<=raw['max_memory_bytes']<=(8<<30):
            raise ValueError('max_memory_bytes 必须为 1MiB–8GiB 的整数。')
        result['max_memory_bytes']=raw['max_memory_bytes']
    if 'stores' in raw:
        stores = raw['stores']
        if (not isinstance(stores, dict) or set(stores) != {'version', 'street_formats'}
            or type(stores['version']) is not int or stores['version'] != 1
            or not isinstance(stores['street_formats'], list) or len(stores['street_formats']) != 4
            or stores['street_formats'][0] != 23 or any(type(v) is not int or v not in (25, 27, 31) for v in stores['street_formats'][1:])):
            raise ValueError('stores 需要 version:1，street_formats 为 [23, 后街格式, 后街格式, 后街格式]；后街支持 25/27/31。')
        result['stores'] = deepcopy(stores)
    if 'solver_mode' in raw:
        if raw['solver_mode'] not in ('v3', 'v4'):
            raise ValueError('solver_mode 必须为 v3 或 v4。')
        result['solver_mode'] = raw['solver_mode']
    if 'track_ci' in raw:
        if type(raw['track_ci']) is not bool:
            raise ValueError('track_ci 必须是布尔值。')
        result['track_ci'] = raw['track_ci']
    for key in ('stop_after_seconds', 'hard_seconds', 'target_ci'):
        value = raw.get(key)
        if value is None:
            continue
        low, high = (1e-12, 1e12) if key == 'target_ci' else (.1, 86400)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} 必须为 {low:g}–{high:g} 的有限数值。')
        result[key] = float(value)
    if 'target_ci' in result and not result.get('track_ci'):
        raise ValueError('设置 CI 目标时必须启用 track_ci。')
    if 'policies' not in raw:
        return result
    policies = raw['policies']
    if not isinstance(policies, dict) or type(policies.get('version')) is not int or policies.get('version') != 1 or set(policies) != {'version', 'nodes'}:
        raise ValueError('policies 必须包含 version:1 和 nodes。')
    rows = policies['nodes']
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError('策略约束节点列表无效。')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get('node_id')) is not int or not 0 <= row['node_id'] < 1000000 or row['node_id'] in ids:
            raise ValueError('策略约束节点 ID 无效或重复。')
        ids.add(row['node_id'])
        if set(row) == {'node_id', 'locks'}:
            locks = row['locks']
            if not isinstance(locks, list) or not 2 <= len(locks) <= 16:
                raise ValueError('locks 必须按行动列出概率数组，未锁定行动使用 null。')
            sizes = set()
            for values in locks:
                if values is not None:
                    if not isinstance(values, list) or not 1 <= len(values) <= 8192:
                        raise ValueError('每个锁定行动需要完整的桶概率数组。')
                    sizes.add(len(values))
                    for value in values:
                        _probability(value)
            if len(sizes) > 1:
                raise ValueError('锁定概率数组长度不一致。')
            for b in range(next(iter(sizes), 0)):
                mass = sum(values[b] for values in locks if values is not None)
                if mass > 1 + 1e-12 or (all(values is not None for values in locks) and abs(mass - 1) > 1e-12):
                    raise ValueError('每手牌的锁定概率和不能超过 1；锁定全部行动时必须等于 1。')
        elif set(row) == {'node_id', 'frequency'}:
            frequency = row['frequency']
            if not isinstance(frequency, dict) or set(frequency) - {'targets', 'edges'}:
                raise ValueError('frequency 必须包含 targets，可选 edges。')
            targets = frequency.get('targets')
            if not isinstance(targets, list) or not 2 <= len(targets) <= 16:
                raise ValueError('频率目标需要按行动列出，未约束行动使用 null。')
            if sum(_probability(v) for v in targets if v is not None) > 1 + 1e-12:
                raise ValueError('行动频率目标总和不能超过 1。')
            edges = frequency.get('edges', [0] * len(targets))
            if not isinstance(edges, list) or len(edges) != len(targets) or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e12 for v in edges):
                raise ValueError('edges 需要按行动列出有限 EV 偏置。')
        else:
            raise ValueError('同一节点需要且只能使用 locks 或 frequency。')
    result['policies'] = deepcopy(policies)
    return result


def training_spec(config, tree):
    """Validate node dimensions and return only active compact extensions."""
    options = validated_training(config)
    if options.get('sampling_scope') == 'selected_subtree':
        from .hrc_sampling import sampling_selection
        sampling_selection(tree.compact_export(), options['sampling_scope'], options.get('sampling_path', []))
    result = {}
    if options.get('stores'):
        result['stores'] = deepcopy(options['stores'])
    policies = options.get('policies', {})
    if policies.get('nodes'):
        compact = tree.compact_export()
        for row in policies['nodes']:
            if row['node_id'] >= len(compact['nodes']):
                raise ValueError('策略约束节点不存在。')
            node = compact['nodes'][row['node_id']]
            actions = len(node['children'])
            if actions < 2:
                raise ValueError('终局或单行动节点不能设置策略约束。')
            if 'locks' in row:
                locks = row['locks']
                store = options.get('stores', {}).get('street_formats', [23, 25, 25, 25])[node['street']]
                if store == 25:
                    raise ValueError('翻后格式 25 不支持逐桶锁定；先升级到 27/31，或使用行动频率目标。')
                if len(locks) != actions or any(v is not None and len(v) != node['buckets'] for v in locks):
                    raise ValueError('锁定数组必须对应此节点的全部行动和手牌桶。')
                if node.get('special') and locks[0] is not None:
                    raise ValueError('可过牌节点的虚拟弃牌行动不能锁定。')
            elif len(row['frequency']['targets']) != actions:
                raise ValueError('频率目标数量与节点行动数不一致。')
        result['policies'] = deepcopy(policies)
    if options.get('track_ci'):
        result['ci'] = {'enabled': True}
    return result


def run_options(solver):
    options = {key: solver.config[key] for key in ('stop_after_seconds', 'hard_seconds', 'target_ci', 'max_memory_bytes') if key in solver.config} | {
            'mode': solver.config.get('solver_mode', 'v4'),
            'threads': solver.config.get('threads',1),
            'constant_scalar_shortcuts': solver.config.get('constant_scalar_shortcuts',True),
            'track_ci': solver.config.get('track_ci',False),
            'sampling_scope': solver.config.get('sampling_scope','entire_tree'),
            'sampling_path': solver.config.get('sampling_path',[]),
            'sampling_stage': solver.config.get('sampling_stage','calculation'),
            'stopping_mode': solver.config.get('stopping_mode'),
            'allow_algorithm_change': True,
            'reset_regret': getattr(solver, 'reset_regret', False),
            'reset_average': getattr(solver, 'reset_average', False)}
    if hasattr(solver, 'checkpoint_migration'):
        options['checkpoint_migration'] = solver.checkpoint_migration
    return options


def solver_compact(solver):
    """Portable training input; runtime resource locations never enter identity."""
    if hasattr(solver, 'compact_override'):
        return deepcopy(solver.compact_override)
    from .hrc_fgs_config import fgs_spec, CACHE_SHA256, CACHE_BYTES
    compact = solver.tree.compact_export()
    equity = getattr(solver, 'equity_config', None)
    if equity:
        compact['equity'] = equity
    compact.update(training_spec(solver.config, solver.tree))
    fgs = fgs_spec(solver.config.get('fgs'), equity, solver.tree,
                   chip_scale=solver.config.get('chip_scale',10000) if solver.config.get('engine') == 'hrc_custom' else None)
    if fgs:
        compact['fgs'] = {**fgs, 'chance_sha256': CACHE_SHA256, 'chance_bytes': CACHE_BYTES}
    from .hrc_rake import rake_spec, add_terminal_context
    add_terminal_context(compact, solver.tree, rake_spec(solver.config))
    return compact
