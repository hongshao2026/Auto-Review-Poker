"""Cash-game rake controls; amounts use the scene's chip unit."""
from decimal import Decimal
from .tournament import _number

DEFAULTS = {'mode': 'none', 'percentage': 5, 'cap': 3}


def validated_rake(raw, utility):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError('rake 需要 mode、percentage、cap。')
    cfg = {**DEFAULTS, **raw}
    if cfg['mode'] not in ('none', 'nfnd', 'gg', 'full'):
        raise ValueError('rake.mode 必须为 none、nfnd、gg 或 full。')
    cfg['percentage'] = _number(cfg['percentage'], 'rake.percentage', maximum=100)
    cfg['cap'] = _number(cfg['cap'], 'rake.cap', maximum=1e8)
    if cfg['mode'] != 'none' and utility != 'chips':
        raise ValueError('现金局抽水仅适用于 ChipEV，不能与奖金或赏金模型组合。')
    if Decimal(str(cfg['cap'])) * 10000 != (Decimal(str(cfg['cap'])) * 10000).to_integral_value():
        raise ValueError('抽水上限最多保留 4 位小数。')
    return cfg


def rake_spec(config):
    cfg = validated_rake(config.get('rake', {'mode': 'none'}), config['utility'])
    if cfg['mode'] == 'none':
        return None
    if config.get('engine') not in ('hrc_custom', 'hrc_imported'):
        raise ValueError('抽水需要使用自定义原生行动树。')
    exact = Decimal(str(cfg['cap'])) * config.get('chip_scale', 10000)
    if exact != exact.to_integral_value():
        raise ValueError('抽水上限无法用当前内部筹码精度精确表示。')
    return {'mode': cfg['mode'], 'fraction': cfg['percentage'] / 100,
            'cap': int(exact)}


def add_terminal_context(compact, tree, rake):
    """Actual terminal street and all raise actions, including compressed edges."""
    if rake is None:
        return compact
    counts = {}
    for node in tree.nodes:
        counts[node.id] = (counts[node.parent_id] if node.parent_id >= 0 else 0) + sum(a.kind == 3 for a in node.incoming_actions)
    compact['rake'] = rake
    for terminal in compact['terminals']:
        node_id = terminal['node_id']
        terminal['street'] = tree.states[node_id].street
        terminal['raise_count'] = counts[node_id]
    return compact
