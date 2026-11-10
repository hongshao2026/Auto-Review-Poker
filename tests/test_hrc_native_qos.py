"""Process scheduling controls must not change serial solver state."""
import json
import subprocess

from preflop_lab.hrc_native import build, prepare
from test_hrc_kernel import hu_tree


def test_native_qos_default_on_and_off_preserve_checkpoint_and_rng(tmp_path):
    executable = build()
    prepared = prepare(hu_tree(), tmp_path / 'input')

    def invoke(label, flag, goal, resume=None):
        output = tmp_path / label
        output.mkdir()
        command = [str(executable), prepared['tree_binary'], str(tmp_path / 'input'),
                   str(goal), '43', str(output), 'v4', str(resume) if resume else '-',
                   '0', '0', '-1', '-1', '-1', str(1 << 30), '1', '1', '-', '-1', '-1',
                   '1000000000', '1', '1', '0']
        if flag is not None:
            command.append(str(flag))
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if flag == 2:
            assert result.returncode != 0
            assert 'Native process HighQoS requires 0 or 1' in result.stderr
            assert not (output / 'checkpoint.bin').exists()
            return None
        assert result.returncode == 0, result.stderr
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        for row in (rows[0], rows[-1]):
            assert row['native_qos_requested'] is (flag != 0)
            assert isinstance(row['native_qos_active'], bool)
            if flag == 0:
                assert not row['native_qos_active']
        assert rows[-1]['iteration'] == goal
        return output / 'checkpoint.bin'

    fresh = [invoke(str(flag), flag, 10003) for flag in (None, 0, 1)]
    assert len({path.read_bytes() for path in fresh}) == 1
    source = fresh[0]
    original = source.read_bytes()
    resumed = [invoke('resume-' + str(flag), flag, 20007, source) for flag in (None, 0, 1)]
    assert len({path.read_bytes() for path in resumed}) == 1
    assert source.read_bytes() == original
    invoke('invalid', 2, 10003)
