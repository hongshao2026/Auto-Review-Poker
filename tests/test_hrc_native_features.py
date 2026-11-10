"""Actual training integration for policies, checkpoint v2, CI, and finite FGS."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import runpy
import struct
import subprocess

import pytest

from preflop_lab.hrc_native import ROOT, build, prepare, read_node, run

hu_tree = runpy.run_path(str(ROOT/'tests/test_hrc_kernel.py'))['hu_tree']


def raw_node(path, node_id=0):
    index=json.loads((path/'index.json').read_text())
    n=index['nodes'][node_id]
    with (path/'checkpoint.bin').open('rb') as f:
        f.seek(n['raw_offset'])
        return struct.unpack(f"<{n['raw_count']}d",f.read(8*n['raw_count']))


@pytest.mark.parametrize('mass',[0.,.3,1.])
def test_lock_changes_actual_average_accumulation(tmp_path,mass):
    tree=hu_tree();tree['policies']={'version':1,'nodes':[{'node_id':0,'locks':[[mass]*169,None]}]}
    run(tree,tmp_path,1200,33,tmp_path/'run')
    node=read_node(tmp_path/'run',0);raw=raw_node(tmp_path/'run')
    for hand in node['hands']:
        assert hand['display_strategy']==pytest.approx([mass,1-mass])
        if hand['visits']:
            r=1+5*hand['bucket'];a=raw[r+3:r+5]
            assert a[0]/sum(a)==pytest.approx(mass)
    assert sum(row['visits'] for row in node['hands'])==1200


@pytest.mark.parametrize('mode',['v3','v4'])
def test_frequency_complete_state_resume_equals_continuous(tmp_path,mode):
    tree=hu_tree();tree['policies']={'version':1,'nodes':[{'node_id':0,'frequency':{'targets':[.4,None],'edges':[0,.2]}}]}
    run(tree,tmp_path,2200,42,tmp_path/'direct',mode=mode)
    run(tree,tmp_path,700,42,tmp_path/'partial',mode=mode)
    run(tree,tmp_path,2200,99,tmp_path/'resumed',resume_from=tmp_path/'partial/checkpoint.bin',mode=mode)
    assert (tmp_path/'direct/checkpoint.bin').read_bytes()==(tmp_path/'resumed/checkpoint.bin').read_bytes()
    n=read_node(tmp_path/'direct',0)
    assert n['format']==63 and n['updates']==2200
    assert abs(n['frequency_state']['edge_sums'][0])>0
    assert n['frequency_state']['edge_sums'][1]==.2
    assert len(n['global_average'])==2
    assert all(sum(h['current_strategy'])==1 for h in n['hands'])


def test_historical_v1_checkpoint_can_resume(tmp_path):
    tree=hu_tree();partial=tmp_path/'partial';direct=tmp_path/'direct';resumed=tmp_path/'resumed'
    run(tree,tmp_path,300,42,partial)
    run(tree,tmp_path,700,42,direct)
    data=(partial/'checkpoint.bin').read_bytes();index=json.loads((partial/'index.json').read_text())
    legacy=bytearray(b'HRSOLV01'+data[8:68+2*8])
    for n in index['nodes']:
        legacy.extend(struct.pack('<Q',n['updates']))
        legacy.extend(data[n['visits_offset']:n['raw_offset']+n['raw_count']*8])
    old=tmp_path/'old-v1.bin';old.write_bytes(legacy)
    run(tree,tmp_path,700,0,resumed,resume_from=old)
    assert (resumed/'checkpoint.bin').read_bytes()==(direct/'checkpoint.bin').read_bytes()


@pytest.mark.parametrize('frequency',[False,True])
def test_reset_preserves_rng_and_applies_original_tiny_scaling(tmp_path,frequency):
    tree=hu_tree()
    if frequency:
        tree['policies']={'version':1,'nodes':[{'node_id':0,'frequency':{'targets':[.4,None],'edges':[0,.2]}}]}
    run(tree,tmp_path,300,42,tmp_path/'before')
    before=raw_node(tmp_path/'before')
    result=run(tree,tmp_path,300,42,tmp_path/'after',resume_from=tmp_path/'before/checkpoint.bin',reset_regret=True,reset_average=True)
    after=raw_node(tmp_path/'after');n=read_node(tmp_path/'after',0)
    assert result['summary']['reset_regret'] and result['summary']['reset_average']
    assert n['updates']==0 and all(h['visits']==0 for h in n['hands'])
    assert after[0]==0
    assert after[1:]==pytest.approx([x*1e-20 for x in before[1:]],abs=1e-26)
    assert (tmp_path/'before/checkpoint.bin').read_bytes()[36:68]==(tmp_path/'after/checkpoint.bin').read_bytes()[36:68]


def test_ci_and_frequency_use_integrated_original_math():
    rows={r['id']:r['actual'] for r in map(json.loads,subprocess.check_output([str(build()),'--self-test'],text=True).splitlines())}
    assert rows['ci.integrated_store_flush']==[5000,1,1]
    assert rows['frequency.integrated_raw']==[2,0,0,2,14,3,2.5,.5]
    assert rows['frequency.integrated_strategy']==[0,1]


def test_ci_is_explicit_and_starts_new_history_on_resume(tmp_path):
    tree=hu_tree();tree['ci']={'enabled':True}
    first=run(tree,tmp_path,500,42,tmp_path/'first')
    assert first['summary']['ci']['selected_nodes']==2
    assert first['summary']['ci']['history']==[]
    next_=run(tree,tmp_path,600,42,tmp_path/'next',resume_from=tmp_path/'first/checkpoint.bin')
    assert next_['summary']['ci_restarted'] and next_['summary']['ci']['history']==[]


@pytest.mark.parametrize('options,reason,reached', [({'stop_after_seconds':.1},'time_target',True),
                                                  ({'hard_seconds':.1},'hard_time',False)])
def test_time_targets_stop_actual_training_and_preserve_identity(tmp_path,options,reason,reached):
    tree=hu_tree()
    result=run(tree,tmp_path,1_000_000_000,42,tmp_path/'timed',**options)
    assert result['summary']['stop_reason']==reason
    assert result['summary']['target_reached'] is reached
    assert 0<result['summary']['iteration']<1_000_000_000
    assert .1<=result['summary']['elapsed_seconds']<3
    baseline=prepare(tree,tmp_path/'plain')
    manifest=json.loads((tmp_path/'timed/manifest.json').read_text())
    assert manifest['tree_sha256']==baseline['manifest']['tree_sha256']


def test_ci_target_requires_tracking_and_distinguishes_sample_cap(tmp_path):
    tree=hu_tree()
    with pytest.raises(ValueError,match='explicit'):
        run(tree,tmp_path,100,42,tmp_path/'invalid',target_ci=1)
    tree['ci']={'enabled':True}
    result=run(tree,tmp_path,100,42,tmp_path/'capped',target_ci=1)
    assert result['summary']['stop_reason']=='sample_cap'
    assert result['summary']['target_reached'] is False


def test_ci_target_reached_after_original_poll_interval(tmp_path):
    tree=hu_tree();tree['ci']={'enabled':True}
    result=run(tree,tmp_path,1_000_000_000,42,tmp_path/'ci-goal',target_ci=1e9,hard_seconds=20)
    assert result['summary']['stop_reason']=='ci_target'
    assert result['summary']['target_reached'] is True
    assert result['summary']['ci']['history']
    assert result['summary']['ci']['value']<=1e9


def fgs_tree(tmp_path, *,depth=1,max_states=500,max_seconds=20):
    cache=ROOT/'analysis/hrc-deep/fgs/chance-cache.bin'
    if not cache.exists():
        pytest.skip('Local user-derived FGS chance cache is unavailable')
    resource=ROOT/'analysis/hrc-native/policy-build/fgs-resources';resource.mkdir(exist_ok=True)
    if not (resource/'fgs-chance-v1.bin').exists():
        os.link(cache,resource/'fgs-chance-v1.bin')
    tree=hu_tree();tree['equity']={'mode':'icm','payouts':[70,30],'bounty':{'mode':'none'}}
    tree['fgs']={'big_blind':100,'small_blind':50,'ante':0,'ante_type':'Regular','straddle':'Off','moving_button':False,
                 'depth':depth,'depth3way':depth,'next_level_at':-1,'next_level':[0,0,0],'cache_capacity':5000,
                 'terminal_cache_capacity':65536,'max_states':max_states,'max_sweeps':1000000,'max_seconds':max_seconds,'skip_sb':False}
    return tree,resource


def test_fgs_depth_zero_equals_static_icm_and_finite_depth_runs(tmp_path):
    tree,resources=fgs_tree(tmp_path,depth=0)
    static=copy.deepcopy(tree);static.pop('fgs')
    run(tree,resources,600,42,tmp_path/'fgs0')
    run(static,resources,600,42,tmp_path/'static')
    assert raw_node(tmp_path/'fgs0')==pytest.approx(raw_node(tmp_path/'static'),rel=1e-12,abs=1e-9)
    tree['fgs']['depth']=tree['fgs']['depth3way']=1
    result=run(tree,resources,600,42,tmp_path/'fgs1')
    assert result['summary']['fgs']['states']>0
    assert result['summary']['fgs']['terminal_cache_hits']>0
    assert raw_node(tmp_path/'fgs1')!=raw_node(tmp_path/'fgs0')


def test_fgs_resource_limit_preserves_valid_zero_checkpoint(tmp_path):
    tree,resources=fgs_tree(tmp_path,depth=2,max_states=1)
    output=tmp_path/'limited'
    with pytest.raises(RuntimeError,match='resource budget'):
        run(tree,resources,300,42,output)
    failure=json.loads((output/'failure.json').read_text())
    assert failure['resource_limit']
    index=json.loads((output/'index.json').read_text())
    assert index['samples']==0 and all(n['updates']==0 for n in index['nodes'])


@pytest.mark.parametrize('policy',[
    {'node_id':0,'locks':[[.2]*169,[.2]*169]},
    {'node_id':0,'locks':[[1.]*169,None],'frequency':{}},
    {'node_id':1,'frequency':{}},
    {'node_id':0,'frequency':{'targets':[.8,.8]}},
])
def test_invalid_policy_rejected_before_native_training(tmp_path,policy):
    tree=hu_tree();tree['policies']={'version':1,'nodes':[policy]}
    with pytest.raises(ValueError):
        prepare(tree,tmp_path)
