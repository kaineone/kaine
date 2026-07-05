# Active-inference benchmark (Nous AIF vs RL)

An **offline** research instrument that tests the paper's falsifiable claim
(KAINE_Paper §6.3, §11): Nous's bounded discrete active-inference decisions are
compared head-to-head against a reinforcement-learning baseline, matched on
observation model and reward, over a suite of bounded discrete tasks. It reports
decision quality, sample efficiency, and the **value of epistemic action**, and
emits a WIN / NULL / NEGATIVE verdict — where **null and negative are
first-class, reportable outcomes**, not harness failures.

The benchmark is headless and synthetic. It constructs discrete POMDP
environments and runs both agents on them. It does **not** boot an entity,
attach to the event bus, or run a cognitive cycle, and it enables no module. The
boot is ethically scarce and never unattended (operator-supervised, or
safety-net-verified in research mode); this instrument never needs it.

## What it compares

- **AIF agent** — drives the *live* Nous pymdp engine
  (`kaine.modules.nous.engine.PymdpEngine`, the same EFE-minimising engine the
  cognitive loop uses). It is handed the env's generative model
  (`A`/`B`/`C`/`D`) and, at each step, runs real pymdp belief updating +
  expected-free-energy policy selection. It carries belief between steps (the
  cue's information persists), which is the machinery under test.
- **RL baseline** — tabular Q-learning with ε-greedy exploration over the
  *observation*–action space. It has **no belief state**: the honest comparison
  asks whether the AIF agent's explicit belief + information-value machinery
  beats a model-free learner that lacks it. Its hyperparameters (α, γ, ε
  schedule) are tuned per task by a small grid on held-out seeds, and the chosen
  values are recorded so the baseline is not strawmanned.

The two agents are **matched**: the same observation model and the same reward,
with the AIF preference vector `C` encoding the identical reward the RL agent
receives. The matching is disclosed in every result record
(`reward_matching`).

## The task suite

1. **`tmaze_epistemic`** (epistemic) — a T-maze (5 locations) whose rewarding arm
   is hidden until the agent visits a *cue* location (the probe) at the
   opportunity cost of a timestep. The reward-maximising policy must probe before
   committing. This is the canonical case (Friston et al.'s T-maze) where EFE's
   information-gain term should produce earlier, more reliable probing than
   ε-greedy. A correctly-wired EFE agent (planning depth `policy_len=4`)
   provably visits the cue first.
2. **`exploitation`** (no hidden state) — a fully observed contextual task with a
   fixed optimal observation→action mapping. Info-seeking has no value here, so
   model-free RL is expected to be competitive. Including it guards the suite
   against being AIF-favourable by construction.

All tasks are parameterised over noise / horizon / info-cost, so sensitivity
runs are possible (e.g. sweeping the T-maze `cue_validity`: the value of
epistemic action falls off as the cue becomes noisier).

## How to run it

```bash
.venv/bin/python -m kaine.evaluation.benchmarks.active_inference
```

Useful flags:

- `--seeds N` — number of evaluation seeds (default 8). The same seeds reproduce
  the verdict.
- `--rl-train-episodes N` — Q-learning training episodes per seed (default 800).
- `--eval-episodes N` — evaluation episodes per seed for both agents.
- `--tasks tmaze_epistemic exploitation` — run a subset.
- `--alpha`, `--min-effect` — verdict significance level and minimum effect size.
- `--out PATH` — JSONL output path.

It prints a summary table and writes seeded, reproducible JSONL (one record per
task × seed × agent, plus a per-task verdict record and a suite summary). Each
record carries the task, seed, agent, the baseline's hyperparameters, the raw
per-episode returns, the computed metrics, and the verdict.

A representative run:

```
task                 epistemic       AIF       RL        p   effect  verdict
----------------------------------------------------------------------------
tmaze_epistemic      True          0.976    0.000    0.007    1.000  WIN
exploitation         False         0.912    0.832    0.049    0.760  WIN
----------------------------------------------------------------------------
SUITE VERDICT: WIN
```

## How to read a null or negative result

The verdict per task is a two-sided Mann–Whitney U test across seeds on the two
agents' decision-quality distributions, gated by a minimum effect size
(rank-biserial `|r|`):

- **WIN** — the AIF agent is significantly higher than the baseline beyond the
  effect-size floor. On the epistemic task this is the paper's hypothesis
  holding: the explicit treatment of information value buys better epistemic
  behaviour.
- **NULL** — the two distributions are not separable beyond the significance
  level and effect size. **This is a real finding, not a failure.** It means
  active inference *matches* but does not beat the baseline on that bounded
  problem. The exploitation task is expected to trend toward NULL once the RL
  baseline is fully converged — that is the point of including it. A NULL on the
  *epistemic* task would be a stronger statement: it would say the information-
  value machinery did not help even where it should, and would motivate the
  complementary reasoning module (paper §6.3).
- **NEGATIVE** — the AIF agent is significantly *lower* than the baseline. Also
  reportable: it would be direct evidence against active inference as a
  sufficient bounded decision engine, and would likewise motivate the
  complementary reasoning module.

The suite verdict aggregates conservatively: a mix of WIN and NEGATIVE across
tasks is surfaced as NULL (the suite as a whole does not support a clean win),
so a single aggregate number can never hide a mixed picture. Always read the
per-task rows.

The benchmark **never manufactures a WIN**: the verdict is computed from the raw
per-seed returns by a standard statistical test. If you change the task
parameters (e.g. drop `cue_validity` on the T-maze), the epistemic advantage can
shrink to NULL — that sensitivity is itself a result worth reporting.
