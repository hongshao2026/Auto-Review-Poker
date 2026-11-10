"""Pairwise all-in bubble factors using the same native monetary evaluators."""
import hashlib
import json
from pathlib import Path
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]
_build_lock = threading.Lock()


def build():
    files = [ROOT / 'native' / file for file in ('hrc_tournament_analysis.cpp', 'hrc_equity.hpp', 'hrc_mtt.hpp')]
    digest = hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()
    folder = ROOT / 'analysis/hrc-native/analysis-build'
    exe = folder / f'hrc_analysis-{digest[:20]}.exe'
    with _build_lock:
        if exe.is_file():
            return exe
        folder.mkdir(parents=True, exist_ok=True)
        zig = Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
        command = [str(zig), 'c++', '-O3', '-std=c++17', '-ffp-contract=off', str(files[0]), '-o', str(exe)]
        compiled = subprocess.run(command, capture_output=True, text=True)
        if compiled.returncode:
            raise RuntimeError('权益分析内核编译失败：' + compiled.stderr[-4000:])
    return exe


def analyze_solver(solver):
    """HRC eC semantics: no blinds/dead money, static evaluator even with FGS."""
    cfg = getattr(solver, 'equity_config', None)
    if cfg is None:
        raise ValueError('泡沫因子需要 ICM 或 MTT 金额权益模型。')
    bounty = cfg['bounty']
    mode = 1 if cfg['mode'] == 'icm' else 2
    rows = [[mode, ('none', 'ko', 'pko').index(bounty['mode']), bounty['immediate_fraction']],
            solver.tree.rules.initial_stacks, cfg['payouts'], bounty['amounts'],
            cfg.get('other_stacks', []), bounty.get('other_amounts', [])]
    payload = '\n'.join(' '.join(map(str, row)) for row in rows) + '\n'
    completed = subprocess.run([str(build())], input=payload, capture_output=True, text=True, timeout=120)
    if completed.returncode:
        raise ValueError('权益分析失败：' + completed.stderr[-2000:])
    result = json.loads(completed.stdout)
    n = solver.tree.rules.players
    factors, premiums = [[None] * n for _ in range(n)], [[None] * n for _ in range(n)]
    for row in result['pairs']:
        factors[row['row']][row['column']] = row['bubble_factor']
        premiums[row['row']][row['column']] = row['risk_premium_pp']
    result.update(bubble_factors=factors, risk_premiums_pp=premiums,
                  players=[p['name'] for p in solver.config['players']],
                  stacks_bb=[s / solver.tree.rules.big_blind for s in solver.tree.rules.initial_stacks],
                  utility_unit='currency', equity_model=cfg['mode'], bounty_model=bounty['mode'],
                  model='static_pairwise_allin_no_dead_money', fgs_applied=False,
                  explanation='行玩家对列玩家：有效筹码全下，未投入盲注/前注或额外死钱。BF=(基准权益−输后权益)/(赢后权益−基准权益)，RP=100×(BF/(1+BF)−0.5)。FGS 场景也使用静态权益，符合原版此工具定义。')
    return result
