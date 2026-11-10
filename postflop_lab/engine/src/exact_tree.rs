//! Sparse betting-only trie. Chance cards do not advance its cursor.

use std::collections::BTreeMap;

pub(crate) struct ExactTree(Vec<BTreeMap<u32, usize>>);

impl ExactTree {
    pub(crate) fn compile(lines: &[Vec<u32>], stack: f64, board_len: usize) -> Result<Self, String> {
        if stack.fract() != 0.0 || stack > u32::MAX as f64 {
            return Err("betting_lines require a positive integer effective_stack".into());
        }
        let stack = stack as u32;
        let mut trie = vec![BTreeMap::new()];
        for (index, line) in lines.iter().enumerate() {
            if line.is_empty() || line.len() > 128 {
                return Err(format!("betting_lines[{index}] must contain 1 to 128 actions"));
            }
            let mut cursor = 0;
            let mut street = board_len;
            let mut actor = 0;
            let mut invested = [0u32; 2];
            let mut acted = false;
            for (step, &amount) in line.iter().enumerate() {
                let facing = invested[1 - actor];
                let min_increment = (facing - invested[actor]).max(1);
                let valid_raise = amount == stack || amount.saturating_sub(facing) >= min_increment;
                if street > 5 || amount < facing || amount > stack || (amount > facing && !valid_raise) {
                    return Err(format!("betting_lines[{index}][{step}]: illegal cumulative commitment {amount}"));
                }
                let call = amount == facing && facing > invested[actor];
                invested[actor] = amount;
                if amount == facing && (call || acted) {
                    street = if amount == stack { 6 } else { street + 1 };
                    actor = 0;
                    acted = false;
                } else {
                    actor = 1 - actor;
                    acted = true;
                }

                let next_index = trie.len();
                let next = *trie[cursor].entry(amount).or_insert(next_index);
                if next == next_index {
                    trie.push(BTreeMap::new());
                }
                cursor = next;
            }
        }
        Ok(Self(trie))
    }

    pub(crate) fn child(&self, cursor: Option<usize>, amount: u32) -> Option<usize> {
        self.0[cursor?].get(&amount).copied()
    }

    pub(crate) fn increases(&self, cursor: Option<usize>, facing: u32) -> impl Iterator<Item = u32> + '_ {
        cursor.into_iter().flat_map(move |idx| {
            self.0[idx].range((std::ops::Bound::Excluded(facing), std::ops::Bound::Unbounded)).map(|(&amount, _)| amount)
        })
    }
}
