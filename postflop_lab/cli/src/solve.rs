//! `solver solve`: build a spot, run Discounted CFR to a stopping condition, report,
//! and optionally save a [`Solution`].
//!
//! # Node locking
//!
//! Freezing a decision node is a property of the spot, so it lives in the TOML config as
//! a `[[locks]]` array rather than behind a flag — a locked strategy is a per-combo
//! array, which is not something to type at a shell prompt, and it has to travel with the
//! saved solution anyway:
//!
//! ```toml
//! [[locks]]
//! line = "check,bet:5"   # "" is the root; see GameTree::resolve_line
//! player = 1             # 0 = OOP, 1 = IP, cross-checked against the tree
//! freqs = [0.7, 0.3]     # one per action, applied to every combo
//! # ...or strategy = [...], per combo, action-major
//! ```
//!
//! Everything else is unchanged, and a config with no locks solves exactly as before.

use std::path::{Path, PathBuf};
use std::time::Instant;

use clap::{Args, ValueEnum};
use engine::cfr::{DcfrParams, Solver, StorageMode};
use engine::config::{SolveConfig, Tournament};
use engine::game::{Game, NodeInfo};
use engine::icm;
use engine::nlhe::NlheGame;
use engine::solution::Solution;

/// CLI-facing mirror of [`StorageMode`] (clap needs its own enum for `--storage`).
#[derive(Clone, Copy, ValueEnum)]
enum StorageArg {
    F32,
    I16,
}

impl From<StorageArg> for StorageMode {
    fn from(a: StorageArg) -> StorageMode {
        match a {
            StorageArg::F32 => StorageMode::F32,
            StorageArg::I16 => StorageMode::I16,
        }
    }
}

#[derive(Args)]
pub struct SolveArgs {
    /// Path to the JSON or TOML config.
    #[arg(long)]
    config: PathBuf,

    /// Override: board cards, e.g. "As Kd 7h".
    #[arg(long)]
    board: Option<String>,
    /// Override: OOP range string.
    #[arg(long = "oop-range")]
    oop_range: Option<String>,
    /// Override: IP range string.
    #[arg(long = "ip-range")]
    ip_range: Option<String>,
    /// Override: effective stack, in chips.
    #[arg(long)]
    stack: Option<f64>,
    /// Override: starting pot, in chips.
    #[arg(long)]
    pot: Option<f64>,
    /// Override: a TOML file holding a `[tournament]` table (payouts, stacks, seats).
    /// Its block replaces the config's, so one structure file is reused across boards.
    /// Present means payoffs are scored in tournament equity (CSTE) instead of chips.
    #[arg(long)]
    tournament: Option<PathBuf>,
    /// Override: hard iteration ceiling.
    #[arg(long = "max-iterations")]
    max_iterations: Option<u64>,
    /// Override: stop once exploitability falls below this percent of pot.
    #[arg(long = "target-exploitability")]
    target_exploitability: Option<f64>,
    /// Measure and print exploitability every N iterations; also the granularity
    /// of the stop-condition check.
    #[arg(long = "report-every", default_value_t = 100)]
    report_every: u64,
    /// Rayon global thread pool size (default: all logical CPUs). The CFR
    /// traversal parallelizes across chance-node outcomes; results are
    /// bit-identical for every thread count.
    #[arg(long)]
    threads: Option<usize>,
    /// Write the solved strategy here. Omit to solve-and-print only.
    #[arg(long)]
    out: Option<PathBuf>,
    /// Per-node regret/strategy storage. `i16` roughly halves peak memory; results
    /// are the same up to the codec's quantization error. See `StorageMode`. That
    /// error was measured on chip payoffs only: with `--tournament`, i16 parity is
    /// not yet measured and the report says so.
    #[arg(long, value_enum, default_value_t = StorageArg::F32)]
    storage: StorageArg,
    /// MiB budget for regret and strategy arrays, including export if requested.
    #[arg(long, default_value_t = 4096)]
    max_strategy_mib: u64,
}

pub fn run(args: SolveArgs) -> Result<(), String> {
    if args.report_every == 0 {
        return Err("--report-every must be at least 1 (it drives the stop-condition check)".into());
    }
    if let Some(out) = &args.out {
        if let Ok(output) = out.canonicalize() {
            if args.config.canonicalize().ok().as_ref() == Some(&output) {
                return Err("solution output cannot replace the input config".into());
            }
        }
    }

    let mut cfg = read_config(&args.config)?;

    if let Some(b) = args.board {
        cfg.board = b;
    }
    if let Some(r) = args.oop_range {
        cfg.oop_range = r;
    }
    if let Some(r) = args.ip_range {
        cfg.ip_range = r;
    }
    if let Some(s) = args.stack {
        cfg.effective_stack = s;
    }
    if let Some(p) = args.pot {
        cfg.starting_pot = p;
    }
    if let Some(path) = &args.tournament {
        cfg.tournament = Some(read_tournament(path)?);
    }
    if let Some(m) = args.max_iterations {
        cfg.max_iterations = m;
    }
    if let Some(t) = args.target_exploitability {
        cfg.target_exploitability = t;
    }
    cfg.validate()?;

    if cfg.turn_chance_sampling {
        return Err(
            "turn_chance_sampling is set, but exact search is the only mode implemented so far \
             (the flag exists for a future speed mode) - refusing to silently approximate"
                .to_string(),
        );
    }

    if let Some(n) = args.threads {
        if n == 0 {
            return Err("--threads must be at least 1".into());
        }
        rayon::ThreadPoolBuilder::new().num_threads(n).build_global()
            .map_err(|e| format!("cannot configure thread pool: {e}"))?;
    }

    let game = NlheGame::new(&cfg)?;
    check_strategy_budget(&game, args.storage, args.out.is_some(), args.max_strategy_mib)?;
    let params = DcfrParams::from_config(&cfg);
    let mut solver = Solver::new_configured(game, args.storage.into(), &cfg);
    print_tree_stats(&solver);

    // Under a tournament payoff map the headline metric is NashConv in CSTE chips,
    // not exploitability in chips: the game is general-sum. Same number, different
    // meaning, so it never wears the chip label.
    let (metric, unit) = metric(solver.game());
    let start = Instant::now();
    let mut done = 0u64;
    let mut last_pct = f32::INFINITY;
    while done < cfg.max_iterations {
        let chunk = args.report_every.min(cfg.max_iterations - done);
        solver.run(chunk, &params, chunk, |i, chips, pct| {
            println!("iter {i:>8}  {metric} {chips:.6} {unit}  {pct:.4}% of pot  [measured]");
            last_pct = pct;
        });
        done += chunk;
        if (last_pct as f64) <= cfg.target_exploitability {
            break;
        }
    }
    let wall_seconds = start.elapsed().as_secs_f64();

    print_final_report(&solver, wall_seconds);

    if let Some(out) = args.out {
        let sol = Solution::from_solver(&solver, wall_seconds);
        sol.save(&out)?;
        println!("wrote {}", out.display());
    }
    Ok(())
}

fn check_strategy_budget(game: &NlheGame, storage: StorageArg, save: bool, mib: u64) -> Result<(), String> {
    let limit = mib.checked_mul(1024 * 1024).filter(|&n| n > 0)
        .ok_or("--max-strategy-mib must specify a positive, representable memory budget")?;
    let nodes = game.num_nodes() as u64;
    let mut entries = 0u64;
    let mut export_entries = 0u64;
    for id in 0..nodes as u32 {
        if let NodeInfo::Decision { player, num_actions } = game.node(id) {
            let size = (num_actions * game.combo_count(id, player)) as u64;
            export_entries += size;
            if game.strategy_alias(id).is_none() {
                entries += size;
            }
        }
    }
    if entries >= u32::MAX as u64 {
        return Err(format!("tree requires {entries} entries per strategy array; the engine uses 32-bit offsets"));
    }
    let training = match storage {
        StorageArg::F32 => entries * 8,
        StorageArg::I16 => entries * 4 + nodes * 8,
    } + if game.config().prediction_weight > 0.0 { entries * 4 } else { 0 };
    let bytes = training + if save { export_entries * 4 } else { 0 };
    if bytes > limit {
        return Err(format!("strategy arrays require {} MiB, budget is {mib} MiB; narrow the tree or raise --max-strategy-mib", bytes.div_ceil(1024 * 1024)));
    }
    Ok(())
}

fn metric(game: &NlheGame) -> (&'static str, &'static str) {
    if game.config().tournament.is_some() {
        ("NashConv", "cste chips")
    } else if game.zero_sum() {
        ("exploitability", "chips")
    } else {
        ("NashConv", "chips")
    }
}

pub(crate) fn read_config(path: &Path) -> Result<SolveConfig, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("cannot read {path:?}: {e}"))?;
    let text = text.trim_start_matches('\u{feff}');
    if text.trim_start().starts_with('{') {
        serde_json::from_str(text).map_err(|e| format!("invalid JSON configuration: {e}"))
    } else {
        SolveConfig::from_toml_str(text)
    }
}

fn print_tree_stats(solver: &Solver<NlheGame>) {
    let game = solver.game();
    if game.config().suit_isomorphism {
        println!("suit isomorphism: {} decision nodes share strategy storage", game.shared_suit_decisions());
    }
    let counts = game.tree().counts();
    println!(
        "tree: {} decision, {} chance, {} fold, {} showdown terminals ({} nodes total)",
        counts.decision, counts.chance, counts.fold, counts.showdown, counts.total
    );
    let locked = game.locked_nodes();
    if !locked.is_empty() {
        println!(
            "locks: {} node(s) frozen; the rest of the tree is solved around them, and \
             exploitability below is measured against the locked profile",
            locked.len()
        );
        for (node, lock) in locked.iter().zip(&game.config().locks) {
            let who = if lock.player == 0 { "OOP" } else { "IP " };
            println!("  node {node:>7}  {who}  line {:?}", lock.line);
        }
    }
    println!(
        "strategy storage: {:?}, {} bytes [measured]  (regret + strategy-sum{})",
        solver.storage_mode(),
        solver.storage_bytes(),
        if game.config().prediction_weight > 0.0 { " + prediction arrays" } else { " arrays" }
    );
    println!("chance maps: {} bytes [measured]", game.chance_map_bytes());
}

fn print_final_report(solver: &Solver<NlheGame>, wall_seconds: f64) {
    let game = solver.game();
    let cfg = game.config();
    let report = solver.exploitability();
    println!("=== final report ===");
    println!("iterations: {}", solver.iterations());
    println!("wall time: {wall_seconds:.4} s [measured]");
    match &cfg.tournament {
        // Chips: the game is zero-sum, so this number is a genuine bound on what
        // either player can win by deviating.
        None => {
            let (name, unit) = metric(game);
            println!("{name}: {:.6} {unit}  {:.4}% of pot  [measured]", report.chips, report.pct_of_pot);
        }
        // Tournament equity: the game is general-sum (the frozen field trades
        // equity), so the same slot holds NashConv and is never called
        // exploitability. See the `engine::br` module docs.
        Some(_) => {
            println!("payoff unit: cste (chip-scaled tournament equity)");
            println!(
                "NashConv: {:.6} cste chips  {:.4}% of pot  [measured]",
                report.chips, report.pct_of_pot
            );
            println!(
                "  (both players' unilateral best-response gains, summed; the game is \
                 general-sum, so zero does not certify a minimum EV)"
            );
        }
    }
    for p in 0..2u8 {
        let who = if p == 0 { "OOP" } else { "IP " };
        let zero_sum = solver.expected_value(p);
        let pot_share = game.ev_pot_share(p, zero_sum);
        let baseline = if game.zero_sum() { "zero-sum" } else { "net" };
        println!("{who} EV: {baseline} {zero_sum:.4}  pot-share {pot_share:.4}  [measured]");
    }
    if let Some(t) = &cfg.tournament {
        print_icm_block(game, t, report.gain, matches!(solver.storage_mode(), StorageMode::I16));
    }
}

/// The tournament half of the final report: which table seats are in the hand, what
/// each player gains by deviating alone, how the two seats price a flip against each
/// other, and the volume the ICM map covered.
///
/// The bubble factors are measured at [`NlheGame::icm_base_stacks`], not at the raw
/// `tournament.stacks` of the file: the payoff map is centred on the stacks with the
/// starting pot credited half to each in-hand seat, and the preflop money moves the
/// quoted factor well inside the four decimals printed here.
fn print_icm_block(game: &NlheGame, t: &Tournament, gain: [f32; 2], i16: bool) {
    let counts = game.tree().counts();
    let base = game.icm_base_stacks().expect("an ICM solve has a base stack vector");
    let bf = icm::bubble_factors(base, &t.payouts);
    let paid = t.payouts.len().min(t.stacks.len());
    for (p, g) in gain.iter().enumerate() {
        let who = if p == 0 { "OOP" } else { "IP " };
        let seat = t.seats[p];
        let other = t.seats[1 - p];
        let f = bf[seat][other];
        println!(
            "{who} seat {seat} ({} chips, {} with this pot)  gain {:.6} cste chips  \
             bubble factor vs seat {other} {f:.4} (required equity {:.2}%)  [measured]",
            t.stacks[seat],
            base[seat],
            g,
            100.0 * f / (f + 1.0)
        );
    }
    println!(
        "icm: {} seats, {paid} paid, {} terminals mapped  [measured]",
        t.stacks.len(),
        counts.fold + counts.showdown
    );
    if i16 {
        println!("note: i16 storage parity was measured on chip payoffs only; not yet on CSTE (ICM) payoffs");
    }
}

/// Reads a `[tournament]` table out of its own file, for `--tournament`.
///
/// Nothing is checked here beyond the file's shape: the block goes into the config
/// and `SolveConfig::validate` rejects a bad one with the offending seat, stack or
/// payout named.
fn read_tournament(path: &Path) -> Result<Tournament, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("cannot read {path:?}: {e}"))?;
    let mut doc: toml::Table =
        toml::from_str(&text).map_err(|e| format!("invalid tournament file {path:?}: {e}"))?;
    let block = doc
        .remove("tournament")
        .ok_or_else(|| format!("{path:?} has no [tournament] table"))?;
    if !doc.is_empty() {
        let keys: Vec<&str> = doc.keys().map(String::as_str).collect();
        return Err(format!(
            "{path:?} has keys outside [tournament] ({}); a tournament file carries the \
             prize structure and the table's stacks, nothing else",
            keys.join(", ")
        ));
    }
    block
        .try_into()
        .map_err(|e| format!("invalid [tournament] in {path:?}: {e}"))
}
