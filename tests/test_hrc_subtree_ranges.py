from dataclasses import asdict
import math
from pathlib import Path

import pytest

from preflop_lab.hrc_dynamic import COMBOS
from preflop_lab.hrc_chance import ChanceSampler
from preflop_lab.hrc_subtree_ranges import (
    PREFLOP_CLASSES,apply_blockers,board_text,expand_preflop,extract_reach,
    multiply_action,range_text,
)
from preflop_lab.hrc_tree_builder import build_tree,default_settings

FLOP=(1<<51)|(1<<28)|(1<<22)
BOARD=(0,FLOP,FLOP|(1<<4),FLOP|(1<<4)|(1<<1))


@pytest.fixture(scope='module')
def tree():
    settings=default_settings(3,stack=[25000,50000,50000])
    settings['engine']['maxactive']=3
    settings['treeconfig']['preflop']['settings']['ALLOWED_FLATS_PER_RAISE']=[1,2,1,1,1]
    return build_tree(settings,node_budget=50000)


def probabilities(tree,node_id,edge):
    node=tree.nodes[node_id]
    count=len(node.children)
    value=(edge+1)/(count*(count+1)/2)
    return [value]*tree.rules.buckets[node.street]


def mapping(tree,street,history,actor):
    return [-1 if mask&history[street] else i%tree.rules.buckets[street] for i,mask in enumerate(COMBOS)]


def extract(tree,node,**kwargs):
    return extract_reach(tree,tree.node_path(node.id),BOARD,
        lambda n,e:probabilities(tree,n,e),lambda s,b,p:mapping(tree,s,b,p),**kwargs)


def test_actual_generated_tree_path_product_and_state_preserved(tree):
    node=next(n for n in tree.nodes if not n.terminal and n.street==1)
    before=asdict(tree.states[node.id])
    result=extract(tree,node)
    factors=[1.]*3;cursor=tree.nodes[tree.root]
    for edge in result.path:
        factors[cursor.actor]*=probabilities(tree,cursor.id,int(edge))[0]
        cursor=tree.nodes[cursor.children[int(edge)]]
    for p,row in enumerate(result.ranges):
        assert row==tuple(0. if mask&BOARD[-1] else factors[p] for mask in COMBOS)
    assert result.initial_state['initial_stacks']==list(tree.rules.initial_stacks)
    assert result.initial_state['contributions']==before['contributions']
    assert asdict(tree.states[node.id])==before
    assert len(result.trace)==len(result.path)
    assert result.active==tuple(not f and r>0 for f,r in zip(before['folded'],before['remaining']))
    assert result.provenance['original_wizard_compatible']


def test_allin_and_folded_are_inactive_but_ranges_retained(tree):
    node=next(n for n in tree.nodes if not n.terminal and n.street>0 and
              any(tree.states[n.id].remaining[p]==0 and not tree.states[n.id].folded[p] for p in range(3)))
    result=extract(tree,node)
    assert len(result.ranges)==3
    for p,remaining in enumerate(tree.states[node.id].remaining):
        if remaining==0 or tree.states[node.id].folded[p]:
            assert result.active[p] is False
            assert any(value>0 for value in result.ranges[p])
    assert result.provenance['selection_semantics']=='independent_midstreet_extension'
    assert not result.provenance['original_wizard_compatible']
    assert any(action['street']==node.street for action in result.sequence)
    assert all(a['street']<node.street for a in result.provenance['original_wizard_sequence'])


def test_zero_mass_inactive_seat_is_reported_and_not_replaced(tree):
    node=next(n for n in tree.nodes if not n.terminal and n.street==1 and any(tree.states[n.id].folded))
    seat=tree.states[node.id].folded.index(True)
    ranges=[None]*3;ranges[seat]=[0.]*1326
    result=extract(tree,node,initial_ranges=ranges)
    assert seat in result.zero_mass_seats and not result.active[seat]
    assert not any(result.ranges[seat])
    with pytest.raises(ValueError,match='positive'):
        ChanceSampler(list(result.ranges),BOARD)


def test_rounding_can_make_an_existing_path_unreachable(tree):
    node=next(n for n in tree.nodes if not n.terminal and n.street==1)
    result=extract(tree,node,initial_ranges=[[.0001]*1326,None,None],range_precision=2)
    assert 0 not in result.zero_mass_seats
    assert 0 in result.serialized_zero_mass_seats
    assert result.subtree_config['players']['0']['range']==''


def test_initial_169_or_1326_ranges_are_reach_factors_not_normalized(tree):
    node=next(n for n in tree.nodes if not n.terminal and n.street==1)
    base=extract(tree,node)
    values169=[(i+1)/169 for i in range(169)]
    values1326=[(i+1)/1326 for i in range(1326)]
    result=extract(tree,node,initial_ranges=[values169,values1326,None])
    for i,hole in enumerate(COMBOS):
        assert result.ranges[0][i]==pytest.approx(base.ranges[0][i]*values169[PREFLOP_CLASSES[i]],abs=1e-16)
        assert result.ranges[1][i]==pytest.approx(base.ranges[1][i]*values1326[i],abs=1e-16)
    assert sum(result.ranges[2])>1


def test_forced_actions_are_not_extra_probability_factors(tree):
    node=next(n for n in tree.nodes if not n.terminal and n.street>0 and len(n.incoming_actions)>1)
    calls=[]
    def policy(n,e):
        calls.append((n,e));return probabilities(tree,n,e)
    result=extract_reach(tree,tree.node_path(node.id),BOARD,policy,lambda s,b,p:mapping(tree,s,b,p))
    assert len(calls)==len(result.path)==len(result.trace)
    assert len(result.sequence)>len(result.path)


def test_board_and_original_shape_fields(tree):
    node=next(n for n in tree.nodes if not n.terminal and n.street==1)
    result=extract(tree,node,range_precision=3)
    assert board_text(BOARD)=='As9c7h3c2d'
    config=result.subtree_config
    assert set(config)=={'street','board','sequence','players'}
    assert list(config['players'])==['0','1','2']
    assert all(set(p)=={'active','range'} for p in config['players'].values())
    assert all(set(a)=={'player','type','amount','street'} for a in config['sequence'])
    assert result.provenance['range_precision']==3


def test_quantization_threshold_and_lossless_text():
    values=[0.]*1326;values[0]=1e-100;values[1]=.00049;values[2]=.0005;values[3]=.9996;values[4]=1.25
    text,parsed=range_text(values,3)
    assert parsed[:5]==[0,0,.001,1,1]
    assert '2s2c' in text
    exact,recovered=range_text(values)
    assert 'e-' not in exact and recovered==values
    assert len(exact)>100


def test_pure_weight_primitives_and_invalid_mapping():
    weights=[i/168 for i in range(169)]
    expanded=expand_preflop(weights,FLOP)
    assert expanded==[0. if m&FLOP else weights[c] for m,c in zip(COMBOS,PREFLOP_CLASSES)]
    assert apply_blockers([1.]*1326,BOARD[-1]).count(1.)==1081
    assert multiply_action([1.]*1326,[.2,.8],[i%2 for i in range(1326)])[:3]==[.2,.8,.2]
    assert multiply_action([1.]*1326,[1.],[-1]*1326)==[0.]*1326
    for buckets in ([2]*1326,[-2]*1326,[True]*1326):
        with pytest.raises(ValueError):multiply_action([1.]*1326,[1.],buckets)
    with pytest.raises(ValueError):multiply_action([1.]*1326,[1.01],[0]*1326)


def test_selection_and_probability_domain_failures(tree):
    with pytest.raises(ValueError,match='postflop'):extract_reach(tree,[],BOARD,None,None)
    terminal=next(n for n in tree.nodes if n.terminal)
    with pytest.raises(ValueError,match='postflop'):extract(tree,terminal)
    node=next(n for n in tree.nodes if not n.terminal and n.street==3)
    with pytest.raises(ValueError,match='Board history'):
        extract_reach(tree,tree.node_path(node.id),BOARD[:2],None,None)
    node=next(n for n in tree.nodes if not n.terminal and n.street==1)
    with pytest.raises(ValueError,match='169'):
        extract_reach(tree,tree.node_path(node.id),BOARD,lambda n,e:[.5],None)
    with pytest.raises(ValueError,match='finite'):
        extract(tree,node,initial_ranges=[[math.nan]*1326,None,None])


def test_actual_imported_topology_uses_explicit_synthetic_policy_only():
    from preflop_lab.hrc_tree import load_hrc_tree
    archive=Path(__file__).resolve().parents[1]/'analysis/hrc-desktop/nine20bb-raise-call-postflop-60m.hrcz'
    if not archive.exists():pytest.skip('Optional user-installed research archive unavailable')
    imported=load_hrc_tree(archive)
    node=next(n for n in imported.nodes if not n.terminal and n.street==1)
    result=extract(imported,node)
    assert len(result.ranges)==9 and len(result.active)==9
    assert result.initial_state['remaining']==imported.states[node.id].remaining
    assert result.provenance['original_strategy_auto_loaded'] is False
