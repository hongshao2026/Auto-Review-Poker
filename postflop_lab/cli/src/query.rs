use std::path::PathBuf;

use clap::Args;
use engine::br::{self, StrategyProfile};
use engine::cards::{self, NUM_CARDS};
use engine::game::{Game, NodeInfo};
use engine::nlhe::NlheGame;
use engine::solution::{NodeStrategy, Solution};
use engine::tree::{GameTree, NodeKind, Terminal, NO_CHILD};
use serde_json::{json, Value};

#[derive(Args)]
pub struct TreeArgs {
    #[arg(long)]
    config: PathBuf,
    /// Comma-separated action and runout tokens. Amounts are street totals.
    #[arg(long, default_value = "")]
    line: String,
}

#[derive(Args)]
pub struct QueryArgs {
    #[arg(long)]
    solution: PathBuf,
    /// Comma-separated action and runout tokens. Amounts are street totals.
    #[arg(long, default_value = "")]
    line: String,
    /// Include each action's EV conditional on this hand reaching the node.
    #[arg(long)]
    ev: bool,
}

pub fn tree(args: TreeArgs) -> Result<(), String> {
    let cfg = crate::solve::read_config(&args.config)?;
    cfg.validate()?;
    let tree = GameTree::build(&cfg, &cfg.board_cards()?)?;
    let node = tree.resolve_line(&args.line)?;
    let counts = tree.counts();
    let mut result = node_json(&tree, node);
    result["counts"] = json!({"nodes": counts.total, "decisions": counts.decision,
        "chance": counts.chance, "folds": counts.fold, "showdowns": counts.showdown});
    print_json(result)
}

pub fn query(args: QueryArgs) -> Result<(), String> {
    let sol = Solution::load(&args.solution)?;
    let game = NlheGame::new(&sol.config)?;
    let tree = game.tree();
    let node = tree.resolve_line(&args.line)?;
    let mut result = node_json(tree, node);
    result["board"] = json!(game.board_at(node).iter().map(|&c| cards::card_to_string(c)).collect::<Vec<_>>());
    result["meta"] = json!(sol.meta);
    result["metric"] = json!(if game.zero_sum() { "exploitability" } else { "nashconv" });
    if let NodeKind::Decision { player, actions } = &tree.node(node).kind {
        let profile = FileProfile(&sol.nodes);
        for strategy in &sol.nodes {
            let count = game.combo_count(strategy.node, strategy.player);
            if strategy.combo_count as usize != count || strategy.strategy.iter().any(|p| !p.is_finite() || *p < 0.0 || *p > 1.00001) {
                return Err(format!("invalid strategy payload at node {}", strategy.node));
            }
        }
        let strategy = profile.at(node);
        let hands = game.live_combos(node, *player);
        let mut conditional_evs = Vec::new();
        let mut mass = Vec::new();
        if args.ev {
            let opp = 1 - *player;
            let reach = reach_at(&game, &profile, &args.line, opp)?;
            mass = game.compatible_mass(node, *player, &reach);
            for action in actions {
                let mut values = vec![0.0; hands.len()];
                br::subtree_values(&game, action.child, *player, &profile, &reach, false, &mut values);
                conditional_evs.push(values);
            }
        }
        let rows = hands.iter().enumerate().map(|(i, &(a, b))| {
            let frequencies: Vec<_> = (0..actions.len()).map(|action| strategy.strategy[action * hands.len() + i]).collect();
            let mut row = json!({"combo": format!("{}{}", cards::card_to_string(a), cards::card_to_string(b)), "frequencies": frequencies});
            if args.ev {
                let evs: Vec<Option<f32>> = conditional_evs.iter().map(|values| {
                    (mass[i] > 0.0).then(|| values[i] / mass[i])
                }).collect();
                let ev = evs.iter().zip(frequencies).try_fold(0.0, |sum, (value, p)| value.map(|v| sum + p * v));
                row["ev"] = json!(ev);
                row["action_evs"] = json!(evs);
            }
            row
        }).collect::<Vec<_>>();
        result["hands"] = json!(rows);
    }
    print_json(result)
}

fn node_json(tree: &GameTree, id: u32) -> Value {
    let node = tree.node(id);
    let mut data = json!({"id": id, "pot": node.pot, "stacks": node.stacks, "street": node.street});
    match &node.kind {
        NodeKind::Decision { player, actions } => {
            data["kind"] = json!("decision");
            data["player"] = json!(player);
            data["actions"] = json!(actions.iter().map(|a| json!({"token": a.label.token(), "child": a.child})).collect::<Vec<_>>());
        }
        NodeKind::Chance { child_for_card, .. } => {
            data["kind"] = json!("chance");
            data["actions"] = json!((0..NUM_CARDS).filter(|&c| child_for_card[c] != NO_CHILD)
                .map(|c| json!({"token": cards::card_to_string(c as u8), "child": child_for_card[c]})).collect::<Vec<_>>());
        }
        NodeKind::Terminal(Terminal::Fold { folder, .. }) => {
            data["kind"] = json!("fold");
            data["folder"] = json!(folder);
        }
        NodeKind::Terminal(Terminal::Showdown { .. }) => data["kind"] = json!("showdown"),
    }
    data
}

fn print_json(value: Value) -> Result<(), String> {
    serde_json::to_writer(std::io::stdout().lock(), &value).map_err(|e| format!("cannot write JSON: {e}"))
}

struct FileProfile<'a>(&'a [NodeStrategy]);

impl FileProfile<'_> {
    fn at(&self, id: u32) -> &NodeStrategy {
        &self.0[self.0.binary_search_by_key(&id, |s| s.node).expect("validated decision index")]
    }
}

impl StrategyProfile for FileProfile<'_> {
    fn strategy_into(&self, node: u32, out: &mut [f32]) {
        out.copy_from_slice(&self.at(node).strategy);
    }
}

fn reach_at(game: &NlheGame, profile: &FileProfile<'_>, line: &str, player: u8) -> Result<Vec<f32>, String> {
    let tree = game.tree();
    let mut node = tree.root();
    let mut reach = game.root_weights(player).to_vec();
    let mut prefix = String::new();
    for token in line.split(',').map(str::trim).filter(|s| !s.is_empty()) {
        if !prefix.is_empty() {
            prefix.push(',');
        }
        prefix.push_str(token);
        let next = tree.resolve_line(&prefix)?;
        match game.node(node) {
            NodeInfo::Decision { player: actor, num_actions } if actor == player => {
                let action = (0..num_actions).find(|&a| game.child(node, a) == next).ok_or("decision path mismatch")?;
                let offset = action * reach.len();
                for (i, weight) in reach.iter_mut().enumerate() {
                    *weight *= profile.at(node).strategy[offset + i];
                }
            }
            NodeInfo::Chance { num_outcomes } => {
                let edge = (0..num_outcomes).map(|i| game.chance_outcome(node, i)).find(|e| e.child == next).ok_or("chance path mismatch")?;
                reach = edge.parent_of_child[player as usize].iter().map(|&i| reach[i as usize] * edge.weight).collect();
            }
            _ => {}
        }
        node = next;
    }
    Ok(reach)
}
