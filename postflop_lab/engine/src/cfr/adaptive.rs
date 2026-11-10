//! Adaptive policy update derived from the observed V4 decision kernels.

#[derive(Clone, Copy)]
pub(super) struct Round {
    pub(super) stabilizer: f32,
    step: f32,
    average_weight: f32,
}

impl Round {
    pub(super) fn new(iteration: u64, stabilizer: f32) -> Self {
        let step = if iteration <= 30 { 0.24 } else { 0.12 };
        let average_weight = match iteration {
            0..=29 => 0.0,
            30 => 1.0,
            _ => 6.0 / iteration as f32,
        };
        Self { stabilizer, step, average_weight }
    }

    pub(super) fn for_outcome(self, weight: f32) -> Self {
        // The traversal already multiplies counterfactual values by the path's
        // chance probability. Scale epsilon by its square to keep the step
        // equivalent to taking moments in unweighted chance units.
        Self { stabilizer: self.stabilizer * (weight * weight), ..self }
    }
}

pub(super) struct State<'a> {
    pub(super) moment: &'a mut [f32],
    pub(super) average: &'a mut [f32],
    pub(super) policy: &'a mut [f32],
}

pub(super) fn update(
    state: State<'_>,
    values: &[f32],
    node_value: &[f32],
    active: &[f32],
    sum: &mut [f32],
    actions: usize,
    round: Round,
) {
    let width = node_value.len();
    if width == 0 {
        return;
    }
    sum.fill(0.0);
    let uniform = 1.0 / actions as f32;
    for a in 0..actions {
        for i in 0..width {
            if active[i] == 0.0 {
                continue;
            }
            let k = a * width + i;
            let advantage = values[k] - node_value[i];
            let moment = 0.8 * state.moment[k] + (0.2 * advantage) * advantage;
            state.moment[k] = moment;
            let adjustment = round.step * advantage / (moment + round.stabilizer).sqrt();
            let weight = 0.99 * state.policy[k] * (1.0 + adjustment) + 0.01 * state.average[k];
            let corrected = if weight > 0.0 {
                // The float exponent and mantissa give a cheap log2 approximation.
                let log_share = (uniform / weight).to_bits() as f32 * f32::EPSILON - 127.0;
                weight * (1.0 + 0.0034657358 * log_share)
            } else if advantage > 0.0 {
                1.065528e-6
            } else {
                0.0
            };
            state.policy[k] = corrected;
            sum[i] += corrected;
        }
    }
    for a in 0..actions {
        for i in 0..width {
            if active[i] == 0.0 {
                continue;
            }
            let k = a * width + i;
            let next = if sum[i] > 0.0 { state.policy[k] / sum[i] } else { uniform };
            state.policy[k] = next;
            state.average[k] = (1.0 - round.average_weight) * state.average[k] + round.average_weight * next;
        }
    }
}
