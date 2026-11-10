"""Pinned local research scenarios; archive policy values are never training input."""
from copy import deepcopy
from functools import lru_cache
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = ROOT / 'analysis/hrc-desktop'
CACHE = ROOT / '.research-cache'
ENGINE = 'hrc_v4_research'
MAX_SAMPLES = 1_000_000_000_000
# Not a registered preset until the completed original archive has a verified
# SHA-256. Keeping its configuration separate prevents premature availability.
EIGHT15BB_TEMPLATE = {
    'title': '八人 15BB · 翻前与翻后对照', 'seats': 8, 'stack': 15,
    'archive': 'eight15bb-raise-call-postflop-60m.hrcz',
}
SEAT_NAMES = {
    2: ('SB/BTN', 'BB'),
    8: ('UTG', 'EP', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB'),
    9: ('UTG', 'EP', 'MP1', 'MP2', 'HJ', 'CO', 'BTN', 'SB', 'BB'),
}
BENCHMARKS = {
    'eight15bb': {
        **EIGHT15BB_TEMPLATE,
        'sha256': '4cf1df34e8cef402087d713a0a9909637c86480bde05cefcd6ccd35a067b03c6',
    },
    'nine20bb': {
        'title': '九人 20BB · 翻前与翻后对照', 'seats': 9, 'stack': 20,
        'archive': 'nine20bb-raise-call-postflop-60m.hrcz',
        'sha256': '29fe171c91571705eca9105718db432e12638bc6dfd58c3ed66f057163c0abb8',
    },
    'nine10bb': {
        'title': '九人 10BB · 翻前与翻后对照', 'seats': 9, 'stack': 10,
        'archive': 'nine10bb-raise-call-postflop-initial.hrcz',
        'sha256': '84be4409a502db904597bbe76b5c2abc41e98ef8212d831be15523ef241649a3',
    },
    'hu10bb': {
        'title': '单挑 10BB · 全下独立基准', 'seats': 2, 'stack': 10,
        'archive': 'hu10bb-pushfold-10m.hrcz',
        'sha256': 'e2d0f3fa4253237604490391f10847122be4281f50ab2a82aeab392a81147e17',
    },
}
MODEL = {
    'title': '对照内核 · 独立训练',
    'continuation': '在固定对照行动树上，从零训练翻前及翻后策略；不沿用原版已训练范围。',
    'limitations': [
        '下注结构和翻后桶来自本机对照数据；并非独立生成全部下注树与抽象数据。',
        '各预设使用已封存的固定下注结构；合法动作以所选节点实际列出的行动为准。',
        '单线程执行恢复出的 v4 数值行为；不复现原版多线程的随机调度。',
        '完成采样预算不代表收敛；范围和 EV 误差以实际对照报告为准。',
        '翻后展示抽象桶，未选择公共牌时不把桶伪装成 169 类具体手牌。',
    ],
}


def config_for(name='nine20bb', iterations=100_000, seed=42):
    if name not in BENCHMARKS:
        raise ValueError('未知对照场景。请选择列出的本机研究预设。')
    case = BENCHMARKS[name]
    try:
        names = SEAT_NAMES[case['seats']]
    except KeyError:
        raise ValueError('对照场景尚未定义该人数的座位顺序。') from None
    heads_up = case['seats'] == 2
    return {'engine': ENGINE, 'benchmark': name,
            'players': [{'name': p, 'stack': case['stack'], 'range': 'all'} for p in names],
            'small_blind': .5, 'big_blind': 1, 'ante': 0,
            'open_sizes': [case['stack']] if heads_up else [2],
            'reraise_multipliers': [], 'max_raises': 0 if heads_up else 1,
            'utility': 'chips', 'payouts': [1] + [0] * (case['seats'] - 1),
            'iterations': iterations, 'seed': seed}


def validated_config(raw):
    from .core import _integer
    if not isinstance(raw, dict):
        raise ValueError('场景必须是 JSON 对象。')
    name = raw.get('benchmark', 'nine20bb')
    if not isinstance(name, str) or name not in BENCHMARKS:
        raise ValueError('未知对照场景。')
    from .hrc_sampling import iteration_limit
    expected = config_for(name, _integer(iteration_limit(raw), '采样次数', 100, MAX_SAMPLES),
                          _integer(raw.get('seed', 42), '随机种子', 0, 2**32-1))
    for key, value in expected.items():
        if key not in ('iterations', 'seed') and key in raw and raw[key] != value:
            raise ValueError(f'固定对照场景不允许修改 {key}；请选择另一预设，或切回自定义场景。')
    from .hrc_training import validated_training
    expected.update(validated_training(raw))
    if 'fgs' in raw:
        from .hrc_fgs_config import validated_fgs
        expected['fgs'] = validated_fgs(raw['fgs'], expected, len(expected['players']))
    return expected


@lru_cache(maxsize=8)
def _verify(path, size, modified, expected):
    with Path(path).open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected:
        raise ValueError('对照存档内容已变化，身份校验失败。请恢复研究记录中的原始文件。')


def archive_for(name):
    if name not in BENCHMARKS:
        raise ValueError('未知对照场景。')
    case = BENCHMARKS[name]
    expected = case.get('sha256')
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('该对照场景尚未封存有效的 SHA-256 身份，暂不可使用。')
    path = ARCHIVES / case['archive']
    if not path.is_file():
        raise ValueError('缺少本机对照存档，请先完成该场景的原版保存。')
    stat = path.stat()
    _verify(str(path), stat.st_size, stat.st_mtime_ns, expected)
    return path


def public_metadata():
    def available(name):
        try:
            archive_for(name)
        except ValueError:
            return False
        return True

    return {'engine': ENGINE, 'max_samples': MAX_SAMPLES, 'model': deepcopy(MODEL),
            'presets': [{'id': key, 'title': case['title'], 'config': config_for(key),
                         'available': available(key)}
                        for key, case in BENCHMARKS.items()]}
