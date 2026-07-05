## Why

The paper does **not** assume active inference is a general decision engine. It
makes a falsifiable claim and attaches a benchmark to it (KAINE_Paper §6.3, and
a "first empirical priority" in §11): Nous's bounded discrete active-inference
decisions are to be compared against a reinforcement-learning baseline matched
on observation and reward, reporting decision quality, sample efficiency, and
the value of epistemic action. The hypothesis under test is that active
inference's explicit treatment of information value yields better epistemic
behavior on these bounded problems. A **null** result (matches but does not
beat the baseline) and a **negative** result (underperforms) are both
reportable, and either would motivate the complementary reasoning module.

This instrument does not exist. `nous_policy_observer` records the live
policies Nous selects, but there is no RL baseline and no head-to-head
benchmark, so the paper's central active-inference claim cannot currently be
falsified. This change builds the benchmark.

## What Changes

A new **offline** benchmark harness compares Nous's active-inference engine
against an RL baseline on a suite of matched bounded discrete decision tasks.

- It runs **headless and offline** — it constructs synthetic discrete POMDP
  environments and runs both agents on them. It does NOT run inside the live
  cognitive loop and does NOT require an entity boot (the boot is ethically
  scarce and operator-supervised).
- The **active-inference agent** reuses Nous's pymdp generative-model
  construction (the same EFE-minimizing engine the live module uses).
- The **RL baseline** is a standard tabular model-free learner (Q-learning with
  ε-greedy exploration) appropriate to small discrete state spaces — local,
  CPU, no new heavy dependency.
- The two agents are **matched**: the same observation model and the same
  reward, with the AIF preferences (the `C` vector) encoding the identical
  reward the RL agent receives. The matching is documented in each result.
- The **task suite** includes at least one *epistemic* task (hidden state that
  must be probed by an information-seeking action before the rewarding action
  pays off — the canonical case where EFE's epistemic term should help) and at
  least one *pure-exploitation* task (no hidden state — where model-free RL is
  expected to be competitive), so the "value of epistemic action" claim can be
  isolated rather than confounded.
- It reports, per task and aggregated over seeds: **decision quality**
  (asymptotic reward), **sample efficiency** (steps/episodes to a performance
  threshold; regret / area under the learning curve), and **value of epistemic
  action** (relative performance on the epistemic tasks, and a measure of
  info-seeking behavior).
- It emits a **reportable verdict** per task and overall — WIN (AIF beats the
  baseline beyond a significance margin), NULL (statistically matches), or
  NEGATIVE (underperforms) — with null and negative treated as first-class,
  meaningful outcomes, not failures of the harness.
- Results are written as seeded, reproducible JSONL plus a CLI summary.

## Capabilities

### New Capabilities

- `active-inference-benchmark`: an offline harness that benchmarks Nous's
  active-inference engine against an RL baseline on matched bounded discrete
  tasks, reporting decision quality, sample efficiency, and value of epistemic
  action, with a WIN/NULL/NEGATIVE verdict in which null and negative are
  reportable.

### Modified Capabilities

<!-- none -->

## Impact

- **Code (new):**
  - `kaine/evaluation/benchmarks/active_inference/envs.py` — parameterized
    discrete POMDP task library (≥1 epistemic, ≥1 exploitation).
  - `.../rl_baseline.py` — tabular Q-learning (ε-greedy) agent.
  - `.../aif_agent.py` — adapter that runs Nous's pymdp generative model as an
    agent on an env, reusing the live construction path.
  - `.../metrics.py` — decision quality, sample efficiency, epistemic-value,
    and the verdict classifier (significance test over seeds).
  - `.../runner.py` + `__main__.py` — CLI: run all tasks × seeds, write JSONL,
    print a summary table.
- **Code (touch):** factor Nous's generative-model construction so the agent
  adapter can reuse it without duplicating logic (no behavior change to the
  live module).
- **Docs:** a short `docs/` page describing how to run the benchmark and how to
  read a null/negative result.
- **Tests:** deterministic seeded runs; an epistemic task on which a
  correctly-wired EFE agent provably out-info-seeks a no-exploration baseline;
  verdict-classifier unit tests (WIN/NULL/NEGATIVE boundaries); offline /
  no-boot guarantee (no bus, no entity).
- **Safety:** offline research instrument; read-only w.r.t. any running entity;
  enables no module and collects no live cognitive-loop data.
