"""Raked terminal production wiring, portable input and actual deal/training tests."""
import copy
import hashlib
import json
import runpy
import subprocess

import pytest

from preflop_lab.hrc_native import ROOT, build, prepare, run

hu_tree=runpy.run_path(str(ROOT/'tests/test_hrc_kernel.py'))['hu_tree']
raw_node=runpy.run_path(str(ROOT/'tests/test_hrc_native_features.py'))['raw_node']


def rake_tree(mode='nfnd',fraction=.05,cap=100):
    tree=hu_tree();tree['rake']={'mode':mode,'fraction':fraction,'cap':cap}
    for t,raises in zip(tree['terminals'],[0,1,1]):t.update(street=0,raise_count=raises)
    return tree


def test_production_terminal_matches_all_original_rank_fixtures(tmp_path):
    original=json.loads((ROOT/'reports/hrc-original-rake-validation.json').read_text())
    build();buildinfo=json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text())
    source=ROOT/'scripts/native/rake_kernel_probe.cpp';binary=tmp_path/'rake-kernel.exe'
    subprocess.run([buildinfo['compiler'],'c++','-O2','-std=c++17','-ffp-contract=off',str(source),'-o',str(binary)],check=True,capture_output=True,text=True)
    inputs=[str(len(original['results']))]
    for case in original['results']:
        x=case['input'];inputs.append(' '.join(map(str,[len(x['remaining']),x['mode'],x['fraction'],x['cap'],x['street'],x['raises'],x['folded'],x['dead'],*x['remaining'],*x['paid'],*x['ranks']])))
    output=subprocess.check_output([str(binary)],input='\n'.join(inputs),text=True)
    records=list(map(json.loads,output.splitlines()));errors=[];rejected=0
    for record,case in zip(records,original['results']):
        expected=case['original'];x=case['input']
        if 'error' in expected:
            assert record.get('error') is True;rejected+=1;continue
        initial=[a+b for a,b in zip(x['remaining'],x['paid'])];initial[0]+=x['dead']
        net=[(a-b)/100 for a,b in zip(expected['stacks'],initial)]
        assert record['values']==net
        errors.extend(abs(a-b) for a,b in zip(record['values'],net))
    assert len(records)==original['cases']==1240
    report={'passed':True,'cases':len(records),'original_domain_rejections':rejected,'max_abs_error':max(errors),
            'scope':'Actual production Engine::terminal raked branch with original rank fixtures; tests net BB conversion and domain errors. Random card evaluation covered separately.',
            'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                [source,ROOT/'native/hrc_research_solver.cpp',ROOT/'native/hrc_settlement.hpp']},
            'original_report_sha256':hashlib.sha256((ROOT/'reports/hrc-original-rake-validation.json').read_bytes()).hexdigest()}
    (ROOT/'reports/hrc-native-rake-integration-validation.json').write_text(json.dumps(report,indent=2))


@pytest.mark.parametrize('mode',['nfnd','gg','full'])
def test_actual_raked_training_resume_and_net_loss(tmp_path,mode):
    tree=rake_tree(mode)
    run(tree,tmp_path,1000,42,tmp_path/'direct')
    run(tree,tmp_path,400,42,tmp_path/'partial')
    run(tree,tmp_path,1000,99,tmp_path/'resumed',resume_from=tmp_path/'partial/checkpoint.bin')
    assert (tmp_path/'direct/checkpoint.bin').read_bytes()==(tmp_path/'resumed/checkpoint.bin').read_bytes()
    index=json.loads((tmp_path/'direct/index.json').read_text())
    assert sum(index['root_mean_net_bb'])<0
    manifest=json.loads((tmp_path/'direct/manifest.json').read_text())
    assert manifest['rake']==tree['rake'] and manifest['utility']=='net_bb'


def test_zero_rake_fraction_matches_old_training_values(tmp_path):
    old=hu_tree();raked=rake_tree(fraction=0.)
    run(old,tmp_path,1000,42,tmp_path/'old');run(raked,tmp_path,1000,42,tmp_path/'raked')
    assert raw_node(tmp_path/'old')==raw_node(tmp_path/'raked')
    assert raw_node(tmp_path/'old',2)==raw_node(tmp_path/'raked',2)


@pytest.mark.parametrize('alteration',[
    {'mode':'unknown'},{'fraction':float('nan')},{'fraction':-.1},{'fraction':1.01},{'fraction':True},
    {'cap':-1},{'cap':1.5},{'cap':True},
])
def test_invalid_rake_rejected_before_training(tmp_path,alteration):
    tree=rake_tree();tree['rake'].update(alteration)
    with pytest.raises(ValueError):prepare(tree,tmp_path)


def test_rake_requires_cash_and_explicit_terminal_context(tmp_path):
    tree=rake_tree();tree['equity']={'mode':'icm','payouts':[70,30]}
    with pytest.raises(ValueError,match='chip equity'):prepare(tree,tmp_path/'icm')
    tree=rake_tree();tree['terminals'][0].pop('raise_count')
    with pytest.raises(ValueError,match='explicit terminal'):prepare(tree,tmp_path/'missing')


def test_rake_cannot_be_changed_by_policy_migration(tmp_path):
    tree=rake_tree();run(tree,tmp_path,10,42,tmp_path/'source')
    changed=copy.deepcopy(tree);changed['rake']['fraction']=.04
    with pytest.raises(ValueError,match='cannot change topology'):
        run(changed,tmp_path,10,42,tmp_path/'next',resume_from=tmp_path/'source/checkpoint.bin',checkpoint_migration='preserve')
