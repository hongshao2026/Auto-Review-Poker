"""End-to-end independently generated archive terminal vectors and baselines."""
from copy import deepcopy
import runpy

import pytest

from preflop_lab.hrc_native import ROOT
from preflop_lab.hrc_hrcz_leaves import generate_leaves,evaluate_baseline
from preflop_lab.hrc_hrcz_storage import terminal_rank_patterns

hu_tree=runpy.run_path(str(ROOT/'tests/test_hrc_kernel.py'))['hu_tree']


@pytest.mark.parametrize('bounty_mode',['none','ko','pko'])
def test_exact_hu_chip_and_monetary_outcome_order(tmp_path,bounty_mode):
    tree=hu_tree()
    plain,baseline,meta=generate_leaves(tree,tmp_path,tmp_path/'chips')
    assert baseline==[10.,10.]  # original archive units are internal / 100
    assert meta['terminals']==3 and meta['vectors']==5
    assert list(map(list,plain[4]['vectors']))==[[20.,0.],[10.,10.],[0.,20.]]
    assert list(plain[1]['vectors'][0])==[9.5,10.5]
    tree['equity']={'mode':'icm','payouts':[50,30],'other_stacks':[],
                    'bounty':{'mode':bounty_mode,'amounts':[0.,0.] if bounty_mode=='none' else [10.,10.],
                              'other_amounts':[],'immediate_fraction':.5 if bounty_mode=='pko' else 1.}}
    money,base,_=generate_leaves(tree,tmp_path,tmp_path/'money')
    assert base==[40.,40.] if bounty_mode=='none' else base==[50.,50.]
    assert evaluate_baseline(tree,tmp_path,tmp_path/'baseline')==base
    expected=[[50.,30.],[40.,40.],[30.,50.]] if bounty_mode=='none' else [[70.,30.],[50.,50.],[30.,70.]]
    assert list(map(list,money[4]['vectors']))==expected
    assert not (tmp_path/'baseline/hrcz-live-masks.bin').exists()


def test_rank_pattern_uses_paid_not_starting_stack_order():
    term={'remaining':[0,300,450,1000],'contributions':[200,100,150,0],'folded':[False,False,False,True]}
    patterns=list(terminal_rank_patterns(term))
    assert len(patterns)==9 and patterns[0]==[9,0,0,0] and patterns[-1]==[7,9,8,0]
    order=[0,2,1]
    for index,ranks in enumerate(patterns):
        actual=0;best=ranks[order[0]]
        for p in order[1:]:
            actual=actual*3+1+(ranks[p]>best)-(ranks[p]<best);best=max(best,ranks[p])
        assert actual==index


def test_vector_budget_rejected_before_native_prepare(tmp_path):
    tree=hu_tree();tree['players']=10
    term={'folded':[False]*10}
    tree['terminals']=[deepcopy(term) for _ in range(103)]
    tree['nodes']=[{'id':i,'terminal_id':i,'children':[]} for i in range(103)]
    with pytest.raises(ValueError,match='vector budget'):
        generate_leaves(tree,tmp_path,tmp_path/'over-budget')
    assert not (tmp_path/'over-budget').exists()


@pytest.mark.parametrize('filename',['hu10bb-pushfold-initial.hrcz','eight15bb-raise-call-postflop-60m.hrcz','eight15bb-pko-50-30-20-initial.hrcz'])
def test_all_original_archive_leaf_float32_bytes(tmp_path,filename):
    if not (ROOT/'analysis/hrc-desktop'/filename).exists():pytest.skip('Local original fixture unavailable')
    check=runpy.run_path(str(ROOT/'scripts/validate-hrc-hrcz-leaves.py'))['check_archive']
    result=check(filename,tmp_path)
    assert result['passed'],result['first_mismatches']
