"""General policy selectors, moving-button scope, and complete generated trees."""
import copy
import json
from pathlib import Path

import pytest

from preflop_lab.hrc_tree_builder import _Builder,build_tree,default_settings,TreeBuildError
from preflop_lab import hrc_general_policy as policy

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('n',range(2,11))
def test_moving_button_preserves_current_hand_and_configuration(n):
    cfg=default_settings(n,[1000+i*10 for i in range(n)],100)
    cfg['treeconfig']['preflop']['settings']['PREFLOP_SIZES']=['all-in']
    cfg['engine']['maxactive']=2
    fixed=build_tree(cfg);cfg['handdata']['movingBu']=True;moving=build_tree(cfg)
    assert fixed.nodes==moving.nodes and fixed.states==moving.states
    assert moving.settings['handdata']['movingBu'] is True
    assert fixed.provenance['settings_sha256']!=moving.provenance['settings_sha256']


@pytest.mark.parametrize('pre,post',[('general','simple'),('simple','general'),('general','general')])
def test_mixed_builtin_policies_generate_finite_deterministic_four_street_trees(pre,post):
    cfg=default_settings(3,150000,preflop_policy=pre,postflop_policy=post);old=copy.deepcopy(cfg)
    tree=build_tree(cfg);again=build_tree(cfg)
    assert cfg==old and tree.compact_export()==again.compact_export()
    assert {n.street for n in tree.nodes if not n.terminal}=={0,1,2,3}
    assert all(sum(s.remaining)+sum(s.contributions)+s.dead_money==450000 for s in tree.states)
    assert tree.provenance['saved_tree_read'] is False


def builder(n=5,stack=20000):
    cfg=default_settings(n,stack,100,preflop_policy='general',postflop_policy='general')
    cfg['treeconfig']['preflop']['settings'].update(PREFLOP_ALLIN_THRESHOLD=100,PREFLOP_ADD_ALLIN_SPR=0)
    return _Builder(cfg,10000,None,None,'none')


def test_position_order_wraps_at_button_and_hu_button_is_sb():
    b=builder()
    assert b.button==2
    # Seat order after the button is SB,BB,UTG,CO,BU.
    order=[3,4,0,1,2]
    assert all(policy.in_position(b,later,earlier) for i,earlier in enumerate(order) for later in order[i+1:])
    hu=builder(2);assert hu.button==0 and policy.in_position(hu,0,1)


def test_open_position_and_bb_isolation_settings_take_precedence():
    b=builder();c=b.initial()
    assert policy.pre_text(b,c,0)==b.pre['SIZES_OPEN_OTHERS']
    c=b.apply(b.apply(c,0),0)
    assert policy.pre_text(b,c,2)==b.pre['SIZES_OPEN_BU']
    c=b.apply(c,0)
    assert policy.pre_text(b,c,3)==b.pre['SIZES_OPEN_SB']
    c=b.apply(c,2)
    assert policy.pre_text(b,c,4)==b.pre['SIZES_OPEN_BB_VS_SB']


def test_preflop_optional_blind_override_falls_back_to_oop_then_ip():
    b=builder();c=b.apply(b.initial(),3,250);c=b.apply(b.apply(c,0),0)
    b.pre['SIZES_3BET_SB_VS_OTHER']=None;b.pre['SIZES_3BET_OOP']='4x'
    assert policy.pre_text(b,c,3)=='4x'
    b.pre['SIZES_3BET_OOP']=None
    assert policy.pre_text(b,c,3)==b.pre['SIZES_3BET_IP']


def test_cold_call_and_closing_action_exceptions_have_original_priority():
    b=builder();c=b.apply(b.apply(b.initial(),3,250),3,650)
    b.pre['ALLOWED_FLATS_PER_RAISE']=[9]*5;b.pre['ALLOW_COLD_CALLS']=False;b.pre['ALLOW_FLATS_CLOSING_ACTION']=False
    assert not policy.can_flat(b,c,2)
    b.pre['ALLOW_COLD_CALLS']=True;assert policy.can_flat(b,c,2)
    b.pre['ALLOW_COLD_CALLS']=False
    for _ in range(3):c=b.apply(c,0)
    assert b.actor(c)==0 and policy.closing_action(b,c,0)
    b.pre['ALLOWED_FLATS_PER_RAISE']=[0]*5;b.pre['ALLOW_FLATS_CLOSING_ACTION']=True
    assert policy.can_flat(b,c,0)


def test_general_postflop_parser_supported_units_and_empty_overrides():
    assert policy.post_specs('33% 66g, 3e 2x 2bb, all-in')==[('%',33.),('g',66.),('e',3),('x',2.),('bb',2.),('allin',0.)]
    assert policy.post_specs('2.5e 3.5e')==[('e',2),('e',4)]
    assert policy.post_specs('none')==policy.post_specs('-')==[]
    assert _Builder._parse_sizes('2bb 3bb + 1bb + 0.5bb, all-in')==[[('bb',2.)],[('bb',3.),('bb',1.),('bb',.5)],[('allin',0.)]]


def test_short_button_straddle_preserves_original_negative_spr_and_effective_clamp():
    cfg=default_settings(3,[25,25,2000],100,preflop_policy='general',postflop_policy='general')
    cfg['handdata'].update(skipSb=True,straddleType='BUTTON');cfg['handdata']['blinds'][2]=10
    b=_Builder(cfg,10000,None,None,'none');c=b.initial()
    assert b.actor(c)==2 and b.limits(c,2)==(400,25)
    assert policy.spr(b,c,2)<0
    assert b.sizings(c,2)==[25]


@pytest.mark.parametrize('street,key,value',[
    ('preflop','SIZES_OPEN_BU',None),('preflop','SIZES_3BET_OOP','process.exit()'),
    ('preflop','ALLOW_COLD_CALLS',1),('preflop','PREFLOP_ADD_ALLIN_SPR',float('inf')),
    ('postflop','POSTFLOP_LOW_SPR_BET',[None,None]),('postflop','POSTFLOP_TURN_BET',['0e','66%']),
    ('postflop','POSTFLOP_RIVER_RAISE',['2e']),('postflop','POSTFLOP_ALLOW_DONK',[1,0]),
])
def test_invalid_general_settings_rejected(street,key,value):
    cfg=default_settings(3,1000,100,preflop_policy='general',postflop_policy='general');cfg['treeconfig'][street]['settings'][key]=value
    with pytest.raises(TreeBuildError):build_tree(cfg)


def test_all_shipped_settings_were_exercised_against_original_methods_and_scripts():
    report=json.loads((ROOT/'reports/hrc-original-general-builder-validation.json').read_text())
    assert report['passed'] and report['context_count']>=5000 and report['moving_button_pairs']>=2500
    assert not report['uncovered_settings']
    assert set(report['covered_settings'])==set(policy.PRE_DEFAULTS)|set(policy.POST_DEFAULTS)
