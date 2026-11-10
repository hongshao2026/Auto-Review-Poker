"""Production mode1 deal -> dynamic lookup -> traversal -> storage integration.

Dense synthetic maps isolate actor/street addressing. Original abstraction and
sampler mathematical parity have separate retained evidence suites.
"""
import copy
import hashlib
import json
import runpy
import struct
import subprocess

import numpy as np
import pytest

from preflop_lab.hrc_dynamic import DynamicAbstraction, prepare as prepare_map
from preflop_lab.hrc_native import ROOT, build, prepare, read_node, run

hu_tree = runpy.run_path(str(ROOT/'tests/test_hrc_kernel.py'))['hu_tree']


def combo(a,b):
    hi,lo=sorted((a,b),reverse=True)
    return hi*(hi-1)//2+lo


def fixed_tree(directory, *, street=3, table_prefix=None, real_map=False, players=2):
    directory.mkdir(parents=True,exist_ok=True)
    tree=hu_tree();tree['players']=players
    if players==3:
        tree['initial_stacks'].append(1000)
        for term in tree['terminals']:
            term['remaining'].append(1000);term['contributions'].append(0);term['folded'].append(True)
    board=[0,(1<<0)|(1<<5)|(1<<10)]
    board.extend([board[-1]|(1<<23),board[-1]|(1<<23)|(1<<28)])
    history=board[:street+1]
    hands=[combo(48,49),combo(44,45),combo(40,41)][:players]
    ranges=[]
    for hand in hands:
        row=[0.]*1326;row[hand]=1.;ranges.append(row)
    prefix=tuple(table_prefix or history)
    if real_map:
        mapping=prepare_map(prefix,street,'strict',ranges)
    else:
        rows=52**(street+1-len(prefix));maps=[]
        for p in range(players):
            if p==2:maps.append(None);continue
            data=np.zeros((rows,1326),dtype='<i4')
            data[:,hands[p]]=p+1
            # Exercise IDs for all configured buckets.
            data[:,20]=1
            maps.append(data)
        mapping=DynamicAbstraction(prefix,street,'synthetic-addressing',[2,3]+([0] if players==3 else []),maps)
    path=directory/f'street{street}-test.bin';mapping.write(path)
    for node in tree['nodes']:
        node['street']=street
        if node['children']:node['buckets']=mapping.effective[node['actor']]
    tree['chance']={'version':1,'mode':1,'board_history':history,'ranges':ranges,'max_attempts':1000,'max_random_calls':10000}
    tree['dynamic']={'version':1,'tables':[{'street':street,'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'effective_counts':mapping.effective}]}
    return tree,mapping,hands,board


@pytest.fixture(scope='module')
def probe(tmp_path_factory):
    build();info=json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text())
    executable=tmp_path_factory.mktemp('dynamic-probe')/'probe.exe'
    subprocess.run([info['compiler'],'c++','-O2','-std=c++17','-ffp-contract=off',str(ROOT/'scripts/native/dynamic_kernel_probe.cpp'),'-o',str(executable)],check=True,capture_output=True,text=True)
    return executable


@pytest.mark.parametrize('size',[0,3,55,56,63,64,65,100000])
def test_native_sha256_streaming(probe,tmp_path,size):
    path=tmp_path/'bytes';path.write_bytes(bytes((i*17+3)%256 for i in range(size)))
    assert subprocess.check_output([str(probe),'--digest',str(path)],text=True)==hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('street,prefix_length,real_map,players',[(3,4,False,3),(3,4,True,2),(2,2,False,2),(1,2,True,3)])
def test_actual_deal_lookups_and_terminal_values(probe,tmp_path,street,prefix_length,real_map,players):
    base=[0,(1<<0)|(1<<5)|(1<<10)];base.extend([base[-1]|(1<<23),base[-1]|(1<<23)|(1<<28)])
    tree,mapping,hands,board=fixed_tree(tmp_path/'resources',street=street,table_prefix=base[:prefix_length],real_map=real_map,players=players)
    binary=prepare(tree,tmp_path/'input')['tree_binary']
    rows=list(map(json.loads,subprocess.check_output([str(probe),binary,str(tmp_path/'resources'),'42','50'],text=True).splitlines()))
    assert len(rows)==50
    for row in rows:
        assert row['combos']==hands
        assert row['board'][:street+1]==board[:street+1]
        used=row['board'][-1]
        for hole in row['holes']:
            assert used & hole == 0;used |= hole
        expected=mapping.map(row['board'],hands)
        assert row['hands']==expected[:2]
        assert row['terminals'][:2]==[[-.5,.5]+([0] if players==3 else []),[1.,-1.]+([0] if players==3 else [])]
        assert all(abs(sum(values))<1e-12 for values in row['terminals'])
        if street==3:assert row['terminals'][2]==[10.,-10.]+([0] if players==3 else [])


@pytest.mark.parametrize('store',[25,27,31])
def test_fresh_training_updates_actor_bucket_and_resume_exact(tmp_path,store):
    tree,_,_,_=fixed_tree(tmp_path/'resources')
    tree['stores']={'version':1,'street_formats':[23,store,store,store]}
    run(tree,tmp_path/'resources',1000,42,tmp_path/'direct')
    run(tree,tmp_path/'resources',400,42,tmp_path/'partial')
    run(tree,tmp_path/'resources',1000,999,tmp_path/'resumed',resume_from=tmp_path/'partial/checkpoint.bin',max_memory_bytes=2<<30)
    assert (tmp_path/'direct/checkpoint.bin').read_bytes()==(tmp_path/'resumed/checkpoint.bin').read_bytes()
    for node_id,hand in [(0,1),(2,2)]:
        result=read_node(tmp_path/'direct',node_id)
        assert result['hands'][hand]['visits']>0
        assert all(row['visits']==0 for i,row in enumerate(result['hands']) if i!=hand)
    index=json.loads((tmp_path/'direct/index.json').read_text())
    assert abs(sum(index['root_mean_net_bb']))<1e-12


def test_joint_range_failure_is_explicit_and_keeps_zero_checkpoint(tmp_path):
    tree,_,_,_=fixed_tree(tmp_path/'resources')
    tree['chance']['ranges'][1]=tree['chance']['ranges'][0][:]
    tree['chance']['max_attempts']=3
    with pytest.raises(RuntimeError,match='rejection-attempt'):
        run(tree,tmp_path/'resources',100,42,tmp_path/'output')
    failure=json.loads((tmp_path/'output/failure.json').read_text())
    assert failure['resource_limit'] and failure['checkpoint_path']
    assert struct.unpack_from('<Q',(tmp_path/'output/checkpoint.bin').read_bytes(),16)[0]==0


def test_random_call_budget_and_sampling_cancel(probe,tmp_path):
    tree,_,_,_=fixed_tree(tmp_path/'resources')
    binary=prepare(tree,tmp_path/'input')['tree_binary']
    result=json.loads(subprocess.check_output([str(probe),binary,str(tmp_path/'resources'),'42','1','cancel'],text=True))
    assert result=={'cancelled':True,'samples':0,'epoch':0}
    tree['chance']['max_random_calls']=1
    with pytest.raises(RuntimeError,match='random-call'):
        run(tree,tmp_path/'resources',1,42,tmp_path/'budget')
    assert json.loads((tmp_path/'budget/failure.json').read_text())['resource_limit']


@pytest.mark.parametrize('cancel',[False,True])
def test_sampling_stop_rolls_back_to_complete_checkpoint(tmp_path,cancel):
    tree,_,_,_=fixed_tree(tmp_path/'resources')
    tree['chance']['ranges'][1]=tree['chance']['ranges'][0][:]
    tree['chance'].update(max_attempts=1_000_000_000,max_random_calls=1_000_000_000)
    result=run(tree,tmp_path/'resources',100,42,tmp_path/'out',stop_after_seconds=.1,
               cancel_check=(lambda:True) if cancel else None)
    summary=result['summary']
    assert summary['iteration']==0 and summary['rolled_back_to_checkpoint']
    assert summary['stop_reason']==('cancelled' if cancel else 'time_target')
    assert summary['cancelled']==cancel and not summary['partial_iteration_saved']
    assert struct.unpack_from('<Q',(tmp_path/'out/checkpoint.bin').read_bytes(),16)[0]==0


@pytest.mark.parametrize('field,value',[
    ('mode',2),('board_history',[0,1]),('max_attempts',0),('max_random_calls',True),('ranges',[None]),
])
def test_invalid_chance_configuration(tmp_path,field,value):
    tree,_,_,_=fixed_tree(tmp_path/'resources');tree['chance'][field]=value
    with pytest.raises(ValueError):prepare(tree,tmp_path/'out')


@pytest.mark.parametrize('alteration',['digest','size','prefix','effective','missing','filename','nodecount'])
def test_resource_identity_and_domain_rejection(tmp_path,alteration):
    tree,_,_,_=fixed_tree(tmp_path/'resources');desc=tree['dynamic']['tables'][0]
    if alteration=='digest':desc['sha256']='0'*64
    if alteration=='size':desc['bytes']+=1
    if alteration=='prefix':tree['chance']['board_history'][-1]^=(1<<28)|(1<<29)
    if alteration=='effective':desc['effective_counts'][0]=3;tree['nodes'][0]['buckets']=3
    if alteration=='missing':tree['dynamic']['tables']=[]
    if alteration=='filename':desc['file']='../outside.bin'
    if alteration=='nodecount':tree['nodes'][0]['buckets']=4
    with pytest.raises((ValueError,RuntimeError)):
        run(tree,tmp_path/'resources',1,42,tmp_path/'out')


def test_memory_preallocation_limit_with_int32_bucket_count(tmp_path):
    tree,_,_,_=fixed_tree(tmp_path/'resources');tree['nodes'][0]['buckets']=2**31-1
    tree['dynamic']['tables'][0]['effective_counts'][0]=2**31-1
    with pytest.raises(RuntimeError,match='memory budget'):
        run(tree,tmp_path/'resources',0,42,tmp_path/'out',max_memory_bytes=1<<20)
    assert json.loads((tmp_path/'out/failure.json').read_text())['resource_limit']
    assert not (tmp_path/'out/checkpoint.bin').exists()


def test_missing_dynamic_street_never_falls_back(tmp_path):
    tree,_,_,_=fixed_tree(tmp_path/'resources',street=1)
    tree['nodes'][2]['street']=2
    with pytest.raises(ValueError,match='Missing dynamic table'):prepare(tree,tmp_path/'out')


def test_more_than_16384_buckets_actually_train(tmp_path):
    flop=[0,(1<<0)|(1<<5)|(1<<10)]
    tree,mapping,hands,_=fixed_tree(tmp_path/'resources',street=2,table_prefix=flop)
    mapping.effective[0]=20000;mapping.maps[0][:,hands[0]]=19999
    descriptor=tree['dynamic']['tables'][0];path=tmp_path/'resources'/descriptor['file'];mapping.write(path)
    descriptor['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    tree['nodes'][0]['buckets']=20000
    run(tree,tmp_path/'resources',100,42,tmp_path/'out',max_memory_bytes=4<<20)
    index=json.loads((tmp_path/'out/index.json').read_text());node=index['nodes'][0]
    with (tmp_path/'out/checkpoint.bin').open('rb') as stream:
        stream.seek(node['visits_offset']);visits=struct.unpack('<20000Q',stream.read(20000*8))
    assert visits[19999]==100 and sum(visits)==100


def test_lazy_lookup_switches_actor_and_street(probe,tmp_path):
    resources=tmp_path/'resources';tree,_,hands,board=fixed_tree(resources,street=1)
    turn_tree,turn,_,_=fixed_tree(resources,street=2,table_prefix=board[:2])
    turn.maps[1][:,hands[1]]=0;turn.maps[1][:,21]=2
    descriptor=turn_tree['dynamic']['tables'][0];path=resources/descriptor['file'];turn.write(path)
    descriptor['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    tree['nodes'][2]['street']=2;tree['dynamic']['tables'].append(descriptor)
    binary=prepare(tree,tmp_path/'input')['tree_binary']
    records=list(map(json.loads,subprocess.check_output([str(probe),binary,str(resources),'43','20'],text=True).splitlines()))
    assert all(row['hands']==[1,0] for row in records)
    run(tree,resources,100,43,tmp_path/'out')
    assert read_node(tmp_path/'out',2)['hands'][0]['visits']>0


def test_uniform_folded_seat_receives_dead_cards(probe,tmp_path):
    tree,_,hands,board=fixed_tree(tmp_path/'resources',players=3)
    tree['chance']['ranges'][2]=None
    binary=prepare(tree,tmp_path/'input')['tree_binary']
    records=list(map(json.loads,subprocess.check_output([str(probe),binary,str(tmp_path/'resources'),'44','100'],text=True).splitlines()))
    assert len({row['combos'][2] for row in records})>80
    for row in records:
        assert row['combos'][:2]==hands[:2]
        assert row['holes'][2] & (row['holes'][0]|row['holes'][1]|board[-1])==0


def test_range_chance_unequal_weights_and_joint_blockers(probe,tmp_path):
    tree,_,hands,_=fixed_tree(tmp_path/'resources')
    a=combo(40,41);b=combo(36,37);c=combo(41,42);d=combo(32,33)
    for p,pairs in enumerate([[(a,3.),(b,1.)],[(c,2.),(d,1.)]]):
        weights=[0.]*1326
        for hand,weight in pairs:weights[hand]=weight
        tree['chance']['ranges'][p]=weights
    binary=prepare(tree,tmp_path/'input')['tree_binary']
    records=list(map(json.loads,subprocess.check_output([str(probe),binary,str(tmp_path/'resources'),'45','4000'],text=True).splitlines()))
    counts={pair:sum(tuple(row['combos'])==pair for row in records) for pair in [(a,d),(b,c),(b,d)]}
    # Joint product mass conditioned on no collision: 3 : 2 : 1.
    assert sum(counts.values())==4000
    assert [counts[p]/4000 for p in counts]==pytest.approx([.5,1/3,1/6],abs=.025)


@pytest.mark.parametrize('store,policy',[(25,None),(27,None),(31,None),(27,'locks'),(31,'frequency')])
def test_sparse_bucket_reader_matches_complete_rows(tmp_path,store,policy):
    tree,_,_,_=fixed_tree(tmp_path/'resources')
    tree['stores']={'version':1,'street_formats':[23,store,store,store]}
    if policy:
        entry={'node_id':0}
        entry[policy]=[[.3,.4],None] if policy=='locks' else {'targets':[.6,None],'edges':[0.,0.]}
        tree['policies']={'version':1,'nodes':[entry]}
    run(tree,tmp_path/'resources',100,42,tmp_path/'out')
    full=read_node(tmp_path/'out',0)
    partial=read_node(tmp_path/'out',0,bucket_ids=[1])
    assert partial['hands']==[full['hands'][1]]
    assert partial.get('global_average')==full.get('global_average')
    assert partial['display_semantics']==full['display_semantics']
    assert partial['bucket_selection']==[1] and not partial['hands_complete']
    with pytest.raises(ValueError):read_node(tmp_path/'out',0,bucket_ids=[2])
