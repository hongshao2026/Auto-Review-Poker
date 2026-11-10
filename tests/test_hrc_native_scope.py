"""Selected preflop scope affects real traversal, stores, counters and CI."""
from copy import deepcopy
import json
from pathlib import Path
import runpy
import struct

import pytest

from preflop_lab.hrc_native import ROOT,run,read_node

hu_tree=runpy.run_path(str(ROOT/'tests/test_hrc_kernel.py'))['hu_tree']


def reentry_tree():
    tree=hu_tree()
    tree['nodes'][4]={'id':4,'actor':0,'street':0,'buckets':169,'children':[5,6],
                      'actions':[0,2],'terminal_id':-1}
    tree['nodes'] += [{'id':5,'actor':-1,'street':0,'buckets':0,'children':[],'actions':[],'terminal_id':3},
                      {'id':6,'actor':-1,'street':0,'buckets':0,'children':[],'actions':[],'terminal_id':2}]
    tree['terminals'].append({'remaining':[0,0],'contributions':[1000,1000],'folded':[True,False]})
    # AA at HRC index168 has zero own prefix reach. It must still receive
    # counterfactual regret updates when seat0 is the mode2 target.
    folds=[0.]*169;folds[168]=1.
    tree['policies']={'version':1,'nodes':[{'node_id':0,'locks':[folds,None]},
                                         {'node_id':2,'locks':[[0.]*169,None]}]}
    return tree


def state_bytes(folder,node):
    index=json.loads((folder/'index.json').read_text());meta=index['nodes'][node]
    end=index['nodes'][node+1]['visits_offset']-12 if node+1<len(index['nodes']) else None
    data=(folder/'checkpoint.bin').read_bytes()
    return data[meta['visits_offset']-12:end]


def selected(tree,resources,samples,seed,output,**kwargs):
    return run(tree,resources,samples,seed,output,sampling_scope='selected_subtree',sampling_path=[1],**kwargs)


@pytest.mark.parametrize('threads',[1,3])
def test_mode2_actual_counterfactual_zero_reach_hand_and_outside_freeze(tmp_path,threads):
    tree=reentry_tree();source=tmp_path/'source';out=tmp_path/'scope'
    run(tree,tmp_path,400,11,source,mode='v3')
    before=read_node(source,4)['hands'][168]['visits']
    result=selected(tree,tmp_path,5400,99,out,resume_from=source/'checkpoint.bin',mode='v3',threads=threads)
    index=json.loads((out/'index.json').read_text())
    assert index['sampling_mode']==2 and index['sampling_targets']==[1,0]
    assert index['scope_effective_samples']==5000
    assert index['sampling_deals']==10000 and index['sampling_attempts']>=10000
    assert index['samples']==5400 and result['summary']['iteration']==5400
    assert read_node(out,4)['hands'][168]['visits']>before
    assert state_bytes(source,0)==state_bytes(out,0)
    assert state_bytes(source,1)==state_bytes(out,1)
    assert index['root_mean_valid'] is False and index['root_mean_net_bb'] is None


def test_mode1_for_uniform_active_ranges_with_nonuniform_opponent(tmp_path):
    tree=hu_tree();folds=[0.]*169;folds[168]=1.
    tree['policies']={'version':1,'nodes':[{'node_id':0,'locks':[folds,None]}]}
    result=selected(tree,tmp_path,300,42,tmp_path/'mode1')
    index=json.loads((tmp_path/'mode1/index.json').read_text())
    assert index['sampling_mode']==1 and index['sampling_targets']==[1]
    assert index['sampling_deals']==index['scope_effective_samples']==300
    assert index['nodes'][0]['updates']==0 and index['nodes'][2]['updates']==300


def test_scope_single_thread_resume_is_exact_and_full_tree_mean_remains_invalid(tmp_path):
    tree=reentry_tree();direct,part,resumed,full=(tmp_path/p for p in ('direct','part','resume','full'))
    selected(tree,tmp_path,600,72,direct,mode='v4')
    selected(tree,tmp_path,200,72,part,mode='v4')
    selected(tree,tmp_path,600,999,resumed,resume_from=part/'checkpoint.bin',mode='v4')
    assert (direct/'checkpoint.bin').read_bytes()==(resumed/'checkpoint.bin').read_bytes()
    run(tree,tmp_path,700,999,full,resume_from=resumed/'checkpoint.bin')
    final=json.loads((full/'index.json').read_text())
    assert final['root_mean_valid'] is False and final['root_mean_net_bb'] is None
    assert final['nodes'][0]['updates']>0 and final['sampling_scope']=='entire_tree'


def test_ci_snapshot_and_reset_touch_only_selected_subtree(tmp_path):
    tree=reentry_tree();source=tmp_path/'source';out=tmp_path/'selected'
    run(tree,tmp_path,500,12,source)
    selected(tree,tmp_path,500,99,out,resume_from=source/'checkpoint.bin',track_ci=True,
             reset_regret=True,reset_average=True)
    index=json.loads((out/'index.json').read_text())
    assert index['ci']['selected_nodes']==2 and index['ci']['root_node_id']==2
    assert index['ci']['value'] is None
    assert state_bytes(source,0)==state_bytes(out,0)  # even cached raw0 unchanged
    assert state_bytes(source,1)==state_bytes(out,1)
    assert index['nodes'][2]['updates']==index['nodes'][4]['updates']==0


def test_unreachable_prefix_rejected_without_replacing_saved_state(tmp_path):
    tree=hu_tree();tree['policies']={'version':1,'nodes':[{'node_id':0,'locks':[[1.]*169,None]}]}
    run(tree,tmp_path,0,1,tmp_path/'source')
    before=(tmp_path/'source/checkpoint.bin').read_bytes()
    with pytest.raises(RuntimeError,match='unreachable'):
        selected(tree,tmp_path,100,2,tmp_path/'bad',resume_from=tmp_path/'source/checkpoint.bin')
    assert (tmp_path/'source/checkpoint.bin').read_bytes()==before
    assert not (tmp_path/'bad/checkpoint.bin').exists()


def test_selected_root_matches_unselected_raw_trajectory(tmp_path):
    tree=hu_tree()
    run(tree,tmp_path,300,19,tmp_path/'full')
    run(tree,tmp_path,300,19,tmp_path/'root',sampling_scope='selected_subtree',sampling_path=[])
    # The selected-root mode0 consumes no extra random numbers; only root mean
    # accounting differs because selected scopes deliberately suppress it.
    a=(tmp_path/'full/checkpoint.bin').read_bytes();b=(tmp_path/'root/checkpoint.bin').read_bytes()
    assert a[:68]==b[:68] and a[84:]==b[84:]


def test_jointly_impossible_nonempty_prefix_ranges_are_rejected(tmp_path):
    # Three seats independently demand AA, impossible with four aces even
    # though every marginal range is nonempty. The selected actor is seat3.
    tree={'root':0,'players':4,'big_blind':100,'initial_stacks':[1000]*4,'nodes':[],'terminals':[]}
    for i in range(4):
        tree['nodes'].append({'id':2*i,'actor':i,'street':0,'buckets':169,'children':[2*i+1,2*i+2], 'actions':[0,3],'terminal_id':-1})
        tree['nodes'].append({'id':2*i+1,'actor':-1,'street':0,'buckets':0,'children':[],'actions':[],'terminal_id':i})
        tree['terminals'].append({'remaining':[1000]*4,'contributions':[0]*4,'folded':[False]*4})
    tree['nodes'].append({'id':8,'actor':-1,'street':0,'buckets':0,'children':[],'actions':[],'terminal_id':4})
    tree['terminals'].append(deepcopy(tree['terminals'][0]))
    q=[1.]*169;q[168]=0
    tree['policies']={'version':1,'nodes':[{'node_id':2*i,'locks':[q,None]} for i in range(3)]}
    with pytest.raises(RuntimeError,match='no collision-free joint deal'):
        run(tree,tmp_path,10,1,tmp_path/'impossible',sampling_scope='selected_subtree',sampling_path=[1,1,1])


def test_cancelled_mode2_keeps_complete_boundary_checkpoint(tmp_path):
    tree=reentry_tree();source=tmp_path/'source';out=tmp_path/'cancelled'
    run(tree,tmp_path,100,8,source)
    result=selected(tree,tmp_path,1_000_000_000,3,out,resume_from=source/'checkpoint.bin',cancel_check=lambda:True)
    assert result['summary']['cancelled']
    index=json.loads((out/'index.json').read_text())
    assert index['samples']==result['summary']['iteration']
    assert state_bytes(source,0)==state_bytes(out,0)
    assert index['root_mean_net_bb'] is None
