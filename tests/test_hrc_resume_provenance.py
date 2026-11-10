"""Provenance can retain an original digest only for identical native inputs."""
from copy import deepcopy
import json

import pytest

from preflop_lab.hrc_native import run
from preflop_lab.hrc_sampling import preserve_ci_identity
from test_hrc_kernel import hu_tree


def test_reconstructed_provenance_resume_preserves_rng_and_all_learned_bytes(tmp_path):
    original = hu_tree()
    original['provenance'] = {'settings_sha256': 'original-settings-digest'}
    source = tmp_path / 'source'
    run(original, tmp_path, 500, 43, source)
    before = (source / 'checkpoint.bin').read_bytes()
    rebuilt = deepcopy(original)
    rebuilt['provenance'] = {'settings_sha256': 'rebuilt-settings-digest'}
    output, control = tmp_path / 'rebuilt', tmp_path / 'control'
    run(rebuilt, tmp_path, 1500, 43, output, resume_from=source / 'checkpoint.bin', track_ci=False)
    run(original, tmp_path, 1500, 43, control, resume_from=source / 'checkpoint.bin', track_ci=False)
    assert (output / 'checkpoint.bin').read_bytes() == (control / 'checkpoint.bin').read_bytes()
    assert (source / 'checkpoint.bin').read_bytes() == before
    assert json.loads((output / 'tree.json').read_text())['provenance'] == original['provenance']
    assert rebuilt['provenance']['settings_sha256'] == 'rebuilt-settings-digest'


@pytest.mark.parametrize('field,value', [('big_blind', 20), ('equity', {'mode': 'mtt_icm'}),
    ('policies', {'version': 1, 'nodes': []}), ('stores', {'street_formats': [23, 25, 25, 25]}),
    ('unknown_future_input', 1)])
def test_changed_computational_fields_do_not_reuse_source_provenance(tmp_path, field, value):
    original = hu_tree()
    original['provenance'] = {'settings_sha256': 'original'}
    (tmp_path / 'tree.json').write_text(json.dumps(original))
    candidate = deepcopy(original)
    candidate['provenance'] = {'settings_sha256': 'changed'}
    candidate[field] = value
    retained = preserve_ci_identity(candidate, tmp_path / 'checkpoint.bin')
    assert retained['provenance'] == candidate['provenance']
    assert retained[field] == value


def test_game_change_still_rejected_by_native_checkpoint_validation(tmp_path):
    original = hu_tree()
    original['provenance'] = {'settings_sha256': 'original'}
    source = tmp_path / 'source'
    run(original, tmp_path, 500, 43, source)
    changed = deepcopy(original)
    changed['provenance'] = {'settings_sha256': 'rebuilt'}
    changed['big_blind'] += 1
    with pytest.raises(RuntimeError, match='Checkpoint tree identity mismatch'):
        run(changed, tmp_path, 600, 43, tmp_path / 'rejected', resume_from=source / 'checkpoint.bin', track_ci=False)
