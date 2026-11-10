"""Production checkpoint migrations against retained original-store evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import runpy
import struct

import pytest

from preflop_lab.hrc_checkpoint import migrate_checkpoint
from preflop_lab.hrc_native import ROOT, prepare, read_node, run

hu_tree=runpy.run_path(str(ROOT/'tests/test_hrc_kernel.py'))['hu_tree']
raw_node=runpy.run_path(str(ROOT/'tests/test_hrc_native_features.py'))['raw_node']


def source_fixture(folder, fmt, raw, *, frequency=None,buckets=2):
    """Encode arbitrary audited original numeric state as a native checkpoint."""
    tree=hu_tree();street=0 if fmt==23 else 1
    tree['stores']={'version':1,'street_formats':[23,fmt if street else 25,25,25]}
    for n in tree['nodes']:
        if n['children']:n.update(street=street,buckets=buckets)
    if frequency:
        tree['policies']={'version':1,'nodes':[{'node_id':0,'frequency':{'targets':frequency['targets'],'edges':frequency['edges']}}]}
    prepared=prepare(tree,folder)
    identity=int.from_bytes(hashlib.sha256(json.dumps(tree,sort_keys=True,separators=(',',':')).encode()).digest()[:8],'little')
    data=bytearray(struct.pack('<8sQQIII4Q2d',b'HRSOLV03',identity,123,5,2,1,1,2,3,4,.4,-.4));nodes=[]
    for n in tree['nodes']:
        k=len(n['children']);h=n['buckets'];f=(63 if frequency and n['id']==0 else fmt) if k else 0
        count=0 if not k else 1+h*(2*k+1) if f==23 else 1+(h+1)*k if f==25 else 1+k+h*(2*k if f==27 else 2*k+1)
        values=raw if n['id']==0 else [0.]*count
        updates=(frequency['updates'] if frequency else math.floor(raw[0]+.5)) if n['id']==0 else 0
        data.extend(struct.pack('<QI',updates,f));visits=len(data);data.extend(struct.pack(f'<{h}Q',*([0]*h)));offset=len(data)
        data.extend(struct.pack(f'<{len(values)}d',*values))
        index=dict(id=n['id'],actor=n['actor'],street=n['street'],buckets=h,actions=k,updates=updates,
                   visits_offset=visits,raw_offset=offset,raw_count=count,format=f)
        if f==63:
            index['frequency_state_offset']=len(data);index['targets']=frequency['targets']
            extra=[frequency['minimum'],frequency['maximum'],*frequency['edges'],*frequency['edge_sums'],*frequency['shared_sums'],
                   *(math.nan if t is None else t for t in frequency['targets'])]
            data.extend(struct.pack(f'<{len(extra)}d',*extra))
        elif f==31:
            index['shared_state_offset']=len(data);data.extend(struct.pack(f'<{k}d',*values[1:1+k]))
        nodes.append(index)
    (folder/'checkpoint.bin').write_bytes(data)
    (folder/'index.json').write_text(json.dumps({'version':3,'samples':123,'nodes':nodes}))
    return tree,nodes


def migrated_root(path, fmt, h=2,k=2):
    data=path.read_bytes();updates,actual=struct.unpack_from('<QI',data,84)
    assert data[:8]==b'HRSOLV03' and actual==fmt
    count=1+h*(2*k+1) if fmt==23 else 1+(h+1)*k if fmt==25 else 1+k+h*(2*k if fmt==27 else 2*k+1)
    raw=list(struct.unpack_from(f'<{count}d',data,84+12+8*h));extra=[]
    if fmt==63:extra=list(struct.unpack_from(f'<{2+4*k}d',data,84+12+8*h+8*count))
    elif fmt==31:extra=list(struct.unpack_from(f'<{k}d',data,84+12+8*h+8*count))
    return updates,raw,extra


def original_cases():
    return [row for row in map(json.loads,(ROOT/'analysis/hrc-deep/store-migration/original.jsonl').read_text().splitlines())
            if row['kind']=='case' and row['actions']==2]


@pytest.mark.parametrize('case',original_cases(),ids=lambda c:str(c['format']))
def test_original_enable_frequency_migration(tmp_path,case):
    tree,_=source_fixture(tmp_path/'source',case['format'],case['initial'])
    tree['policies']={'version':1,'nodes':[{'node_id':0,'frequency':{'targets':[.4,None],'edges':[0.,.75]}}]}
    path,_=migrate_checkpoint(tmp_path/'source/checkpoint.bin',tree,tmp_path/'target','reset','v4')
    count,raw,extra=migrated_root(path,63);original=case['enabled']
    assert count==original['updates']
    assert raw==original['raw'] and extra[:2]==[original['minimum'],original['maximum']]
    assert extra[2:4]==original['edges'] and extra[4:6]==original['edge_sums'] and extra[6:8]==original['shared_sums']
    assert extra[8]==original['targets'][0] and math.isnan(extra[9])


@pytest.mark.parametrize('case',[c for c in original_cases() if c['format'] in (23,31)],ids=lambda c:str(c['format']))
def test_original_disable_frequency_migration(tmp_path,case):
    original=copy.deepcopy(case['edited']);original['targets']=[None if t=='NaN' else t for t in original['targets']]
    tree,_=source_fixture(tmp_path/'source',case['format'],original['raw'],frequency=original)
    tree.pop('policies')
    path,_=migrate_checkpoint(tmp_path/'source/checkpoint.bin',tree,tmp_path/'target','preserve','v4')
    _,raw,_=migrated_root(path,case['format'])
    assert raw==case['restored_raw']


@pytest.mark.parametrize('case',original_cases(),ids=lambda c:str(c['format']))
def test_original_existing_target_edit_flushes_stale_state(tmp_path,case):
    original=copy.deepcopy(case['updated']);original['targets']=[None if t=='NaN' else t for t in original['targets']]
    tree,_=source_fixture(tmp_path/'source',case['format'],original['raw'],frequency=original)
    tree['policies']['nodes'][0]['frequency']={'targets':[.65,None],'edges':[0.,-.25]}
    path,_=migrate_checkpoint(tmp_path/'source/checkpoint.bin',tree,tmp_path/'target','preserve','v4')
    count,raw,extra=migrated_root(path,63);expected=case['edited']
    assert count==expected['updates'] and raw==expected['raw']
    assert extra[2:4]==expected['edges'] and extra[4:6]==expected['edge_sums']
    assert extra[6:8]==expected['shared_sums'] and extra[8]==.65


def test_original_25_to_27_conversion_seeds_exact_bucket_averages(tmp_path):
    records=map(json.loads,(ROOT/'analysis/hrc-deep/extended-store/original.jsonl').read_text().splitlines())
    case=next(r for r in records if r.get('id')=='convert25_k2')
    before,after=case['snapshots'][:2]
    raw=before['header']+[x for row in before['rows'] for x in row]
    tree,_=source_fixture(tmp_path/'source',25,raw,buckets=3)
    tree['stores']['street_formats'][1]=27
    path,report=migrate_checkpoint(tmp_path/'source/checkpoint.bin',tree,tmp_path/'target','preserve','v3')
    updates,converted,_=migrated_root(path,27,h=3)
    assert updates==after['counter']
    assert converted==after['header']+[x for row in after['rows'] for x in row]
    assert report['solver_mode_changed']


def test_unproven_store_preservation_rejected_and_explicit_reset_available(tmp_path):
    tree,_=source_fixture(tmp_path/'source',25,[10.,3.,4.,1.,-2.,3.,4.])
    tree['stores']['street_formats'][1]=31
    with pytest.raises(ValueError,match='Cannot preserve'):
        migrate_checkpoint(tmp_path/'source/checkpoint.bin',tree,tmp_path/'bad','preserve','v4')
    path,report=migrate_checkpoint(tmp_path/'source/checkpoint.bin',tree,tmp_path/'target','reset','v4')
    updates,raw,shared=migrated_root(path,31)
    assert updates==0 and not any(raw+shared)
    assert report['changed_nodes'][0]['counter_reset']


def test_actual_lock_migration_preserves_source_and_learning(tmp_path):
    tree=hu_tree();source=tmp_path/'source';run(tree,tmp_path,700,42,source)
    originals={p.name:p.read_bytes() for p in source.iterdir() if p.is_file()}
    tree['policies']={'version':1,'nodes':[{'node_id':0,'locks':[[.3]*169,None]}]}
    result=run(tree,tmp_path,700,99,tmp_path/'locked',resume_from=source/'checkpoint.bin',checkpoint_migration='preserve')
    assert raw_node(source)==raw_node(tmp_path/'locked')
    assert all(h['display_strategy']==pytest.approx([.3,.7]) for h in read_node(tmp_path/'locked',0)['hands'])
    assert result['summary']['migration']['rng_preserved']
    assert all((source/name).read_bytes()==data for name,data in originals.items())
    run(tree,tmp_path,900,99,tmp_path/'continued',resume_from=tmp_path/'locked/checkpoint.bin')
    assert read_node(tmp_path/'continued',0)['updates']==900


def test_frequency_enable_requires_explicit_reset_and_retains_quantized_targets(tmp_path):
    tree=hu_tree();run(tree,tmp_path,500,42,tmp_path/'source')
    tree['policies']={'version':1,'nodes':[{'node_id':0,'frequency':{'targets':[.4,None],'edges':[0.,.2]}}]}
    with pytest.raises(ValueError,match='Cannot preserve'):
        run(tree,tmp_path,500,42,tmp_path/'bad',resume_from=tmp_path/'source/checkpoint.bin',checkpoint_migration='preserve')
    run(tree,tmp_path,500,42,tmp_path/'migrated',resume_from=tmp_path/'source/checkpoint.bin',checkpoint_migration='reset')
    n=read_node(tmp_path/'migrated',0)
    assert n['updates']==0 and n['targets'][0]==struct.unpack('<f',struct.pack('<f',.4))[0]
    run(tree,tmp_path,700,42,tmp_path/'resumed',resume_from=tmp_path/'migrated/checkpoint.bin')
    assert read_node(tmp_path/'resumed',0)['targets']==n['targets']


@pytest.mark.parametrize('fmt',[27,31])
def test_postflop_formats_resume_and_actual_lock_accumulation(tmp_path,fmt):
    resources=ROOT/'.research-cache/abstractions'
    if not resources.exists():pytest.skip('Local abstraction resources unavailable')
    tree=hu_tree()
    for n in tree['nodes']:
        if n['children']:n.update(street=1,buckets=1024)
    tree['stores']={'version':1,'street_formats':[23,fmt,25,25]}
    tree['policies']={'version':1,'nodes':[{'node_id':0,'locks':[[.3]*1024,None]}]}
    run(tree,resources,500,42,tmp_path/'direct')
    run(tree,resources,200,42,tmp_path/'partial')
    run(tree,resources,500,99,tmp_path/'resumed',resume_from=tmp_path/'partial/checkpoint.bin')
    assert (tmp_path/'direct/checkpoint.bin').read_bytes()==(tmp_path/'resumed/checkpoint.bin').read_bytes()
    node=read_node(tmp_path/'direct',0);raw=raw_node(tmp_path/'direct')
    for h in node['hands']:
        if h['visits']:
            offset=3+(4 if fmt==27 else 5)*h['bucket']+2+int(fmt==31)
            assert raw[offset]/sum(raw[offset:offset+2])==pytest.approx(.3)
            assert (h['relative_ev_to_action0'] is not None)==(fmt==31)


def test_migration_cannot_change_game_or_overwrite_source(tmp_path):
    tree=hu_tree();run(tree,tmp_path,10,42,tmp_path/'source')
    original=(tmp_path/'source/tree.json').read_bytes()
    with pytest.raises(ValueError,match='new output directory'):
        run(tree,tmp_path,10,42,tmp_path/'source',resume_from=tmp_path/'source/checkpoint.bin',checkpoint_migration='reset')
    changed=copy.deepcopy(tree);changed['initial_stacks'][0]+=1
    with pytest.raises(ValueError,match='source metadata was preserved'):
        run(changed,tmp_path,10,42,tmp_path/'source',resume_from=tmp_path/'source/checkpoint.bin')
    assert (tmp_path/'source/tree.json').read_bytes()==original
    with pytest.raises(ValueError,match='cannot change topology'):
        migrate_checkpoint(tmp_path/'source/checkpoint.bin',changed,tmp_path/'bad','reset','v4')


def test_v2_frequency_checkpoint_is_read_compatibly(tmp_path):
    tree=hu_tree();tree['policies']={'version':1,'nodes':[{'node_id':0,'frequency':{'targets':[.4,None],'edges':[0.,.2]}}]}
    run(tree,tmp_path,300,42,tmp_path/'first');run(tree,tmp_path,500,42,tmp_path/'direct')
    data=(tmp_path/'first/checkpoint.bin').read_bytes();index=json.loads((tmp_path/'first/index.json').read_text())
    legacy=bytearray(b'HRSOLV02'+data[8:84])
    for n in index['nodes']:
        start=n['visits_offset']-12;end=n['raw_offset']+8*n['raw_count']
        if n['format']==63:end+=8*(2+3*n['actions'])
        legacy.extend(data[start:end])
    old=tmp_path/'old2.bin';old.write_bytes(legacy)
    run(tree,tmp_path,500,99,tmp_path/'resumed',resume_from=old)
    assert (tmp_path/'direct/checkpoint.bin').read_bytes()==(tmp_path/'resumed/checkpoint.bin').read_bytes()
