from copy import deepcopy
import json
from pathlib import Path
import zipfile

import pytest

from preflop_lab.hrc_hrcz import SourceArchive
from preflop_lab.hrc_imported import HRCImportedSolver,config_for_source

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def source():
    return SourceArchive(ROOT/'analysis/hrc-desktop/hu10bb-pushfold-10m.hrcz')


def solver(source,**kw):
    return HRCImportedSolver({'engine':'hrc_imported','source_sha256':source.sha256,**kw},source=source)


def changed_archive(source,path,member,value):
    members=dict(source.members);members[member]=value
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in members.items():archive.writestr(name,data)
    return SourceArchive(path)


def test_read_only_source_policy_uses_unknown_history_not_fabricated_visits(source):
    imported=solver(source)
    assert imported.tree is source.tree and imported.output is None
    assert imported.training_supported
    strategy=imported.result_node([])['strategy']
    assert strategy['visits'] is None
    assert strategy['hands']['AA']['visits'] is None
    assert strategy['hands']['AA']['has_saved_policy']
    assert strategy['saved_counter_float32']==20000500.
    assert sum(strategy['hands']['AA']['frequencies'])==pytest.approx(1)
    result=imported.build_result()
    assert result['summary']['iterations_completed']==0
    assert result['summary']['source_iterations'] is None
    assert result['summary']['hrcz_import']['source_saved_counter']==20000500.
    assert result['summary']['hrcz_import']['source_iterations_known'] is False
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize('field,value',[('big_blind',2),('utility','icm'),('tree_settings',{}),('policies',{'version':1,'nodes':[{'node_id':0,'locks':[None,[1.]*169]}]})])
def test_import_scene_projection_cannot_be_edited(source,field,value):
    cfg=config_for_source(source);cfg[field]=value
    with pytest.raises(ValueError,match='不可修改'):HRCImportedSolver(cfg,source=source)


def test_run_controls_are_separate_from_saved_scene(source):
    imported=solver(source,iterations=200,seed=43,track_ci=True,hard_seconds=2,target_ci=.1)
    assert imported.config['seed']==43
    assert imported.compact_override['ci']=={'enabled':True}
    assert imported.config['tree_settings']==source.settings['treeconfig']


def test_baseline_mismatch_is_readonly_before_native(source,tmp_path):
    state=deepcopy(source.state);state['eqpre'][0]+=2
    changed=changed_archive(source,tmp_path/'baseline.hrcz','state.json',json.dumps(state).encode())
    imported=solver(changed)
    assert not imported.training_supported
    assert imported.baseline_validation['status']=='mismatch'
    assert imported.result_node([])['strategy']['hands']['AA']['has_saved_policy']
    with pytest.raises(ValueError,match='仅可查看'):imported.initialize_checkpoint(tmp_path/'no-write')
    assert not (tmp_path/'no-write').exists()


def test_unknown_profile_can_be_viewed_without_substitution(source,tmp_path):
    settings=deepcopy(source.settings)
    settings['engine']['configuration']['abstractions'][1]['id']='unknown-resource'
    changed=changed_archive(source,tmp_path/'profile.hrcz','settings.json',json.dumps(settings).encode())
    imported=solver(changed)
    assert not imported.training_supported
    assert imported.result_node([])['strategy']['hands']['AA']['has_saved_policy']
    assert imported.config['abstractions'][1]['id']=='unknown-resource'


def test_unknown_storage_is_explicit_readonly(source,tmp_path):
    import struct
    data=bytearray(source.members['nodedata.dat'])
    # File count then pY header: node ID, payload length, reserved, format ID.
    struct.pack_into('<i',data,16,999)
    changed=changed_archive(source,tmp_path/'format.hrcz','nodedata.dat',data)
    imported=solver(changed)
    assert not imported.training_supported
    view=imported.result_node([])['strategy']
    assert view['decode_status']=='unsupported_storage_format' and view['hands']=={}
    assert not view['has_saved_policy']
    json.dumps(imported.build_result(),allow_nan=False)


def test_initialize_converts_real_policy_without_training_and_checks_baseline(source,tmp_path):
    imported=solver(source)
    before=imported.result_node([])['strategy']
    imported.initialize_checkpoint(tmp_path/'import')
    after=imported.result_node([])['strategy']
    assert imported.index['samples']==0
    assert after['visits']==0 and after['new_visits']==0
    assert after['hands']['AA']['has_saved_policy']
    for hand,row in before['hands'].items():
        assert after['hands'][hand]['frequencies']==pytest.approx(row['frequencies'],abs=1e-14)
        assert after['hands'][hand]['relative_ev_bb']==pytest.approx(row['relative_ev_bb'],abs=1e-12)
    assert imported.baseline_validation['method']=='native_production_baseline'
    assert imported.baseline_validation['passed']
    assert imported.resume_from==tmp_path/'import/checkpoint.bin'
    manifest=json.loads((tmp_path/'import/manifest.json').read_text())
    assert manifest['original_strategy_read'] and not manifest['fresh_zero_storage']
    assert not manifest['original_leaf_values_read']


def test_real_hu_policy_continue_counts_only_new_samples(source,tmp_path,monkeypatch):
    import preflop_lab.hrc_imported as adapter
    monkeypatch.setattr(adapter,'CACHE',tmp_path)
    imported=solver(source,iterations=100)
    imported.initialize_checkpoint(tmp_path/'origin')
    first=imported.run(100)
    assert first['summary']['iterations_completed']==100
    assert first['summary']['source_iterations'] is None
    assert first['summary']['fresh_zero_origin'] is False
    assert first['nodes']['root']['visits']==100
    assert first['nodes']['root']['storage_update_counter']==20000600
    assert first['nodes']['root']['has_saved_policy']
    second=imported.run(200)
    assert second['summary']['iterations_completed']==200
    assert second['nodes']['root']['visits']==200
    assert second['nodes']['root']['storage_update_counter']==20000700
    assert not any('comparison' in row for row in second['nodes'].values() if row)


def test_real_pko_baseline_is_money_and_source_ev_is_not_scaled_to_bb():
    source=SourceArchive(ROOT/'analysis/hrc-desktop/eight15bb-pko-50-30-20-60m.hrcz')
    imported=solver(source)
    assert imported.utility_scale==1
    assert imported.utility_unit=='currency'
    assert imported.training_supported
    assert imported.utility_offsets==[22.5]*8
    assert imported.baseline_validation['independent']==pytest.approx([22.5]*8,abs=1e-12)
    assert 'relative_ev' in imported.result_node([])['strategy']['hands']['AA']

