"""Bundled declarative betting presets and standalone hand setups.

HRC .preflop.js configuration files contain assignments of JSON values. Parse
that restricted data grammar without executing JavaScript or accessing HRC.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re

from .hrc_tree_builder import _Builder, default_settings

DATA = Path(__file__).with_name('data')
MAX_PRESET_BYTES = 128 * 1024


def validate_preflop(block):
    if not isinstance(block, dict) or set(block) != {'id', 'settings'}:
        raise ValueError('翻前预设需要 id 和 settings。')
    if block['id'] not in ('preflop.settings.simple', 'preflop.settings.general'):
        raise ValueError('仅支持 Simple 或 Advanced 翻前配置。')
    if not isinstance(block['settings'], dict):
        raise ValueError('预设 settings 必须是对象。')
    settings = default_settings(2)
    settings['treeconfig']['preflop'] = deepcopy(block)
    _Builder(settings, 10, None, None, 'none')
    return deepcopy(block)


def parse_preflop(text):
    if isinstance(text, bytes):
        if len(text) > MAX_PRESET_BYTES:
            raise ValueError('翻前预设文件不能超过 128 KiB。')
        try:
            text = text.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('翻前预设需使用 UTF-8 编码。') from exc
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_PRESET_BYTES:
        raise ValueError('翻前预设文件不能超过 128 KiB。')
    text = text.lstrip('\ufeff')
    decoder = json.JSONDecoder(parse_constant=lambda value: (_ for _ in ()).throw(ValueError('预设不能含有非有限数值。')))
    values, offset = {}, 0
    while offset < len(text):
        whitespace = re.match(r'(?:\s+|//[^\n]*(?:\n|$)|/\*[\s\S]*?\*/)*', text[offset:])
        offset += whitespace.end()
        if offset == len(text):
            break
        match = re.match(r'([A-Z][A-Z0-9_]*)\s*=\s*', text[offset:])
        if not match:
            raise ValueError('仅支持“配置名 = JSON 值;”形式的翻前预设。')
        key = match.group(1)
        if key in values:
            raise ValueError('预设参数重复：' + key)
        offset += match.end()
        try:
            value, end = decoder.raw_decode(text, offset)
        except (ValueError, RecursionError) as exc:
            raise ValueError('预设参数不是有效的 JSON 值：' + key) from exc
        offset = end
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset >= len(text) or text[offset] != ';':
            raise ValueError('预设参数末尾缺少分号：' + key)
        offset += 1
        values[key] = value
    policy = values.pop('CONFIGURATION_ID', None)
    return validate_preflop({'id': policy, 'settings': values})


@lru_cache(maxsize=1)
def _catalog():
    rows = json.loads((DATA / 'preflop_presets.json').read_text(encoding='utf-8'))
    if not isinstance(rows, list) or len({row['id'] for row in rows}) != len(rows):
        raise ValueError('内置翻前预设目录无效。')
    for row in rows:
        validate_preflop(row['preflop'])
    return rows


def preflop_presets():
    return deepcopy(_catalog())


def preset_for(identity):
    for row in _catalog():
        if row['id'] == identity:
            return deepcopy(row['preflop'])
    raise ValueError('未知翻前预设：' + str(identity))


def apply_preflop(tree_settings, identity):
    result = deepcopy(tree_settings)
    if result.get('mode') != 'ui':
        raise ValueError('翻前预设需要可编辑的下注设置。')
    result['preflop'] = preset_for(identity)
    return result


def scenario_presets():
    return json.loads((DATA / 'scenario_presets.json').read_text(encoding='utf-8'))
