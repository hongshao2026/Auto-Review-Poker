"""Lightweight command contract checks: never launch a process or parse a tree."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ci_benchmark', ROOT/'scripts/benchmark-hrc-ci-target.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_formal_keeps_resume_and_scope_reset_semantics(tmp_path):
    plan = {'output': str(tmp_path), 'build': {'executable_path': 'actual.exe'},
            'tree_binary': 'three.bin', 'resources_dir': 'profiles', 'seed': 51,
            'training_threads': 8, 'memory_budget_bytes': 6 << 30,
            'formal_target_ci': 10, 'formal_total_sample_cap': 1000000000,
            'hard_seconds_per_phase': 3600}
    command = runner.phase_command(plan, 'formal', resume=tmp_path/'initialization/checkpoint.bin')
    assert command[1:5] == ['three.bin', 'profiles', '1000000000', '51']
    assert command[6:10] == ['v4', str(tmp_path/'initialization/checkpoint.bin'), '0', '0']
    assert command[10:19] == ['-1', '10', '3600', str(6<<30), '8', '1', '-', '1', '1']


def test_initialization_tracks_ci_without_a_ci_stop_target(tmp_path):
    plan = {'output': str(tmp_path), 'build': {'executable_path': 'actual.exe'},
            'initialization_track_ci': True, 'initialization_samples': 10000000}
    command = runner.phase_command(plan, 'initialization')
    assert command[3] == '10000000'
    assert command[7:12] == ['-', '0', '0', '-1', '-1']
    assert command[17] == '1'


def test_historical_default_initialization_ci_remains_off(tmp_path):
    plan = {'output': str(tmp_path), 'build': {'executable_path': 'actual.exe'}}
    command = runner.phase_command(plan, 'initialization')
    assert command[17] == '0'
    assert command[3] == '10000000'


def test_large_formal_budget_is_explicit_and_does_not_change_initialization(tmp_path):
    plan = {'output': str(tmp_path), 'build': {'executable_path': 'actual.exe'},
            'formal_total_sample_cap': 3_000_000_000,
            'maximum_additional_samples': 2_990_000_000}
    command = runner.phase_command(plan, 'formal', resume='original-10m-checkpoint.bin')
    assert command[3] == '3000000000' and command[19] == '2990000000'
    initial = runner.phase_command(plan, 'initialization')
    assert len(initial) == 19 and initial[3] == '10000000'


def test_fixed_sample_postphase_can_disable_ci_without_resetting(tmp_path):
    plan = {'output': str(tmp_path), 'build': {'executable_path': 'actual.exe'},
            'formal_total_sample_cap': 15_000_000, 'formal_target_ci': -1,
            'formal_track_ci': False, 'training_threads': 4}
    command = runner.phase_command(plan, 'fixed5m', resume='immutable-own10m.bin')
    assert command[3] == '15000000'
    assert command[7:12] == ['immutable-own10m.bin', '0', '0', '-1', '-1']
    assert command[14:19] == ['4', '1', '-', '0', '1']
