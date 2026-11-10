"""Validated tournament inputs; payout amounts never share BB display units."""
from copy import deepcopy
import math

from .hrc_benchmarks import BENCHMARKS, MAX_SAMPLES, config_for

ENGINE = 'hrc_tournament'
MODEL = {
    'title': '锦标赛 · 原生研究内核',
    'continuation': '在所选固定树上独立训练翻前及翻后策略，以奖金及赏金权益变化为收益。',
    'limitations': [
        '本批入口复用固定对照行动树；筹码、盲注与下注尺寸由所选树确定。',
        '未来赏金按剩余赏金池与筹码比例估值；FGS 仅支持本桌 ICM，可组合 KO/PKO。',
        'FGS 未来手使用固定手牌排序的推注阈值模型，非未来所有手牌的完整行动树。',
        '奖金金额与 BB 是不同单位；当前模型未使用原版已训练策略作为训练初值。',
        '有限采样结果不代表已收敛或已与整个 HRC 产品等价。',
    ],
}


def _number(value, field, minimum=0, maximum=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field} 必须是数值。')
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f'{field} 必须是 {minimum:g} 到 {maximum:g} 的有限数值。')
    return result


def _vector(value, field, *, size=None, limit=10000, positive=False):
    if not isinstance(value, list) or len(value) > limit or (size is not None and len(value) != size):
        raise ValueError(f'{field} 数组长度不符合场景人数。')
    result = [_number(x, f'{field}[{i}]') for i, x in enumerate(value)]
    if positive and any(x <= 0 for x in result):
        raise ValueError(f'{field} 中筹码必须大于零。')
    return result


def default_config(benchmark='eight15bb'):
    base = config_for(benchmark)
    n = len(base['players'])
    return {**base, 'engine': ENGINE, 'utility': 'icm', 'payouts': [50, 30, 20][:n],
            'other_stacks': [], 'bounty': {'mode': 'none', 'amounts': [0] * n,
                                         'other_amounts': [], 'immediate_fraction': 1}}


def validated_config(raw):
    from .core import _integer
    if not isinstance(raw, dict) or raw.get('engine') != ENGINE:
        raise ValueError('锦标赛配置必须指定 hrc_tournament 内核。')
    name = raw.get('benchmark', 'eight15bb')
    if not isinstance(name, str) or name not in BENCHMARKS:
        raise ValueError('benchmark 必须选择已封存的行动树。')
    cfg = default_config(name)
    fixed = config_for(name)
    for field in ('players', 'small_blind', 'big_blind', 'ante', 'open_sizes', 'reraise_multipliers', 'max_raises'):
        if field in raw and raw[field] != fixed[field]:
            raise ValueError(f'固定行动树暂不允许修改 {field}。')
    from .hrc_sampling import iteration_limit
    cfg['iterations'] = _integer(iteration_limit(raw, cfg['iterations']), '采样次数', 100, MAX_SAMPLES)
    cfg['seed'] = _integer(raw.get('seed', cfg['seed']), '随机种子', 0, 2**32 - 1)
    cfg.update(validated_equity(raw, len(cfg['players'])))
    from .hrc_training import validated_training
    cfg.update(validated_training(raw))
    if 'fgs' in raw:
        from .hrc_fgs_config import validated_fgs
        cfg['fgs'] = validated_fgs(raw['fgs'], cfg, len(cfg['players']))
    return cfg


def validated_equity(raw, n):
    cfg = {'utility': raw.get('utility', 'icm')}
    if cfg['utility'] not in ('icm', 'mtt_icm'):
        raise ValueError('utility 必须为 icm 或 mtt_icm。')
    others = _vector(raw.get('other_stacks', []), 'other_stacks', positive=True)
    if cfg['utility'] == 'icm' and others:
        raise ValueError('other_stacks 仅可用于 mtt_icm。')
    prizes = _vector(raw.get('payouts', [50, 30, 20][:n]), 'payouts', limit=n + len(others))
    if not prizes or any(a < b for a, b in zip(prizes, prizes[1:])):
        raise ValueError('payouts 必须从冠军到末名按非递增顺序填写。')
    bounty = raw.get('bounty', {})
    if not isinstance(bounty, dict):
        raise ValueError('bounty 必须是对象。')
    kind = bounty.get('mode', 'none')
    if kind not in ('none', 'ko', 'pko'):
        raise ValueError('bounty.mode 必须为 none、ko 或 pko。')
    amounts = _vector(bounty.get('amounts', [0] * n), 'bounty.amounts', size=n)
    other_amounts = _vector(bounty.get('other_amounts', [0] * len(others)), 'bounty.other_amounts', size=len(others))
    fraction = _number(bounty.get('immediate_fraction', .5 if kind == 'pko' else 1),
                       'bounty.immediate_fraction', maximum=1)
    if kind == 'none' and (any(amounts) or any(other_amounts)):
        raise ValueError('bounty.mode=none 时不能有非零赏金。')
    if kind != 'pko' and fraction != 1:
        raise ValueError('bounty.immediate_fraction 仅 PKO 可小于 1。')
    if kind == 'ko' and len(set(amounts + other_amounts)) > 1:
        raise ValueError('固定 KO 的全场 bounty.amounts 与 other_amounts 必须相同。')
    if kind != 'none' and sum(amounts + other_amounts) <= 0:
        raise ValueError('启用赏金时 bounty 金额总和必须大于零。')
    if sum(prizes) + sum(amounts) + sum(other_amounts) <= 0:
        raise ValueError('payouts 与 bounty 总奖池不能同时为零。')
    cfg.update(payouts=prizes, other_stacks=others,
               bounty={'mode': kind, 'amounts': amounts, 'other_amounts': other_amounts,
                       'immediate_fraction': fraction})
    return cfg


def equity_spec(config, internal_bb):
    """Attach monetary model to immutable chip topology, using one chip scale."""
    cfg = validated_config(config)
    return {'mode': cfg['utility'], 'payouts': cfg['payouts'],
            'other_stacks': [s * internal_bb for s in cfg['other_stacks']],
            'bounty': deepcopy(cfg['bounty'])}


def public_metadata():
    from .hrc_benchmarks import public_metadata as reference_metadata
    available = {p['id']: p['available'] for p in reference_metadata()['presets']}
    return {'engine': ENGINE, 'max_samples': MAX_SAMPLES, 'model': deepcopy(MODEL),
            'presets': [{'id': key, 'title': case['title'].replace('翻前与翻后对照', '锦标赛权益'),
                         'config': default_config(key), 'available': available[key]}
                        for key, case in BENCHMARKS.items()]}
