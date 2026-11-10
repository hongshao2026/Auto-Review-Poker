"""Restore data-only native solvers without opening the original application."""
import hashlib
import json

TOPOLOGY_KEYS = ('root', 'players', 'big_blind', 'initial_stacks', 'nodes', 'terminals')
# Canonical topology digests, derived from the four pinned research fixtures.
# Original archive byte hashes remain in hrc_benchmarks; these exclude file order.
FIXED_TOPOLOGY = {
    'eight15bb': 'ee9e7b21c08ae587c0495b2149ca672eb19d42c4f10d9f4961ec1be53dd7c1f1',
    'nine20bb': 'e20b727ad5127f1c4690ec21debd9e0998b7f112eb2fcf77c97f2258f8aeb656',
    'nine10bb': 'f5c3ce3497b885998b63375ce914866639d18aa007d86f3cb117cd50fb9a96bb',
    'hu10bb': 'eba60d54c8bdc501b6fcbbc19bc3538c2bd9cabbd712ccd28e46ea7a2fefa477',
}


def restore_solver(raw, tree):
    """Validate configuration and bind a checked snapshot without fixture I/O."""
    from . import hrc_benchmarks, hrc_custom, tournament
    from .hrc_research import HRCResearchSolver
    from .hrc_tournament import HRCTournamentSolver
    from .hrc_training import training_spec
    engine = raw.get('engine')
    if engine == 'hrc_imported':
        from .hrc_imported import HRCImportedSolver
        solver = HRCImportedSolver(raw)
        expected, actual = solver.tree.compact_export(), tree.compact_export()
        if any(expected[k] != actual[k] for k in TOPOLOGY_KEYS):
            raise ValueError('原始 HRC 存档与保存行动树不匹配。')
        solver.tree = tree
        return solver
    if engine == hrc_custom.ENGINE:
        solver = hrc_custom.HRCCustomSolver(raw)
        expected, actual = solver.tree.compact_export(), tree.compact_export()
        if any(expected[k] != actual[k] for k in TOPOLOGY_KEYS):
            raise ValueError('场景配置与保存行动树不匹配。')
    else:
        if engine == hrc_benchmarks.ENGINE:
            cls, config = HRCResearchSolver, hrc_benchmarks.validated_config(raw)
        elif engine == tournament.ENGINE:
            cls, config = HRCTournamentSolver, tournament.validated_config(raw)
        else:
            raise ValueError('完整检查点需要原生内核。')
        compact = tree.compact_export()
        digest = hashlib.sha256(json.dumps({k: compact[k] for k in TOPOLOGY_KEYS}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != FIXED_TOPOLOGY[config['benchmark']]:
            raise ValueError('保存的固定行动树身份不匹配。')
        solver = cls.__new__(cls)
        solver.config = config
        if engine == tournament.ENGINE:
            solver.equity_config = tournament.equity_spec(config, tree.rules.big_blind)
    solver.tree = tree
    solver.archive = None
    solver.output = solver.index = solver.reference = solver.resume_from = None
    training_spec(solver.config, tree)
    return solver
