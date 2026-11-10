"""Real shared-policy traversal, coherent checkpoints and worker RNG validation."""
import copy
import json
import math
import struct

import pytest

from preflop_lab.hrc_native import run, read_node
from preflop_lab.hrc_parallel import validate_trailer
from preflop_lab.hrc_archive import _validate_checkpoint
from test_hrc_kernel import hu_tree
from test_hrc_native_dynamic import fixed_tree
from test_hrc_native_features import fgs_tree
from test_hrc_native_rake import rake_tree
from test_hrc_tournament_native import model


def validate(path,tree,threads,samples):
    index=json.loads((path/'index.json').read_text())
    assert index['training_threads']==threads
    assert index['samples']==samples
    assert _validate_checkpoint(path,tree)==samples
    root=read_node(path,0)
    assert root['updates']==samples
    assert sum(h['visits'] for h in root['hands'])==samples
    for node in index['nodes']:
        data=read_node(path,node['id'])
        for hand in data['hands']:
            assert all(math.isfinite(p) and p>=0 for p in hand['display_strategy'])
            assert sum(hand['display_strategy'])==pytest.approx(1.)
    return root


@pytest.mark.parametrize('threads',[2,4,8])
@pytest.mark.parametrize('mode',['v3','v4'])
def test_parallel_updates_are_not_lost_and_resume_can_change_threads(tmp_path,threads,mode):
    tree=hu_tree();first=tmp_path/'first'
    result=run(tree,tmp_path,2003,43,first,threads=threads,mode=mode)
    assert result['summary']['parallel_mode']=='async_shared'
    validate(first,tree,threads,2003)
    before=(first/'checkpoint.bin').read_bytes()
    unchanged=tmp_path/'unchanged'
    run(tree,tmp_path,2003,99,unchanged,threads=threads,mode=mode,resume_from=first/'checkpoint.bin')
    assert (unchanged/'checkpoint.bin').read_bytes()==before
    for target_threads in (1,threads,3):
        path=tmp_path/f'next{target_threads}'
        run(tree,tmp_path,3007,99,path,threads=target_threads,resume_from=first/'checkpoint.bin',mode=mode)
        validate(path,tree,target_threads,3007)
    assert (first/'checkpoint.bin').read_bytes()==before


@pytest.mark.parametrize('kind',['icm','mtt','ko','pko','locks','frequency','rake'])
def test_models_and_constraints_use_shared_training(tmp_path,kind):
    tree=rake_tree() if kind=='rake' else hu_tree()
    if kind in ('icm','mtt','ko','pko'):
        tree['equity']=model(kind if kind in ('ko','pko') else 'none',kind=='mtt')
    if kind in ('locks','frequency'):
        entry={'node_id':0}
        entry[kind]=[[.3]*169,None] if kind=='locks' else {'targets':[.4,None],'edges':[0.,.2]}
        tree['policies']={'version':1,'nodes':[entry]}
    output=tmp_path/'run'
    run(tree,tmp_path,3000,43,output,threads=4)
    root=validate(output,tree,4,3000)
    if kind=='locks':assert all(h['display_strategy']==pytest.approx([.3,.7]) for h in root['hands'])


def test_parallel_fixed_board_private_deals_and_shared_dynamic_map(tmp_path):
    tree,_,_,_=fixed_tree(tmp_path/'resources',players=3)
    output=tmp_path/'run'
    run(tree,tmp_path/'resources',2000,43,output,threads=4)
    validate(output,tree,4,2000)


def test_parallel_fgs_uses_private_mutable_caches(tmp_path):
    tree,resources=fgs_tree(tmp_path,depth=1,max_seconds=60)
    output=tmp_path/'run';result=run(tree,resources,200,43,output,threads=2)
    validate(output,tree,2,200)
    assert result['summary']['fgs']['states']>0


def test_cancel_and_resource_limit_leave_valid_boundary_checkpoint(tmp_path):
    tree=hu_tree();output=tmp_path/'cancel'
    result=run(tree,tmp_path,1_000_000,43,output,threads=4,cancel_check=lambda:True)
    assert result['summary']['cancelled']
    validate(output,tree,4,result['summary']['iteration'])
    with pytest.raises(RuntimeError,match='memory budget'):
        run(tree,tmp_path,1000,43,tmp_path/'limited',threads=8,max_memory_bytes=1<<20)
    assert _validate_checkpoint(tmp_path/'limited',tree)==0


@pytest.mark.parametrize('value',[0,33,True,1.5,'4'])
def test_invalid_thread_controls_rejected_before_output(tmp_path,value):
    with pytest.raises(ValueError,match='threads'):run(hu_tree(),tmp_path,100,43,tmp_path/'bad',threads=value)
    assert not (tmp_path/'bad').exists()


def test_trailer_checks_length_primary_and_stream_uniqueness():
    states=[(1,2,3,4),(5,6,7,8)]
    good=b'HRPAR001'+struct.pack('<I',2)+b''.join(struct.pack('<4Q',*s) for s in states)
    assert validate_trailer(good,states[0],expected_threads=2)==2
    for malformed in (good[:-1],good+b'x',good[:12]+good[12:44]*2):
        with pytest.raises(ValueError):validate_trailer(malformed,states[0])
    with pytest.raises(ValueError):validate_trailer(good,states[1])
    with pytest.raises(ValueError):validate_trailer(good,states[0],expected_threads=4)
