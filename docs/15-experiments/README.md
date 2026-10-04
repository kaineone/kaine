# Running experiments

KAINE ships with offline research instruments that measure specific claims without booting a live entity. This page covers the controlled instrument runners, the active-inference benchmark, the oscillatory-ablation runner, the workspace-mediation ablation, the shared-seed suite orchestrator, and the multi-seed stability harness. Use them when you need reproducible numbers, a seeded null result, or a check that a live nondeterministic process is stable across seeds.

For the live module-ignition study, see [The module-ignition study](./ignition-study.md). Live runs are recorded by the evaluation sidecar; see [The evaluation sidecar](../17-research-data/README.md).

## What these instruments share

Every instrument here is headless and synthetic. None boots an entity, attaches to a live module, starts a real bus connection, or opens a network connection. Each run pins the global seed with `set_global_seed(seed)` and writes seeded JSONL. WIN, NULL, and NEGATIVE are reportable outcomes in their own right.

## Controlled instrument runners

Three measuring instruments that normally run as passive live sidecars can be promoted to seeded offline experiments of the same shape. The runner is the package [`kaine/evaluation/benchmarks/instrument_runners/`](../../kaine/evaluation/benchmarks/instrument_runners/). Run any one with:

```bash
python -m kaine.evaluation.benchmarks.instrument_runners ab_divergence   --seed 1234 --out ab.jsonl
python -m kaine.evaluation.benchmarks.instrument_runners memory_coherence --seed 1234 --out mem.jsonl
python -m kaine.evaluation.benchmarks.instrument_runners self_model       --seed 1234 --out sm.jsonl
```

Each runner uses a fixed stimulus battery and a shared `Verdict` (WIN / NULL).

### A/B divergence runner

The runner measures the dynamic range of the production `divergence_control` seam. A fixed battery of `(utterance, conditioning)` cases runs through that seam with a deterministic *echo* conditioned-inference client that returns its prompt verbatim. Empty conditioning makes both arms byte-identical, so divergence is approximately 0. Heavy conditioning makes them differ by the conditioning block, so divergence is large.

The verdict is **WIN** when every empty case stays near 0 and every conditioned case exceeds the floor. **NULL** means the meter is flat on that battery.

The embedder is the dependency-free `HashEmbedder` (blake2b token buckets). Blake2b is deterministic across processes, so a seeded run reproduces its metrics across operators.

The runner uses an echo client, not a live language organ. It proves the meter's dynamic range on the production path; measuring a live model's divergence remains the live observer's job.

### Memory coherence runner

The runner measures retrieval advantage. A fixed battery of unique fabricated facts is planted into a real in-memory `MnemosCore` (`FakeEmbedder` + `InMemoryStorage`). A full-system arm, whose answer is derived from what Mnemos returns, is scored against a bare arm with no memory using the production `score_async`.

The verdict is **WIN** only when all three hold:

- full-system retrieval accuracy exceeds the bare arm by at least the floor on the planted battery;
- a never-stored fact yields the honest `NON_RECALL_MARKER` (scored 0, never a confabulated positive);
- the advantage vanishes when the same client runs against an emptied Mnemos, proving the advantage is retrieval and not a hard-coded answer.

**NULL** otherwise.

`kaine.evaluation` does not import `kaine.modules.*` at module top level. The real Mnemos is built by an injected `mnemos_builder` callable; the CLI default uses a lazy function-local import inside `_default_mnemos_builder` so the import never runs at module-import time.

### Self-model accuracy runner

The runner checks whether the Eidolon scorer's fixed-threshold heuristic reproduces the expected score. A fixed battery of `(planted-signal, claim, expected-score)` cases plants known affect/activity signals into a temporary evaluation-logs directory and runs the real `EidolonAccuracyRunner` scorer on a self-description carrying a known claim.

The verdict is **WIN** when the scorer reproduces every expected score. **NULL** otherwise.

A **WIN** here means "the scorer's fixed-threshold arithmetic behaves as specified". It does **not** mean the scorer is calibrated, and it does **not** mean the entity knows itself. The verdict detail, the JSONL `validates` field, and the printed summary all state this. A "no scorable claim" result is recorded as no evidence (aggregate `null`), distinct from a claim scored 0.

### Reproducibility and null results

Given the same `--seed` and battery, each runner reproduces its verdict and its metrics. A **NULL** is a reportable result: the meter was flat, the retrieval advantage did not hold, or the scorer mismatched.

## Active-inference benchmark

The active-inference benchmark is an offline instrument that tests the paper's falsifiable claim: Nous's bounded discrete active-inference decisions are compared head-to-head against a reinforcement-learning baseline, matched on observation model and reward, over bounded discrete tasks. It reports decision quality, sample efficiency, and the value of epistemic action. It emits WIN / NULL / NEGATIVE verdicts.

The benchmark lives in [`kaine/evaluation/benchmarks/active_inference/`](../../kaine/evaluation/benchmarks/active_inference/). It constructs discrete POMDP environments and runs both agents on them. It does not boot an entity, attach to the event bus, or run a cognitive cycle, and it enables no module.

### What the benchmark compares

- **AIF agent** — drives the live Nous [`PymdpEngine`](../../kaine/modules/nous/engine.py), the default expected-free-energy engine in the cognitive loop. (The `[nous].backend = "numpy"` engine is not exercised here.) It receives the environment's generative model (`A`/`B`/`C`/`D`) and, at each step, runs real pymdp belief updating and expected-free-energy policy selection. Belief persists between steps.
- **RL baseline** — tabular Q-learning with ε-greedy exploration over the observation–action space. It has no belief state. Its hyperparameters are tuned per task by a small grid on held-out seeds, and the chosen values are recorded.

The two agents share the same observation model and the same reward. The AIF preference vector `C` encodes the identical reward the RL agent receives. Every result record carries `reward_matching`.

### The task suite

1. **`tmaze_epistemic`** — a 5-location T-maze whose rewarding arm is hidden until the agent visits a cue location at the cost of a timestep. A correctly wired expected-free-energy agent with planning depth `policy_len=4` visits the cue first.
2. **`exploitation`** — a fully observed contextual task with a fixed optimal observation→action mapping. Information-seeking has no value here, so model-free RL is expected to be competitive.

Both tasks are parameterised over noise, horizon, and information cost, so sensitivity runs are possible. For example, sweeping `cue_validity` on the T-maze shows the value of epistemic action falling as the cue becomes noisier.

### How to run the benchmark

```bash
.venv/bin/python -m kaine.evaluation.benchmarks.active_inference
```

Useful flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--seeds N` | `8` | Number of evaluation seeds. |
| `--rl-train-episodes N` | `800` | Q-learning training episodes per seed. |
| `--eval-episodes N` | `100` | Evaluation episodes per seed for both agents. |
| `--tasks` | both | Run a subset, e.g. `tmaze_epistemic exploitation`. |
| `--alpha` | `0.05` | Verdict significance level. |
| `--min-effect` | `0.3` | Minimum effect size. |
| `--out PATH` | `data/evaluation/benchmarks/active_inference.jsonl` | JSONL output path. |

The benchmark prints a summary table and writes seeded, reproducible JSONL: one record per task × seed × agent, plus a per-task verdict record and a suite summary. Each record carries the task, seed, agent, the baseline's hyperparameters, raw per-episode returns, computed metrics, and the verdict.

### How to read a null or negative result

The per-task verdict is a two-sided Mann–Whitney U test across seeds on the two agents' decision-quality distributions, gated by a minimum effect size (rank-biserial `|r|`).

- **WIN** — the AIF agent is significantly higher than the baseline beyond the effect-size floor.
- **NULL** — the two distributions are not separable beyond the significance level and effect size. This is a real finding, not a failed run. On the exploitation task it is expected once the RL baseline is fully converged. A NULL on the epistemic task would say the information-value machinery did not help where it should.
- **NEGATIVE** — the AIF agent is significantly lower than the baseline. This would be direct evidence against active inference as a sufficient bounded decision engine.

Both NULL and NEGATIVE on the epistemic task would motivate the complementary reasoning module (KAINE_Paper §6.3).

The suite verdict aggregates conservatively: a mix of WIN and NEGATIVE across tasks is surfaced as NULL. Always read the per-task rows. The benchmark never manufactures a WIN; the verdict is computed from raw per-seed returns by a standard test.

## Oscillatory ablation

The oscillatory-ablation runner is a controlled offline instrument that measures whether the oscillatory coherence layer changes [global-workspace selection](../08-cognitive-cycle/global-workspace.md). It runs the cognitive cycle twice under identical conditions and toggles only the coherence layer, then emits WIN / NULL / NEGATIVE.

The runner lives in [`kaine/evaluation/benchmarks/oscillatory_ablation/`](../../kaine/evaluation/benchmarks/oscillatory_ablation/). It drives only the cycle engine and Syneidesis over a scripted in-memory bus. It does not boot an entity, attach to live modules, start a real bus connection, or open a network connection.

### The determinism guarantee

Both arms run with the same `set_global_seed(seed)`, the same fixed scripted stimulus, and `deterministic=True` (logical timestamps, canonical within-tick ordering). Under those conditions a run is bit-for-bit reproducible.

The enabled arm carries a real `CoherenceScorer` with a configurable precision gain `[coherence_floor, coherence_ceiling]`. The disabled arm passes `coherence=None`, the layer-absent baseline. A test asserts the disabled arm is bit-for-bit equal to an independently built layer-absent cycle. Any difference between the two trajectories is attributable to the coherence layer alone.

### The scripted stimulus

Four sources emit one event per tick:

| Source | Phase relation | Raw salience |
| --- | --- | --- |
| `lock_a`, `lock_b` | phase-locked, PLV → 1 | `0.40` |
| `drift_a`, `drift_b` | desynchronized, low PLV | `0.60` |

With the layer absent, the higher-raw-salience drift sources rank first on every tick. With the layer enabled, the phase-locking-value sliding windows fill over the first several ticks. Once they do, the desynchronized sources' coherence factor collapses toward the floor while the phase-locked sources' rises toward the ceiling, so a phase-locked source overtakes a drift source.

### Effect metrics and verdict

| Metric | Meaning |
| --- | --- |
| `selection_divergence_fraction` | Fraction of ticks where the top selected entry differs between arms. `0` means the layer never changed the winner. |
| `mean_ranking_divergence` | Mean normalised Spearman footrule distance between the arms' per-tick salience rankings. |
| `coherence_alignment_delta` | Fraction of ticks where the enabled arm's top source is phase-coherent minus the same fraction for the disabled arm. Positive means enabling the layer moved selection toward coherent coalitions; negative means it moved away. It is `0` on the neutral battery. |

The verdict is three-way:

- **NULL** — `selection_divergence_fraction` is at or below `--min-effect`. The layer made no meaningful change.
- **NEGATIVE** — the change is meaningful, but adverse: `coherence_alignment_delta` is at or below `-min_alignment` (selection re-ranks away from the coherent coalition).
- **WIN** — the change is meaningful and not adverse.

All three are reportable outcomes. A correctly labelled battery can only return WIN or NULL, because the coherence layer is strictly monotone in PLV. NEGATIVE is reachable only through the `mislabeled` adversarial battery.

### The mislabeled adversarial battery

`--stimulus mislabeled` runs a battery where the `coherent=True` ground-truth label is placed on a high-salience source that is not the most phase-locked, while the truly synchronized source is labelled `coherent=False`. The honest coherence layer still promotes the truly synchronized source over the decoy, producing a genuinely negative `coherence_alignment_delta`. This probes a label/reality mismatch: the layer tracks a coherence that the ground-truth label disagrees with.

### Running the ablation

```bash
python -m kaine.evaluation.benchmarks.oscillatory_ablation \
    --seed 1234 --ticks 16 \
    --coherence-floor 0.05 --coherence-ceiling 8.0 --plv-window 12 \
    --min-effect 0.10 --stimulus engineered \
    --out data/evaluation/benchmarks/oscillatory_ablation.jsonl
```

Defaults match the values above: `--seed 1234`, `--ticks 16`, `--coherence-floor 0.05`, `--coherence-ceiling 8.0`, `--plv-window 12`, `--min-effect 0.10`, and `--stimulus engineered`. The other batteries are `neutral` (no coherence contrast) and `mislabeled`.

The same seed reproduces the verdict and effect metrics exactly. Only the wall-clock `ts` field differs between runs. The CLI prints the verdict plainly and writes a JSONL record with per-arm trajectory digests, the effect, and the verdict.

### Limitation

The stimulus is synthetic, not live perception. The runner exercises selection and coherence under controlled phase schedules; it does not claim a magnitude for live operation.

## Workspace-mediation ablation

The workspace-mediation ablation is the paper's primary offline experiment. It compares the system as built — a competitive global workspace selecting a coalition — against a matched flat fan-in control where the same candidates are handed directly to Chronos and the language organ. It runs the real Soma and Chronos modules head-to-head under a fixed seed and reports WIN / NULL / NEGATIVE / UNDERPOWERED.

The runner lives in [`kaine/evaluation/benchmarks/workspace_mediation_ablation/`](../../kaine/evaluation/benchmarks/workspace_mediation_ablation/). It drives Soma and Chronos by hand over an in-memory bus. It does not boot an entity, start a real bus connection, or open a network connection.

### The two arms

- **Workspace-on** — each tick, Syneidesis competitively selects a coalition of candidate events above `top_k`. Chronos predicts that coalition, and the coalition conditions the language organ.
- **Workspace-off** — the same candidates are handed to Chronos and the organ as a flat snapshot, with no scoring, top-k, inhibition, or competition.

Both arms receive the same information; they differ only in how that information is structured. Soma runs against a scripted `MetricsReader` and an injected clock. Both Chronos arms are built from the same seeds, so they start identical and diverge only because they receive different snapshots. Soma's error series is run once and shared, because Soma does not read the broadcast.

### Measures and verdict

- **coupling_delta** (primary) — the mean sliding-window Pearson correlation between Soma's and Chronos's error series, workspace-on minus workspace-off. The thesis predicts a positive delta: competitive selection concentrates the salient signal into the coalition Chronos predicts, coupling the two modules more than flat fan-in does.
- **coalition_entropy** — Shannon entropy of the on-arm selected-source sequence. A non-trivial workspace selects different sources as state changes.
- **conditioning_divergence** — cosine distance between the two arms' rendered workspace content. With a greedy organ, this is a deterministic offline proxy for output divergence.

The verdict is three-way:

- **WIN** — `coupling_delta` is positive and above `min_effect`, with non-trivial selection.
- **NULL** — `coupling_delta` is within `min_effect` (the fan-in prompt-assembler outcome).
- **NEGATIVE** — `coupling_delta` is at or below `-min_effect` (competitive mediation adverse to the thesis).
- **UNDERPOWERED** — Soma never enters the coalition, or the correlation is undefined. This is distinct from NULL.

### Running the ablation

```bash
python -m kaine.evaluation.benchmarks.workspace_mediation_ablation \
    --seed 1234 --ticks 24 --top-k 2 --window 6 \
    --min-effect 0.15 --stimulus soma_salient \
    --out data/evaluation/benchmarks/workspace_mediation_ablation.jsonl
```

Defaults match the values above: `--seed 1234`, `--ticks 24`, `--top-k 2`, `--window 6`, `--min-effect 0.15`, and `--stimulus soma_salient`. The other batteries are `neutral` (quiet substrate, NULL/underpowered reachable) and `decoupled` (control where coupling should be weak).

The same seed reproduces the verdict and the JSONL record. Each record carries the per-arm trajectories, the effect metrics, and the verdict.

## Shared-seed suite orchestrator

The suite orchestrator is an offline entry point that runs the eight benchmarks under one master seed, derives an independent child seed for each experiment, and emits a combined report with per-experiment verdicts and a family-wise Holm-Bonferroni correction.

Run it with:

```bash
python -m kaine.evaluation.benchmarks.suite
```

Useful flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--seed N` | `1234` | Master seed for the whole suite. |
| `--alpha` | `0.05` | Family-wise significance level. |
| `--fast` | off | Reduced subset for a quick smoke run. |
| `--out PATH` | `data/evaluation/benchmarks/suite.jsonl` | Combined report path. |

### What the suite runs

The eight experiments are:

1. **active-inference** — the AIF-vs-RL benchmark, producing one p-value per task.
2. **oscillatory_ablation** — coherence layer on vs off.
3. **ab_divergence** — controlled dynamic-range battery.
4. **memory_coherence** — retrieval-advantage battery.
5. **self_model** — fixed-threshold scorer battery.
6. **multi_seed_stability** — the longitudinal control machinery, run offline.
7. **enforcement_red_team** — the real enforcement layer against a case battery.
8. **workspace_mediation** — competitive workspace vs flat fan-in, the paper's primary experiment; produces a sign-test p-value over per-seed coupling deltas.

The orchestrator calls `set_global_seed(master_seed, deterministic=True)` once at the start to request GPU/cuDNN determinism on the offline path. It then spawns independent child seeds per experiment via `numpy.random.SeedSequence.spawn` so each experiment stays reproducible. The active-inference benchmark receives its child seed through `BenchmarkConfig.master_seed`, including the env/RL RNG.

### Family-wise correction

The suite collects p-values from the p-value-producing experiments:

- **active-inference** — one p-value per task;
- **workspace_mediation** — the sign-test p-value that the median per-seed `coupling_delta` is greater than 0.

It applies the Holm-Bonferroni correction across those p-values at level `alpha` and reports the raw p-value, Holm-corrected p-value, and a reject/no-reject decision for each. Each experiment's own raw verdict is preserved unchanged; the family-wise view is an additional layer.

Individuation evidence is not one of the eight offline experiments because it requires a live being. It is collected by the cycle's individuation producer and stored as encrypted welfare evidence under `state/individuation/`.

### Scope

Every experiment in the suite runs offline with deterministic or echo clients, in-memory stores, scripted buses, and the real headless enforcement layer. Nothing boots an entity, enables a module, or opens a network connection.

## Longitudinal stability

The multi-seed stability harness is the control for cases where bit-for-bit determinism is not enforced. Single-seed experiments rely on the determinism guarantee: same seed, same input, and `deterministic=True` produce identical results. Live longitudinal runs are genuinely stochastic. The control there is the multi-seed analog: run the same configuration under several seeds and assert that the summary statistics are stable.

The harness lives in [`kaine/experiment/stability.py`](../../kaine/experiment/stability.py). It is boundary-neutral: it imports nothing from `kaine.evaluation`, so both the core cognitive cycle and the evaluation sidecar may use it. It takes a callable, not an experiment object.

### What the harness computes

`run_multi_seed(run_fn, seeds, *, metric_fn, tolerance=0.0)` runs `run_fn(seed)` once per seed, pinning `set_global_seed(seed)` before each call. It pulls the per-seed headline metric with `metric_fn` and returns a `StabilityReport`:

| Field | Meaning |
| --- | --- |
| `seeds` | The seeds run, in order. |
| `values` | Per-seed headline metric, aligned with `seeds`. |
| `mean` / `std` | Mean and population standard deviation of `values`. |
| `cv` | Coefficient of variation = `std / \|mean\|`. |
| `verdict_counts` | Distribution of verdict outcomes across seeds, e.g. `{"WIN": 5}`. |
| `tolerance` | The CV tolerance the verdict was evaluated against. |
| `stable` | Whether the ensemble passed the stability criterion. |

`verdict_unanimous` and `reasons()` explain the verdict. `to_dict()` is JSON-safe: an infinite CV serialises as `null` with a `cv_is_infinite` flag.

### The stability criterion

The ensemble is `stable` only when both hold:

1. the metric's coefficient of variation is within `tolerance` (`cv <= tolerance`); an infinite CV is never within a finite tolerance, and
2. the verdict is unanimous across seeds.

Verdict disagreement makes the ensemble unstable even when the metric CV is within tolerance, because a flipped WIN/NULL is a qualitative instability the scalar dispersion would hide.

`assert_stable(...)` runs the ensemble and raises `StabilityError` with `report.reasons()` unless it is stable.

### Demonstration with the ablation runner

[`kaine/evaluation/benchmarks/oscillatory_ablation/stability.py`](../../kaine/evaluation/benchmarks/oscillatory_ablation/stability.py) runs the controlled oscillatory-ablation runner across K seeds and reports stability of its `selection_divergence_fraction` plus verdict unanimity:

```python
from kaine.evaluation.benchmarks.oscillatory_ablation.stability import run_ablation_stability

report = run_ablation_stability([1234, 2025, 7], ticks=16, tolerance=0.01)
assert report.stable
print(report.verdict_counts)  # {"WIN": 3}
print(report.cv)              # 0.0 — effect identical on every seed
```

The ablation runner is deterministic per seed and its scripted stimulus is seed-independent, so the effect is identical across seeds and the WIN verdict is unanimous. This is the strongest possible demonstration that the experiment is seed-robust.

### Scope

The harness is the right instrument for genuinely nondeterministic live longitudinal experiments: raise `tolerance` to whatever spread the live process admits and run more seeds. As exercised in this codebase it runs offline deterministic runners, so it proves the stability machinery is correct and those offline experiments are seed-robust. It does not itself collect weeks-long live longitudinal data; that is the operator's job once an entity is running.

## See also

- [The module-ignition study](./ignition-study.md) — the live study for module ignition and voice alignment.
- [The evaluation sidecar](../17-research-data/README.md) — how live runs are recorded.
- [Research event streams](../17-research-data/event-streams.md) — the raw event data behind live analysis.
- [Research participation](../17-research-data/participation.md) — submitting results back to the project.
- [For researchers](../14-for-researchers.md) — how to reproduce and cite KAINE results.
- [Nous](../09-modules/nous.md) — the module whose engine the active-inference benchmark exercises.
