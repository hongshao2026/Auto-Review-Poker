from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
import struct
import zipfile

import pytest

from preflop_lab.hrc_hrcz_tree import load_archive_tree,replay_archive_tree
from preflop_lab.hrc_tree import TreeReplayError,HRCNode
from preflop_lab.hrc_tree_builder import build_tree,default_settings

ROOT=Path(__file__).resolve().parents[1]


def encode(nodes,order=None):
    result=bytearray(struct.pack('<i',len(nodes)))
    for i in range(len(nodes)) if order is None else order:
        node=nodes[i]
        result.extend(struct.pack('<iiBbh',node.id,node.parent_id,2 if node.terminal else 1,len(node.incoming_actions),len(node.children)))
        if not node.terminal:result.extend(struct.pack('<bb',node.street,node.actor))
        for action in node.incoming_actions:
            result.extend(struct.pack('<Q',action.kind|(action.actor<<8)|(action.allin<<12)|(action.street<<13)|(action.amount<<16)))
        result.extend(struct.pack('<'+'i'*len(node.children),*node.children))
    return bytes(result)


@pytest.mark.parametrize('path',sorted((ROOT/'analysis/hrc-desktop').glob('*.hrcz')),ids=lambda p:p.name)
def test_all_local_original_archives_replay_without_saved_utilities(path):
    # Local archives also include preserved user backups. They are not all
    # supported-size fixtures: assert the parser's explicit rejection instead
    # of requiring a >1m-node backup to bypass its allocation bound.
    with zipfile.ZipFile(path) as archive, archive.open('gametree.dat') as member:
        count, = struct.unpack('<i', member.read(4))
    if not 1 <= count <= 1_000_000:
        with pytest.raises(TreeReplayError, match='Tree node count outside supported bounds'):
            load_archive_tree(path)
        return
    tree=load_archive_tree(path)
    assert tree.validation['all_nodes_conserve_chips']
    assert tree.validation['all_actions_rule_checked']
    assert not tree.provenance['topology_rebuilt']
    assert not tree.provenance['saved_terminal_utilities_loaded']
    assert sorted(tree.record_order)==list(range(len(tree.nodes)))
    assert len(asdict(tree)['states'])==len(tree.nodes)
    tree.require_trainable()
    compact=tree.compact_export()
    assert all('dead_money' in t and 'raise_count' in t for t in compact['terminals'])


@pytest.mark.parametrize('n',range(2,11))
@pytest.mark.parametrize('ante_type',['REGULAR','BB_ANTE_ANTE_FIRST','BB_ANTE_BLIND_FIRST'])
def test_saved_unequal_short_stacks_antes_and_bb_pool(n,ante_type):
    settings=default_settings(n,[300+i*10 for i in range(n)],100)
    settings['handdata'].update(anteType=ante_type)
    settings['handdata']['blinds'][2]=40
    settings['handdata']['stacks'][-1]=50
    settings['engine']['maxactive']=2
    pre=settings['treeconfig']['preflop']['settings']
    pre.update(PREFLOP_SIZES=['all-in'],ALLOWED_FLATS_PER_RAISE=[0,0])
    generated=build_tree(settings)
    saved=replay_archive_tree(settings,encode(generated.nodes))
    assert saved.nodes==generated.nodes
    for actual,expected in zip(saved.states,generated.states):
        for field in ('remaining','contributions','folded','dead_money','participant_mask','street'):
            assert getattr(actual,field)==getattr(expected,field)
        assert sum(actual.remaining)+actual.pot==sum(saved.rules.initial_stacks)


@pytest.mark.parametrize('straddle',['OFF','SINGLE','DOUBLE','BUTTON'])
@pytest.mark.parametrize('skip,moving',[(False,False),(True,False),(False,True),(True,True)])
def test_saved_straddle_skip_moving_and_scrambled_record_order(straddle,skip,moving):
    settings=default_settings(5,[800,900,700,650,550],100)
    settings['handdata'].update(straddleType=straddle,skipSb=skip,movingBu=moving)
    settings['treeconfig']['preflop']['settings']['PREFLOP_SIZES']=['all-in']
    generated=build_tree(settings)
    order=tuple(reversed(range(len(generated.nodes))))
    saved=replay_archive_tree(settings,encode(generated.nodes,order))
    assert saved.record_order==order
    assert saved.nodes==generated.nodes
    assert [s.remaining for s in saved.states]==[s.remaining for s in generated.states]
    assert saved.describe_node([])['topology_source']=='imported_hrc_saved_topology'


def test_no_builder_policy_or_script_execution(monkeypatch):
    settings=default_settings(3,1000,100)
    generated=build_tree(settings)
    settings['treeconfig']={'mode':'scripted','script':'deliberately not Python or JS execution'}
    from preflop_lab.hrc_tree_builder import _Builder
    for name in ('build','children','sizings','normalize','next_street'):
        monkeypatch.setattr(_Builder,name,lambda *a:pytest.fail('Saved topology must not be rebuilt'))
    saved=replay_archive_tree(settings,encode(generated.nodes))
    assert saved.nodes==generated.nodes
    assert any(x['scope']=='rebuild' for x in saved.validation['unsupported'])


def test_invalid_amount_allin_actor_or_early_leaf_rejected():
    settings=default_settings(3,1000,100)
    original=build_tree(settings)
    raise_node=next(n for n in original.nodes if n.incoming_actions and n.incoming_actions[0].kind==3)
    for field,value in (('amount',raise_node.incoming_actions[0].amount+1),('allin',not raise_node.incoming_actions[0].allin),('actor',2)):
        nodes=list(original.nodes)
        nodes[raise_node.id]=replace(raise_node,incoming_actions=(replace(raise_node.incoming_actions[0],**{field:value}),)+raise_node.incoming_actions[1:])
        with pytest.raises(TreeReplayError):replay_archive_tree(settings,encode(nodes))
    early=(HRCNode(0,-1,None,None,(),()),)
    with pytest.raises(TreeReplayError,match='unfinished'):replay_archive_tree(settings,encode(early))


def test_unknown_profile_remains_viewable_but_not_trainable():
    settings=default_settings(3,1000,100)
    original=build_tree(settings)
    settings['engine']['configuration']['abstractions'][1]['id']='unavailable'
    saved=replay_archive_tree(settings,encode(original.nodes))
    assert saved.describe_node()['actor']==0
    assert saved.settings['engine']['configuration']['abstractions'][1]['id']=='unavailable'
    with pytest.raises(ValueError,match='profile'):saved.require_trainable()


def test_saved_policy_can_stop_future_betting_without_default_rebuild():
    settings=default_settings(3,1000,100)
    settings['treeconfig']['postflop']['settings']['POSTFLOP_FORCE_CHECKDOWN_AFTER']=[0]*9
    settings['treeconfig']['preflop']['settings']['ALLOWED_FLATS_PER_RAISE']=[2,1,0]
    generated=build_tree(settings)
    saved=replay_archive_tree(settings,encode(generated.nodes))
    assert saved.validation['saved_early_checkdown_terminals']>0
    assert saved.nodes==generated.nodes


def test_allin_bb_ante_zero_contribution_seat_stays_live():
    settings=default_settings(2,[1000,50],100)
    settings['handdata']['blinds'][2]=100
    generated=build_tree(settings)
    saved=replay_archive_tree(settings,encode(generated.nodes))
    terminal=saved.compact_export()['terminals'][0]
    assert terminal['dead_money']==50
    assert terminal['contributions']==[50,0]
    assert terminal['live']==[0,1]


@pytest.mark.parametrize('root_contains_prefix',[False,True])
def test_subtree_sequence_replays_once_and_keeps_source_initial_stacks(root_contains_prefix):
    settings=default_settings(3,1000,100)
    generated=build_tree(settings)
    chosen=next(n for n in generated.nodes if n.street==1 and generated.nodes[n.parent_id].street==0)
    chain=[];cursor=chosen
    while True:
        chain.append(cursor)
        if cursor.parent_id<0:break
        cursor=generated.nodes[cursor.parent_id]
    sequence=tuple(a for n in reversed(chain) for a in n.incoming_actions)
    assert all(a.street==0 for a in sequence)
    ids=[];todo=[chosen.id]
    while todo:
        current=todo.pop();ids.append(current);todo.extend(reversed(generated.nodes[current].children))
    remap={old:new for new,old in enumerate(ids)}
    nodes=[]
    for old in ids:
        original=generated.nodes[old]
        nodes.append(replace(original,id=remap[old],parent_id=-1 if old==chosen.id else remap[original.parent_id],
            children=tuple(remap[c] for c in original.children),
            incoming_actions=(sequence if root_contains_prefix else ()) if old==chosen.id else original.incoming_actions))
    settings['subtree']={'street':1,'board':'AsKd2c','players':{},'sequence':[
        {'player':a.actor,'street':a.street,'type':('F','X','C','R')[a.kind],'amount':a.amount} for a in sequence]}
    replayed=replay_archive_tree(settings,encode(nodes))
    assert replayed.rules.initial_stacks==generated.rules.initial_stacks
    for old,new in remap.items():
        for field in ('remaining','contributions','folded','dead_money','street'):
            assert getattr(replayed.states[new],field)==getattr(generated.states[old],field)
    assert any(x['field']=='subtree' for x in replayed.validation['unsupported'])

