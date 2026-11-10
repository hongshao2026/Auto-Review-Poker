//! `solver`: command-line front end for the postflop solving engine.

mod show;
mod solve;
mod query;

use std::process::ExitCode;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(
    name = "solver",
    version,
    about = "Heads-up NLHE postflop GTO solver, for chipEV or tournament ICM"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Solve a spot with Discounted CFR and optionally save it. Pass `--tournament` to
    /// score it in tournament equity (ICM) instead of chips.
    Solve(solve::SolveArgs),
    /// Inspect a saved solution without re-solving.
    Show(show::ShowArgs),
    /// Inspect a configuration's tree without training a strategy.
    Tree(query::TreeArgs),
    /// Read a saved solution and emit a node, per-combo policy and optional EV as JSON.
    Query(query::QueryArgs),
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let result = match cli.command {
        Command::Solve(args) => solve::run(args),
        Command::Show(args) => show::run(args),
        Command::Tree(args) => query::tree(args),
        Command::Query(args) => query::query(args),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
