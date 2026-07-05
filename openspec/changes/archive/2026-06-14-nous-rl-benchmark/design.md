## Context

The paper scopes active inference deliberately (KAINE_Paper §2.3, §3.4.2 Nous):
discrete-state active inference does not scale to large state spaces, so Nous is
applied only to bounded discrete sub-problems, and the *sufficiency* of active
inference is treated as a hypothesis with a falsification condition — a
head-to-head against RL on exactly those bounded problems (§6.3). The honest
outcome may be null or negative; the benchmark must make that outcome legible
rather than burying it.

## Goals / Non-goals

- **Goal:** a reproducible, offline instrument that produces decision-quality,
  sample-efficiency, and epistemic-value numbers for Nous-AIF vs an RL baseline
  on matched tasks, plus a WIN/NULL/NEGATIVE verdict.
- **Goal:** isolate the *value of epistemic action* (the paper's specific
  hypothesis) with at least one task where info-seeking is required and one
  where it is not.
- **Non-goal:** a general RL framework or deep RL. Tabular Q-learning is the
  conventional, transparent baseline for small discrete POMDPs; deep RL would
  add dependencies and obscure the comparison.
- **Non-goal:** running inside the live cognitive loop or requiring an entity
  boot. The harness is standalone and synthetic.

## Decisions

### Environment interface

A minimal discrete-POMDP interface: `reset() -> obs`, `step(action) -> (obs,
reward, done, info)`, with known `num_states`, `num_obs`, `num_actions`, an
observation model `A`, transition model `B`, and a reward function expressible
both as scalar reward (for RL) and as a preference vector `C` over observations
(for AIF). Providing `A`/`B` to the AIF agent is the matched-information
assumption: both agents see the same observation structure; AIF additionally
gets the generative model it is entitled to (that *is* the thing under test).

### Task suite (initial)

1. **Epistemic task** — a hidden context variable (e.g. which of two arms is
   rewarding) is unobservable until a dedicated *probe* action reveals it at a
   small cost. The reward-maximizing policy must probe before committing. This
   is where EFE's epistemic (information-gain) term should produce earlier,
   more reliable probing than ε-greedy.
2. **Exploitation task** — fully observed, no hidden state; the optimal policy
   is a fixed mapping. Model-free RL is expected to be competitive or better;
   including it guards against an AIF-favorable suite.
3. (Extensible) further parameterized tasks (noise level, horizon, cost of
   information) so sensitivity can be reported.

### AIF agent

Reuse Nous's pymdp construction (refactored into a reusable factory that both
the live module and the benchmark call), then drive it on the env: at each
step, infer beliefs from the observation, select the EFE-minimizing policy,
emit the first action. The `C` vector encodes the env reward as
log-preferences. No live bus, no intents — the adapter calls the engine
directly.

### RL baseline

Tabular Q-learning over the (belief-free) observation–action space with
ε-greedy exploration and a decaying ε schedule. For partially observed tasks
the baseline acts on raw observations (it has no belief state) — this is the
honest baseline: the comparison asks whether AIF's explicit belief + info-value
machinery beats a model-free learner that lacks it. Hyperparameters (α, γ, ε
schedule) are tuned per task by a small grid on held-out seeds and the chosen
values are recorded, so the baseline is not strawmanned.

### Metrics

- **Decision quality:** mean reward over the last `k` evaluation episodes
  (greedy/zero-ε for RL; standard policy for AIF).
- **Sample efficiency:** steps (RL) to reach a fraction of optimal return;
  AIF needs no learning episodes for the decision policy, so efficiency is
  reported as "steps-to-competence" for RL against AIF's from-model competence,
  and as cumulative regret vs the env's optimal policy for both.
- **Value of epistemic action:** on epistemic tasks, the rate and timing of the
  probe action, and the performance gap on epistemic vs exploitation tasks.
- **Verdict:** per task, compare the two agents' decision-quality distributions
  across seeds with a permutation / Mann–Whitney test; WIN if AIF is higher
  beyond the significance level and a minimum effect size, NEGATIVE if lower,
  NULL otherwise. Aggregate verdict summarizes the suite. The classifier is the
  same shape of statistical instrument used by the individuation boundary, for
  consistency.

### Reproducibility

Every run is seeded; JSONL records carry the task, seed, agent, hyperparameters,
raw per-episode returns, and computed metrics. Re-running with the same seeds
reproduces the verdict.

## Risks / trade-offs

- A favorable or unfavorable suite biases the verdict. Mitigation: include the
  exploitation task by construction, record hyperparameter tuning for the
  baseline, and report per-task results so a single aggregate can't hide a
  mixed picture.
- pymdp construction coupling: refactoring the live factory risks touching Nous.
  Mitigation: pure extract-and-reuse with the live module's tests unchanged.

## Migration

Additive only — a new `kaine/evaluation/benchmarks/` package and a Nous factory
extraction. No config defaults change; nothing runs unless the CLI is invoked.
