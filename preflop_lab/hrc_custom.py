"""Independent configurable tree plus the audited native numerical kernel."""
from copy import deepcopy
from decimal import Decimal

from .core import _integer
from .hrc_benchmarks import MAX_SAMPLES, SEAT_NAMES
from .hrc_tree_builder import build_tree, default_settings
from .hrc_tournament import HRCTournamentSolver
from .tournament import _number, validated_equity

ENGINE = 'hrc_custom'
MODEL = {
    'title': '原生内核 · 自定义四街树',
    'continuation': '根据筹码、盲注和下注设置独立生成行动树，训练翻前及翻后策略。',
    'limitations': [
        '简单建树规则已有原版逐节点对照；其他配置的验证范围见研究记录。',
        '本入口目前使用本机 1024 / 256 / 256 翻后桶，未执行任意 JavaScript 建树脚本。',
        'FGS 使用固定排序阈值的未来手模型；moving button 只影响下一手轮转，动态抽象正在接入。',
        '逐桶锁定支持 23/27/31 存储；行动频率目标支持各街，目标是否达到需查看实际累计频率。',
        '未来赏金使用剩余赏金池的筹码比例模型；有限训练预算不代表已收敛。',
    ],
}


def default_config(players=8):
    names = SEAT_NAMES.get(players, tuple([f'P{i+1}' for i in range(players - 3)] + ['BTN', 'SB', 'BB']))
    return {'engine': ENGINE, 'players': [{'name': name, 'stack': 15, 'range': 'all'} for name in names],
            'small_blind': .5, 'big_blind': 1, 'ante': 0, 'ante_type': 'BB_ANTE_ANTE_FIRST',
            'straddle': 'OFF', 'skip_small_blind': False, 'moving_button': False,
            'tree_settings': default_settings(players)['treeconfig'], 'max_active': 4,
            'node_budget': 250000, 'utility': 'chips', 'payouts': [50, 30, 20][:players],
            'other_stacks': [], 'bounty': {'mode': 'none', 'amounts': [0]*players, 'other_amounts': [], 'immediate_fraction': 1},
            'chip_scale': 10000, 'iterations': 100000, 'seed': 42}


def validated_config(raw):
    if not isinstance(raw, dict) or raw.get('engine') != ENGINE:
        raise ValueError('自定义原生配置必须指定 hrc_custom 内核。')
    players = raw.get('players')
    if not isinstance(players, list) or not 2 <= len(players) <= 10:
        raise ValueError('本桌需要 2–10 个座位。')
    cfg = default_config(len(players))
    cfg['players'] = []
    for seat in players:
        if not isinstance(seat, dict) or not isinstance(seat.get('name'), str) or not 1 <= len(seat['name'].strip()) <= 30:
            raise ValueError('每个座位需要 1–30 字符的名称。')
        if seat.get('range', 'all') != 'all':
            raise ValueError('本入口的起始发牌范围目前必须为 all。')
        cfg['players'].append({'name': seat['name'].strip(), 'stack': _number(seat.get('stack'), 'stack', minimum=.0001, maximum=1e8), 'range': 'all'})
    for field in ('small_blind', 'big_blind', 'ante'):
        cfg[field] = _number(raw.get(field, cfg[field]), field, minimum=.0001 if field == 'big_blind' else 0, maximum=1e8)
    if cfg['small_blind'] > cfg['big_blind']:
        raise ValueError('小盲不能大于大盲。')
    for field, choices in [('ante_type', ('REGULAR', 'BB_ANTE_ANTE_FIRST', 'BB_ANTE_BLINDS_FIRST')),
                           ('straddle', ('OFF', 'SINGLE', 'DOUBLE', 'BUTTON'))]:
        cfg[field] = raw.get(field, cfg[field])
        if cfg[field] not in choices:
            raise ValueError(f'{field} 无效。')
    for field in ('skip_small_blind', 'moving_button'):
        cfg[field] = raw.get(field, False)
        if type(cfg[field]) is not bool:
            raise ValueError(f'{field} 必须是布尔值。')
    from .hrc_sampling import iteration_limit
    cfg['iterations'] = _integer(iteration_limit(raw), '采样次数', 100, MAX_SAMPLES)
    cfg['seed'] = _integer(raw.get('seed', 42), '随机种子', 0, 2**32-1)
    cfg['max_active'] = _integer(raw.get('max_active', 4), '最多参与者', 2, 10)
    cfg['node_budget'] = _integer(raw.get('node_budget', 250000), '树节点上限', 10, 1000000)
    cfg['chip_scale'] = _integer(raw.get('chip_scale', 10000), '内部筹码精度', 1, 100000000)
    cfg['tree_settings'] = deepcopy(raw.get('tree_settings', cfg['tree_settings']))
    utility = raw.get('utility', 'chips')
    if utility == 'chips':
        bounty = raw.get('bounty', {})
        if not isinstance(bounty, dict):
            raise ValueError('bounty 必须是对象。')
        if raw.get('other_stacks') or bounty.get('mode', 'none') != 'none' or any(bounty.get('amounts', [])) or any(bounty.get('other_amounts', [])):
            raise ValueError('赏金和外桌筹码需要奖金权益模型。')
    else:
        cfg.update(validated_equity(raw, len(players)))
    from .hrc_training import validated_training
    cfg.update(validated_training(raw))
    if 'fgs' in raw:
        from .hrc_fgs_config import validated_fgs
        cfg['fgs'] = validated_fgs(raw['fgs'], cfg, len(cfg['players']))
    if 'rake' in raw:
        from .hrc_rake import validated_rake
        cfg['rake'] = validated_rake(raw['rake'], cfg['utility'])
    return cfg


def settings_for(cfg):
    def chips(value):
        value = Decimal(str(value)) * cfg.get('chip_scale', 10000)
        if value != value.to_integral_value():
            raise ValueError('筹码和盲注无法用当前内部筹码精度精确表示。')
        return int(value)
    settings = default_settings(len(cfg['players']))
    settings['handdata'].update(stacks=[chips(p['stack']) for p in cfg['players']],
                                blinds=[chips(cfg['big_blind']), chips(cfg['small_blind']), chips(cfg['ante'])],
                                anteType=cfg['ante_type'], straddleType=cfg['straddle'],
                                skipSb=cfg['skip_small_blind'], movingBu=cfg['moving_button'])
    settings['treeconfig'] = deepcopy(cfg['tree_settings'])
    settings['engine']['maxactive'] = cfg['max_active']
    if cfg['utility'] != 'chips':
        settings['eqmodel'] = {'id': 'icm' if cfg['utility'] == 'icm' else 'mtt',
                               'structure': {'bountyType': cfg['bounty']['mode'].upper()}}
    else:
        from .hrc_rake import rake_spec
        rake = rake_spec(cfg)
        if rake:
            settings['eqmodel'].update(raked=True, rakepct=rake['fraction'], rakecap=rake['cap'],
                                       nfnd=rake['mode'] == 'nfnd', raketype_ggnetwork=rake['mode'] == 'gg')
    return settings


class HRCCustomSolver(HRCTournamentSolver):
    model = MODEL

    def __init__(self, config):
        self.config = validated_config(config)
        self.tree = build_tree(settings_for(self.config), node_budget=self.config['node_budget'])
        from .hrc_training import training_spec
        training_spec(self.config, self.tree)
        self.archive = None
        self.output = self.index = self.reference = self.resume_from = None
        self.equity_config = None if self.config['utility'] == 'chips' else {
            'mode': self.config['utility'], 'payouts': self.config['payouts'],
            'other_stacks': [s * self.config['chip_scale'] for s in self.config['other_stacks']],
            'bounty': deepcopy(self.config['bounty'])}

    def describe_node(self, path=None):
        node = super().describe_node(path)
        state = self.tree.states[node['native_id']]
        node['dead_money'] = state.dead_money / self.tree.rules.big_blind
        node['minimum_raise_to'] = state.minimum_raise_to / self.tree.rules.big_blind if state.minimum_raise_to >= 0 else None
        return node


def public_metadata():
    from .hrc_presets import preflop_presets, scenario_presets
    return {'engine': ENGINE, 'model': deepcopy(MODEL), 'default_config': default_config(),
            'moving_button': True,
            'chip_scales': [100, 10000],
            'preflop_presets': preflop_presets(), 'scenario_presets': scenario_presets(),
            'tree_policy_defaults': {street: {policy: default_settings(preflop_policy=policy, postflop_policy=policy)['treeconfig'][street]
                                      for policy in ('simple', 'general')} for street in ('preflop', 'postflop')},
            'max_samples': MAX_SAMPLES, 'max_players': 10}
