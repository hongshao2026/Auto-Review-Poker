//! Timing harness for the native solver. Outputs one JSON record per checkpoint.

use std::time::Instant;

use engine::br;
use engine::cards;
use engine::cfr::{DcfrParams, Solver};
use engine::config::SolveConfig;
use engine::nlhe::NlheGame;
use engine::tree::NodeKind;
use serde_json::{json, Value};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 4 {
        return Err("usage: compare_latency CONFIG.json THREADS ITER1,ITER2,... NODE1|NODE2|...".into());
    }
    let cfg: SolveConfig = serde_json::from_reader(std::fs::File::open(&args[0])?)?;
    let threads = args[1].parse::<usize>()?;
    let pool = rayon::ThreadPoolBuilder::new().num_threads(threads).build()?;
    let checkpoints = args[2].split(',').map(str::parse::<u64>).collect::<Result<Vec<_>, _>>()?;
    if threads == 0 || checkpoints[0] == 0 || checkpoints.windows(2).any(|w| w[0] >= w[1]) {
        return Err("positive threads and strictly increasing positive checkpoints are required".into());
    }
    let targets = args[3].split('|').collect::<Vec<_>>();
    pool.install(|| run(&cfg, &checkpoints, &targets))?;
    Ok(())
}

fn run(cfg: &SolveConfig, checkpoints: &[u64], targets: &[&str]) -> Result<(), String> {
    let start = Instant::now();
    let game = NlheGame::new(cfg)?;
    let mut solver = Solver::new_configured(game, engine::cfr::StorageMode::F32, cfg);
    let build = start.elapsed().as_secs_f64();
    println!("{}", json!({"build_s": build, "nodes": solver.game().tree().len(),
        "strategy_bytes": solver.storage_bytes(), "chance_map_bytes": solver.game().chance_map_bytes()}));

    let params = DcfrParams::from_config(cfg);
    let mut train_s = 0.0;
    let mut check_s = 0.0;
    for &iteration in checkpoints {
        let count = iteration - solver.iterations();
        let start = Instant::now();
        solver.run(count, &params, 0, |_, _, _| {});
        train_s += start.elapsed().as_secs_f64();

        let start = Instant::now();
        let ev = [solver.expected_value(0), solver.expected_value(1)];
        let br = [0, 1].map(|p| br::best_response_value(solver.game(), p, &solver.average()));
        check_s += start.elapsed().as_secs_f64();
        let pct = 50.0 * (br[0] - ev[0] + br[1] - ev[1]) as f64 / cfg.starting_pot;
        let pot_ev = [0, 1].map(|p| solver.game().ev_pot_share(p, ev[p as usize]));
        let policy = targets.iter().map(|line| node_policy(&solver, line)).collect::<Result<Vec<_>, _>>()?;
        println!("{}", json!({"iteration": iteration, "train_s": train_s, "check_s": check_s,
            "pct_pot": pct, "pot_ev": pot_ev, "root_ev": ev, "root_br": br, "policy": policy}));
    }
    Ok(())
}

fn node_policy(solver: &Solver<NlheGame>, line: &str) -> Result<Value, String> {
    let game = solver.game();
    let node = game.tree().resolve_line(line)?;
    let NodeKind::Decision { player, actions } = &game.node_at(node).kind else {
        return Err(format!("benchmark line {line:?} does not reach a decision"));
    };
    let actions = actions.iter().map(|a| a.label.token()).collect::<Vec<_>>();
    let hands = game.live_combos(node, *player);
    let data = solver.average_strategy(node);
    let rows = hands.iter().enumerate().map(|(i, &(a, b))| {
        let hand = format!("{}{}", cards::card_to_string(a), cards::card_to_string(b));
        let freqs = (0..actions.len()).map(|k| data[k * hands.len() + i]).collect::<Vec<_>>();
        (hand, freqs)
    }).collect::<std::collections::BTreeMap<_, _>>();
    Ok(json!({"line": line, "actions": actions, "frequencies": rows}))
}
