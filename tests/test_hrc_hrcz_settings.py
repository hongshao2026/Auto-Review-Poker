from copy import deepcopy
from pathlib import Path
import json
import zipfile

import pytest

from preflop_lab.hrc_custom import default_config
from preflop_lab.hrc_hrcz_settings import (settings_to_config,config_to_settings,
    config_to_state,expand_prizes)

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path',sorted((ROOT/'analysis/hrc-desktop').glob('*.hrcz')),ids=lambda p:p.name)
def test_real_settings_state_lossless_without_mutation(path):
    with zipfile.ZipFile(path) as archive:
        settings=json.loads(archive.read('settings.json'));state=json.loads(archive.read('state.json'))
    before=deepcopy((settings,state))
    cfg=settings_to_config(settings,state)
    assert config_to_settings(cfg)==settings
    assert config_to_state(cfg)==state
    assert (settings,state)==before
    assert cfg['hrcz_metadata']['source_training_iterations'] is None
    assert cfg['hrcz_metadata']['unsupported']==[]


@pytest.mark.parametrize('utility,mode',[('icm','none'),('icm','ko'),('icm','pko'),('mtt_icm','none'),('mtt_icm','ko'),('mtt_icm','pko')])
def test_monetary_bidirectional_and_external_units(utility,mode):
    cfg=default_config(4)
    cfg.update(utility=utility,payouts=[50,30,10,10])
    others=[20.,30.5] if utility=='mtt_icm' else []
    cfg['other_stacks']=others
    cfg['bounty']={'mode':mode,'amounts':([0.]*4 if mode=='none' else [7.]*4 if mode=='ko' else [1.,3.,5.,7.]),
        'other_amounts':([0.]*len(others) if mode=='none' else [7.]*len(others) if mode=='ko' else [2.,6.][:len(others)]),
        'immediate_fraction':.35 if mode=='pko' else 1.}
    settings=config_to_settings(cfg)
    mapped=settings_to_config(settings)
    for field in ('utility','big_blind','small_blind','ante','payouts','other_stacks'):
        assert mapped[field]==cfg[field]
    # HRC's handdata stores seat order and stacks, not arbitrary display names.
    assert [p['stack'] for p in mapped['players']]==[p['stack'] for p in cfg['players']]
    assert mapped['bounty']['amounts']==cfg['bounty']['amounts']
    assert mapped['bounty']['immediate_fraction']==cfg['bounty']['immediate_fraction']
    if utility=='mtt_icm':
        assert settings['eqmodel']['id']=='mtticm'
        assert settings['eqmodel']['otherstacks']==[2000.,3050.]
    if mode=='pko' and others:
        # Original file represents outside bounty pool by one average only.
        assert mapped['bounty']['other_amounts']==[4.,4.]
        assert sum(mapped['bounty']['other_amounts'])==sum(cfg['bounty']['other_amounts'])


@pytest.mark.parametrize('mode',['none','nfnd','gg','full'])
def test_cash_rake_fields_and_state_units(mode):
    cfg=default_config(2)
    cfg['rake']={'mode':mode,'percentage':7.25,'cap':2.125}
    settings=config_to_settings(cfg)
    mapped=settings_to_config(settings)
    assert mapped['rake']['mode']==mode
    if mode!='none':
        assert mapped['rake']==cfg['rake']
        assert settings['eqmodel']['rakecap']==21250
    state=config_to_state(cfg,eqpre=[15,15],eqpost=[14.9,15.1],units='scene')
    assert state=={'eqpre':[1500.,1500.],'eqpost':[1490.,1510.]}
    assert config_to_state(cfg,eqpre=[150000,150000],eqpost=[149000,151000],units='internal')==state


def test_fgs_nextlevel_uses_scene_units_and_preserves_ante_alias():
    cfg=default_config(3)
    cfg.update(utility='icm',payouts=[50,30,20],big_blind=2,small_blind=1,ante=.25)
    cfg['ante_type']='BB_ANTE_BLIND_FIRST'
    cfg['fgs']={'enabled':True,'depth':3,'depth3way':2,'next_level_at':2,
                'next_level':{'big_blind':4,'small_blind':2,'ante':.5}}
    settings=config_to_settings(cfg)
    assert settings['eqmodel']['id']=='fgs'
    assert settings['eqmodel']['nextlevel']=={'atdepth':2,'tolevel':[40000,20000,5000]}
    mapped=settings_to_config(settings)
    assert mapped['fgs']['next_level']==cfg['fgs']['next_level']
    assert mapped['ante_type']=='BB_ANTE_BLIND_FIRST'
    assert config_to_settings(mapped)==settings


def test_prize_steps_use_floor_entry_not_interpolation():
    assert expand_prizes({'prizes':{'1':100,'2':60,'5':30,'8':0}})==[100,60,60,60,30,30,30]
    assert expand_prizes({'prizes':{'1':10,'4':10}})==[10]*4
    assert expand_prizes({'prizes':{'1':0}})==[]
    assert expand_prizes({'prizes':{'1':20,'2':0,'5':0}})==[20,0,0,0]


def test_unknown_script_and_profile_preserved_and_explicit():
    settings=config_to_settings(default_config(3))
    settings['treeconfig']={'mode':'scripted','script':'throw new Error("never run")'}
    settings['engine']['configuration']['abstractions'][2]['id']='unknown-profile'
    settings['future_metadata']={'literal':['unchanged']}
    cfg=settings_to_config(settings)
    unsupported=cfg['hrcz_metadata']['unsupported']
    assert any(x['scope']=='rebuild' for x in unsupported)
    assert any(x['scope']=='training' and x['field']=='abstractions[2]' for x in unsupported)
    assert config_to_settings(cfg)==settings
    cfg['players'][0]['stack']=22
    edited=config_to_settings(cfg)
    assert edited['treeconfig']==settings['treeconfig']
    assert edited['engine']['configuration']==settings['engine']['configuration']
    assert edited['future_metadata']==settings['future_metadata']
    assert edited['handdata']['stacks'][0]==220000


def test_missing_state_cannot_be_fabricated_and_unknown_state_is_preserved():
    cfg=default_config(3)
    with pytest.raises(ValueError,match='observed eqpre'):config_to_state(cfg)
    settings=config_to_settings(cfg)
    state={'eqpre':[1.,2.,3.],'eqpost':[2.,2.,2.],'new_field':{'keep':True}}
    mapped=settings_to_config(settings,state)
    assert config_to_state(mapped,eqpost=[5.,5.,5.])['new_field']=={'keep':True}
    with pytest.raises(ValueError):settings_to_config(settings,{'eqpre':[1,2]})


@pytest.mark.parametrize('change',[
    lambda s:s['handdata'].update(anteType='invented'),
    lambda s:s['handdata'].update(blinds=[100,50,float('nan')]),
    lambda s:s['handdata'].update(stacks=[True,100]),
    lambda s:s['handdata'].update(skipSb=1),
])
def test_unknown_or_invalid_rule_is_rejected(change):
    settings=config_to_settings(default_config(3));change(settings)
    with pytest.raises(ValueError):settings_to_config(settings)


def test_integer_chip_precision_is_not_silently_rounded():
    cfg=default_config(2);cfg['players'][0]['stack']=1.00001
    with pytest.raises(ValueError,match='exactly'):config_to_settings(cfg)


def test_no_metadata_aliases_or_hidden_strategy_use():
    cfg=default_config(3);settings=config_to_settings(cfg)
    mapped=settings_to_config(settings,{'eqpre':[2,3,4],'eqpost':[9,8,7]})
    mapped['hrcz_metadata']['settings']['handdata']['stacks'][0]=1
    assert settings['handdata']['stacks'][0]==150000
    assert mapped['players'][0]['stack']==15


def test_changed_scene_cannot_silently_reuse_stale_archive_equities():
    settings=config_to_settings(default_config(3))
    mapped=settings_to_config(settings,{'eqpre':[1500]*3,'eqpost':[1400,1500,1600]})
    mapped['players'][0]['stack']=20
    with pytest.raises(ValueError,match='stale'):config_to_state(mapped)
    assert config_to_state(mapped,eqpre=[2000,1500,1500],eqpost=[2001,1500,1499])['eqpre']==[2000,1500,1500]

