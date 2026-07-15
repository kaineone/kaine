# Process: Research Testing Framework (Three Layers)

The eight controlled experiments do not earn trust by running — they earn it by
being *validated*. KAINE's research-testing framework has three layers, each
answering a different "why should I believe this number?" question:

1. **Instrument validation** — does the meter actually measure what it claims?
   (a negative and a positive control per meter)
2. **Experiment implementation** — is a single run trustworthy? (seed determinism,
   condition isolation)
3. **Data integrity** — is the run's record whole and physically plausible? (run
   identity, completeness gating, schema/range sweep, freeze annotation)

Together with the unsupervised [research operation](research-operation.md), these
layers are what let an offline verdict stand as evidence rather than assertion.

Related: [research-operation.md](research-operation.md) ·
[controlled-experiment-runners.md](controlled-experiment-runners.md) ·
[oscillatory-ablation.md](oscillatory-ablation.md) ·
[active-inference-benchmark.md](active-inference-benchmark.md) ·
[longitudinal-stability.md](longitudinal-stability.md) ·
[enforcement-red-team.md](../enforcement-red-team.md) ·
[run-identity.md](run-identity.md) · [run-admissibility.md](run-admissibility.md)

---

## Layer 1 — Instrument validation (controls per meter)

Every meter ships with a **negative control** (a condition where the meter must
read ~0; a phantom reading there invalidates everything the meter says) and a
**positive control** (a known-large condition the meter must register). A meter
with both controls is *falsifiable* rather than taken on faith.

- **A/B divergence.** Negative control: with empty conditioning both arms run an
  identical prompt → identical output → divergence ~0 (embedder-agnostic, always
  on). Positive control: a known-large conditioning difference must read large
  (structural claim always-on with the lexical embedder; the semantic claim
  validated with the sentence-transformer embedder when present, skipped — never
  faked — when absent). Both arms run through the one production
  `divergence_control` seam, so any divergence is attributable to conditioning
  alone. See [evaluation-sidecar.md](evaluation-sidecar.md#controls-instrument-validation).
- **Memory coherence.** Positive control: a unique fabricated marker the bare
  model cannot know is planted into a real in-memory Mnemos; the full-stack arm
  recalls it, the bare arm cannot, **and** the advantage vanishes against an
  emptied Mnemos (proving retrieval, not a hard-coded answer). Negative control: a
  never-stored fact yields the honest non-recall sentinel, scored exactly 0 —
  confabulation can never read as a false positive. See
  [evaluation-sidecar.md](evaluation-sidecar.md#memory-probe-ground-truth-controls).
- **Oscillatory ablation.** The "disabled" arm is asserted bit-for-bit identical
  to an independently-built layer-absent cycle, so the on-vs-off difference is
  *verified* to be the layer, not assumed. See
  [oscillatory-ablation.md](oscillatory-ablation.md).
- **Self-model accuracy.** Validates the scorer's arithmetic against a battery of
  known `(signal, claim, expected-score)` cases — a **fixed-threshold heuristic**
  (hand-chosen thresholds, not fitted), explicitly *not* calibration and *not*
  predicted-vs-actual self-knowledge. See
  [controlled-experiment-runners.md](controlled-experiment-runners.md#self-model-accuracy-runner).
- **Active-inference benchmark.** Includes a fully-observed `exploitation` task
  where info-seeking has no value, so the suite is not AIF-favourable by
  construction; the RL baseline is hyperparameter-tuned per task so it is not
  strawmanned. See [active-inference-benchmark.md](active-inference-benchmark.md).
- **Enforcement red-team.** Drives the *real* enforcement components (Praxis gate,
  Syneidesis/Volition inhibition, audit log), so a PASS means the architectural
  layer actually blocked the action. See
  [enforcement-red-team.md](../enforcement-red-team.md).
- **Workspace-mediation ablation (the primary experiment).** The off arm is a
  fair null, not a crippled one: the rendering budget (max events, char budget)
  is matched across arms, and the off arm's modules keep running their real
  forward models and publishing real, non-degenerate prediction errors — a WIN
  cannot come from starving the control. A neutral, non-engineered stimulus
  battery and real non-zero minimum-effect thresholds keep NULL and NEGATIVE
  genuinely reachable outcomes, so the runner is not a wiring test rigged to
  always win. See `kaine/evaluation/benchmarks/workspace_mediation_ablation/`.

## Layer 2 — Experiment implementation (determinism + isolation)

A single run is trustworthy when its result is a function of the experiment, not
of the random universe it happened to land in:

- **Seed determinism.** Each runner calls `set_global_seed(seed)` at the start of
  a run; the same seed reproduces the verdict **and** the metrics, not just the
  verdict. The offline runners drive deterministic / echo clients and in-memory
  stores so reproducibility is exact. See
  [run-identity.md](run-identity.md#global-seed).
- **Condition isolation.** Where two arms are compared, they differ in exactly one
  controlled variable and share everything else — the same model, persona, prompt
  path, seed, and (for the oscillatory and workspace-mediation ablations)
  `deterministic=True` with a logical clock and canonical within-tick ordering, so
  the only difference is the variable under test — for the workspace-mediation
  ablation, whether the organ and Chronos are conditioned by the
  competitively-selected coalition or by a matched-budget flat fan-in of the same
  module outputs. See [run-identity.md](run-identity.md#deterministic-mode) and
  [oscillatory-ablation.md](oscillatory-ablation.md#the-determinism-guarantee-why-the-difference-is-the-layer).
- **First-class null results.** A NULL / NEGATIVE / unstable outcome is a real,
  reportable finding, never a harness failure. The verdict is computed from raw
  per-seed data by a standard test; the harness never manufactures a WIN.

For the genuinely nondeterministic **live longitudinal** case — where real timing
and real perception are stochastic and bit-for-bit determinism cannot hold — the
control is the multi-seed analog: run the same configuration under several seeds
and assert the summary statistics are stable and the verdict does not flip. See
[longitudinal-stability.md](longitudinal-stability.md).

## Layer 3 — Data integrity (the run record)

A correct meter on a corrupt record proves nothing. This layer guarantees the
record itself:

- **Run identity.** One seed, one `run_id`, a per-sink monotonic `seq` stamped on
  every durable record, and a manifest (seed, git sha, model ids, config digest).
  See [run-identity.md](run-identity.md).
- **Completeness gating.** A run is admissible only when ticks are contiguous,
  each stream's `seq` is contiguous (a gap means a silently dropped record), every
  expected stream produced records, and there are no parse errors. See
  [run-admissibility.md](run-admissibility.md#completeness-gating).
- **Log range sweep.** Every logged number is re-checked against a declared schema
  of physically-possible ranges; an out-of-range value is a violation, fail-closed.
  See [run-admissibility.md](run-admissibility.md#log-range-validation).
- **Freeze / interruption annotation.** A Spot incident or an autonomous
  preservation/welfare action is published as a structured event and written to a
  durable, never-auto-deleted log joined to the run by `run_id`, so an analyst can
  see that a run was interrupted and locate it by cycle position. See
  [../operations.md](../operations.md#durable-incident-log).

## How the layers map to the eight experiments

| Experiment | Layer 1 control | Layer 2 | Layer 3 |
| --- | --- | --- | --- |
| Active-inference vs RL | `exploitation` guard task; tuned RL baseline | seeded, matched models | seed/manifest |
| Oscillatory ablation | disabled arm = layer-absent (bit-for-bit) | `deterministic=True`, single-variable | seed/manifest |
| A/B divergence | empty-conditioning ~0; large-conditioning large | seeded echo client; one production seam | run identity + sweep |
| Memory coherence | planted marker; emptied-Mnemos vanish; non-recall sentinel | seeded; real in-memory Mnemos | run identity + sweep |
| Self-model accuracy | known `(signal, claim, expected)` battery | seeded | run identity |
| Multi-seed stability | (is itself the live control) | multi-seed CV + verdict unanimity | run identity |
| Enforcement red-team | real enforcement components | deterministic offline cases | durable audit log |
| Workspace-mediation ablation (primary) | matched rendering budget; non-degenerate off arm; neutral battery + real thresholds | `deterministic=True`, matched seed/stimulus/modules, single-variable (workspace on vs. off) | seed/manifest |
