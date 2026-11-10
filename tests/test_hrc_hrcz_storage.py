"""Binary losslessness and actual native continuation after float32 HRC import."""
from array import array
from copy import deepcopy
import hashlib
import json
import math
import runpy
import struct
import zipfile

import pytest

from preflop_lab import hrc_hrcz_storage as codec
from preflop_lab.hrc_native import ROOT,read_node,run

hu_tree=runpy.run_path(str(ROOT/'tests/test_hrc_kernel.py'))['hu_tree']
fixed_tree=runpy.run_path(str(ROOT/'tests/test_hrc_native_dynamic.py'))['fixed_tree']


def decision(fmt,h=3,k=2,*,counter=60000501.,locks=False,base=23):
    raw=array('f',[(i%11-5)*.125 for i in range(codec.raw_count(fmt,h,k))]);raw[0]=counter
    if fmt in (23,31,63):
        for b in range(h):raw[codec.raw_offset(fmt,b,k)+k]=3.+b
    record={'id':0,'format_id':fmt,'action_count':k,'bucket_or_vector_count':h,'raw':raw,'locks':{},'reserved':(0,0)}
    if locks:record['locks']={0:array('f',[.4]*h)}
    if fmt==63:record['frequency']={'targets':array('f',[.4]+[math.nan]*(k-1)),
                                  'minimum':.125,'maximum':25.,'edges':array('f',[0.]+[.75]*(k-1)),'underlying_format':base}
    return record


@pytest.mark.parametrize('fmt',[23,25,27,31,63])
@pytest.mark.parametrize('h,k',[(1,2),(3,4),(4097,2)])
def test_all_current_formats_exact_binary_roundtrip(fmt,h,k):
    record=decision(fmt,h,k,locks=fmt in (23,27,31))
    payload=codec.encode_payload(record)
    restored=codec.decode_payload(0,fmt,h,len(record['locks']),payload,k)
    assert codec.encode_payload(restored)==payload
    encoded,offsets=codec.encode_nodedata({0:restored})
    actual,actual_offsets=codec.decode_nodedata(encoded,{0:k})
    assert offsets==actual_offsets and codec.encode_nodedata(actual)[0]==encoded


@pytest.mark.parametrize('filename',['hu10bb-pushfold-initial.hrcz','eight15bb-raise-call-postflop-60m.hrcz','eight15bb-pko-50-30-20-initial.hrcz'])
def test_real_original_archives_nodedata_roundtrip(filename):
    path=ROOT/'analysis/hrc-desktop'/filename
    if not path.is_file():pytest.skip('Local original fixture unavailable')
    inspect=runpy.run_path(str(ROOT/'scripts/inspect-hrc-save.py'))
    with zipfile.ZipFile(path) as archive:
        nodes,_=inspect['parse_tree'](archive.read('gametree.dat'));data=archive.read('nodedata.dat')
    counts={i:len(node['child_ids']) for i,node in nodes.items()}
    records,offsets=codec.decode_nodedata(data,counts)
    assert codec.encode_nodedata(records)[0]==data


def imported(tree,records,path,scale=100.,offsets=None,seed=42):
    for node in tree['nodes']:
        if not node['children'] and node['id'] in records:
            record=records[node['id']];count=3**(sum(not f for f in tree['terminals'][node['terminal_id']]['folded'])-1)
            if record['bucket_or_vector_count']==1 and count>1:
                records[node['id']]=codec.leaf_record(node['id'],[list(record['vectors'][0])]*count)
    offsets=offsets or [1000.]*tree['players']
    cfg=codec.storage_configuration(records,tree,utility_scale=scale,utility_offsets=offsets)
    assert cfg['trainable'],cfg['reasons']
    tree=deepcopy(tree);tree['stores']=cfg['stores'];tree['policies']=cfg['policies']
    tree['import_provenance']={'format':'hrcz','source_sha256':'a'*64,'saved_update_counters':cfg['saved_update_counters']}
    result=codec.records_to_checkpoint(records,tree,path,seed=seed,utility_scale=scale,utility_offsets=offsets)
    return tree,result


@pytest.mark.parametrize('fmt,base',[(23,23),(25,25),(27,27),(31,31),(63,23),(63,31)])
def test_import_keeps_clock_and_continue_split_exact(tmp_path,fmt,base):
    if base==23:tree=hu_tree();resources=tmp_path
    else:tree,_,_,_=fixed_tree(tmp_path/'resources');resources=tmp_path/'resources'
    records={};leaves={}
    for node in tree['nodes']:
        i=node['id'];k=len(node['children'])
        if k:
            records[i]=decision(fmt,node['buckets'],k,counter=10002.5,base=base);records[i]['id']=i
        else:records[i]=leaves[i]=codec.leaf_record(i,[[1000.,1000.]])
    tree,result=imported(tree,records,tmp_path/'imported')
    before=json.loads((tmp_path/'imported/index.json').read_text());root=before['nodes'][0]
    assert root['updates']==10003 and root['saved_counter_float32']==10002.5
    run(tree,resources,300,99,tmp_path/'direct',resume_from=result['checkpoint_path'])
    run(tree,resources,100,999,tmp_path/'partial',resume_from=result['checkpoint_path'])
    run(tree,resources,300,7,tmp_path/'resumed',resume_from=tmp_path/'partial/checkpoint.bin')
    assert (tmp_path/'direct/checkpoint.bin').read_bytes()==(tmp_path/'resumed/checkpoint.bin').read_bytes()
    node=read_node(tmp_path/'direct',0);visits=sum(r['visits'] for r in node['hands'])
    assert visits==300 and node['updates']==10303 and node['imported_updates_baseline']==10003
    assert node['history_unknown']
    history=json.loads((tmp_path/'imported/import-history.json').read_text())
    assert history['source_per_bucket_visits'] is None and history['source_rng_state'] is None
    assert history['source_iterations'] is None and history['new_seed']==42
    assert json.loads((tmp_path/'direct/index.json').read_text())['utility_baseline']==[10.,10.]


@pytest.mark.parametrize('fmt,base',[(23,23),(25,25),(27,27),(31,31),(63,23),(63,31)])
def test_native_export_flush_units_and_reimport(tmp_path,fmt,base):
    if base==23:tree=hu_tree();resources=tmp_path
    else:tree,_,_,_=fixed_tree(tmp_path/'resources');resources=tmp_path/'resources'
    tree['stores']={'version':1,'street_formats':[23,base if base!=23 else 25,base if base!=23 else 25,base if base!=23 else 25]}
    if fmt==63:tree['policies']={'version':1,'nodes':[{'node_id':n['id'],'frequency':{'targets':[.4,None],'edges':[0.,.1]}} for n in tree['nodes'] if n['children']]}
    run(tree,resources,125,42,tmp_path/'trained')
    leaves={n['id']:codec.leaf_record(n['id'],[[950.,1050.]]*3**(sum(not f for f in tree['terminals'][n['terminal_id']]['folded'])-1)) for n in tree['nodes'] if not n['children']}
    records,report=codec.checkpoint_to_records(tmp_path/'trained',utility_scale=100,utility_offsets=[1000,1000],leaf_records=leaves)
    payload,_=codec.encode_nodedata(records);decoded,_=codec.decode_nodedata(payload,{n['id']:len(n['children']) for n in tree['nodes']})
    configured,converted=imported(tree,decoded,tmp_path/'reimported')
    after=read_node(tmp_path/'reimported',0);before=read_node(tmp_path/'trained',0)
    for old,new in zip(before['hands'],after['hands']):
        assert new['display_strategy']==pytest.approx(old['display_strategy'],abs=2e-7)
        if old['relative_ev_to_action0'] is not None:
            assert new['relative_ev_to_action0']==pytest.approx(old['relative_ev_to_action0'],rel=2e-6,abs=2e-6)
    assert report['float32_quantization'] and not report['rng_or_visits_written_to_hrc']


def test_unknown_formats_preserve_payload_but_refuse_training(tmp_path):
    record=decision(23,169);record['format_id']=777;record.pop('raw');record['opaque_payload']=b'unknown123'
    data,_=codec.encode_nodedata({0:record})
    decoded,_=codec.decode_nodedata(data,{0:2})
    assert codec.encode_nodedata(decoded)[0]==data
    assert not codec.storage_configuration(decoded,hu_tree())['trainable']


def test_mixed_same_street_formats_are_explicit_read_only(tmp_path):
    tree,_,_,_=fixed_tree(tmp_path/'resources')
    records={n['id']:decision(25 if n['id']==0 else 31,n['buckets']) if n['children'] else codec.leaf_record(n['id'],[[1000.,1000.]]) for n in tree['nodes']}
    result=codec.storage_configuration(records,tree)
    assert not result['trainable'] and any('mixed per-node' in reason for reason in result['reasons'])


@pytest.mark.parametrize('counter',[math.nan,math.inf,-1.])
def test_nonfinite_or_negative_import_clock_cannot_train(counter):
    record=decision(23,169,counter=counter)
    cfg=codec.storage_configuration({0:record},hu_tree())
    assert not cfg['trainable']


def test_leaf_codec_requires_rectangular_absolute_vectors():
    record=codec.leaf_record(1,[[950.,1050.],[1000.,1000.],[1050.,950.]])
    payload=codec.encode_payload(record)
    restored=codec.decode_payload(1,1024,3,0,payload,0)
    assert restored['vectors']==record['vectors']
    with pytest.raises(ValueError):codec.leaf_record(0,[[1,2],[3]])


@pytest.mark.parametrize('values',[(.1,.9),(.4,.6)])
def test_imported_full_locks_follow_original_load_sequence(tmp_path,values):
    tree=hu_tree();records={}
    for node in tree['nodes']:
        i=node['id']
        if node['children']:
            records[i]=decision(23,169)
            records[i]['locks']={a:array('f',[value]*169) for a,value in enumerate(values)}
        else:records[i]=codec.leaf_record(i,[[1000.,1000.]])
    tree,result=imported(tree,records,tmp_path/'imported')
    expected=[row[0] for row in codec.runtime_locks(records[0])]
    run(tree,tmp_path,10,42,tmp_path/'run',resume_from=result['checkpoint_path'])
    assert all(row['display_strategy']==expected for row in read_node(tmp_path/'run',0)['hands'])
    if values==(.4,.6):assert expected[0]!=records[0]['locks'][0][0]
    else:assert sum(expected)<1


def test_imported_frequency_targets_keep_float32_residual(tmp_path):
    tree=hu_tree();records={}
    for node in tree['nodes']:
        i=node['id']
        if node['children']:
            records[i]=decision(63,169)
            records[i]['frequency']['targets']=array('f',[.4,.6])
        else:records[i]=codec.leaf_record(i,[[1000.,1000.]])
    tree,result=imported(tree,records,tmp_path/'imported')
    run(tree,tmp_path,10,42,tmp_path/'run',resume_from=result['checkpoint_path'])
    assert sum(read_node(tmp_path/'run',0)['targets'])>1
