"""Bundled inputs are standalone data and preserve unrelated hand settings."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from preflop_lab.hrc_presets import (
    MAX_PRESET_BYTES, apply_preflop, parse_preflop, preflop_presets,
    preset_for, scenario_presets,
)
from preflop_lab.hrc_custom import HRCCustomSolver, default_config, settings_for, validated_config
from preflop_lab.hrc_hrcz_settings import config_to_settings, config_to_state, settings_to_config
from preflop_lab.hrc_rake import rake_spec


@pytest.mark.parametrize('row', preflop_presets(), ids=lambda row: row['label'])
def test_each_bundled_preset_parses_as_declarative_file(row):
    block = row['preflop']
    text = '\ufeff// Data only\nCONFIGURATION_ID = ' + json.dumps(block['id']) + ';\n'
    text += '\n'.join(key + ' = ' + json.dumps(value) + ';' for key, value in block['settings'].items())
    assert parse_preflop(text.encode('utf-8')) == block
    cfg = default_config(3)
    before = deepcopy(cfg)
    cfg['tree_settings'] = apply_preflop(cfg['tree_settings'], row['id'])
    assert cfg['tree_settings']['preflop'] == block
    assert cfg['tree_settings']['postflop'] == before['tree_settings']['postflop']
    assert {k: v for k, v in cfg.items() if k != 'tree_settings'} == {k: v for k, v in before.items() if k != 'tree_settings'}
    preset_for(row['id'])['settings'].clear()
    assert preset_for(row['id']) == block


@pytest.mark.parametrize('suffix', [
    'fetch("https://invalid.example")',
    'PREFLOP_SIZES = (() => ["all-in"])();',
    'ALLOW_SB_COMPLETE = true; ALLOW_SB_COMPLETE = false;',
    'UNKNOWN_PARAMETER = 1;',
    'PREFLOP_ALLIN_THRESHOLD = NaN;',
    'PREFLOP_ALLIN_THRESHOLD = 1e999;',
    'ALLOW_SB_COMPLETE = 1;',
    'PREFLOP_SIZES = ["all-in"]',
])
def test_import_rejects_code_unknown_fields_bad_values_and_duplicates(suffix):
    with pytest.raises(ValueError):
        parse_preflop('CONFIGURATION_ID = "preflop.settings.simple"; ' + suffix)


def test_import_size_and_encoding_are_bounded():
    for text in (b' ' * (MAX_PRESET_BYTES + 1), b'\xff', '中' * MAX_PRESET_BYTES):
        with pytest.raises(ValueError):
            parse_preflop(text)


def test_embedded_browser_fallback_matches_canonical_catalog():
    path = Path(__file__).resolve().parents[1] / 'web/hrc-hand-setup.js'
    source = path.read_text(encoding='utf-8')
    encoded = source.split('window.HrcPreflopCatalog = ', 1)[1].split(';\n// END GENERATED PREFLOP CATALOG', 1)[0]
    assert json.loads(encoded) == preflop_presets()
    assert len(preflop_presets()) == 27
    assert sum(len(row['sources']) for row in preflop_presets()) == 33


def test_bubble_scenario_has_exact_visible_units_and_independent_inputs():
    cfg = scenario_presets()[0]['config']
    assert cfg['chip_scale'] == 100
    assert [p['stack'] for p in cfg['players']] == [19500, 89700, 39900, 107400, 41700, 49500, 26400, 8700]
    assert [p['name'] for p in cfg['players']] == ['UTG', 'EP', 'MP', 'HJ', 'CO', 'BU', 'SB', 'BB']
    assert len(cfg['other_stacks']) == 50 and len(cfg['payouts']) == 57
    assert sum(cfg['payouts']) == 14985
    assert sum(cfg['other_stacks']) == pytest.approx(3547200)
    assert 'hrcz_metadata' not in cfg and 'policy_source' not in cfg
    settings = config_to_settings(cfg)
    assert settings['handdata']['stacks'] == [int(p['stack'] * 100) for p in cfg['players']]
    assert settings['handdata']['blinds'] == [300000, 150000, 37500]
    assert settings['eqmodel']['otherstacks'] == cfg['other_stacks']
    restored = settings_to_config(settings, chip_scale=100)
    assert restored['other_stacks'] == cfg['other_stacks']
    assert [p['stack'] for p in restored['players']] == [p['stack'] for p in cfg['players']]


def test_scene_precision_reaches_training_equity_rake_and_export():
    cfg = default_config(2)
    cfg.update(chip_scale=100, big_blind=3000, small_blind=1500,
               utility='mtt_icm', other_stacks=[12345.67], payouts=[50, 30])
    cfg['players'][0]['stack'] = 19500.01
    cfg['players'][1]['stack'] = 89700
    cfg['tree_settings']['preflop']['settings']['PREFLOP_SIZES'] = ['all-in'] * 4
    cfg['tree_settings']['postflop']['settings']['POSTFLOP_FORCE_CHECKDOWN_AFTER'] = [0] * 9
    cfg['bounty']['other_amounts'] = [0]
    solver = HRCCustomSolver(cfg)
    assert solver.tree.rules.initial_stacks == (1950001, 8970000)
    assert solver.equity_config['other_stacks'] == [1234567]
    assert config_to_state(cfg, eqpre=[10, 20], eqpost=[11, 19], units='scene')['eqpre'] == [10, 20]
    cash = default_config(2)
    cash.update(chip_scale=100, rake={'mode': 'nfnd', 'percentage': 5, 'cap': 2.25})
    assert rake_spec(cash)['cap'] == 225
    cash['rake']['cap'] = 2.251
    with pytest.raises(ValueError, match='精度'):
        rake_spec(cash)
    cfg['ante'] = .001
    with pytest.raises(ValueError, match='精度'):
        settings_for(validated_config(cfg))
