# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## Why

The experiment foundation gives offline experiments a *bit-for-bit* determinism
guarantee: same seed + same input + `deterministic=True` ⇒ identical trajectory,
identical verdict. That guarantee is what makes a single-seed verdict trustworthy
— there is no run-to-run noise to wash out.

But determinism is not always enforceable. The longitudinal / live case — weeks of
a booted entity, genuinely stochastic timing, real perception — has no bit-for-bit
guarantee to lean on. There the methodological control is the **multi-seed
analog**: run the SAME configuration under several seeds and assert that the
SUMMARY STATISTICS are stable across them. If the headline metric's spread is
small and the verdict does not flip, nondeterminism has washed out — N is large
enough that the result is robust to the seed. If it is not, the experiment is
under-powered or genuinely unstable, which is itself a reportable finding.

Today there is no reusable instrument for this. Each experiment that wants to
report seed-robustness would re-implement mean/std/CV and a verdict tally. The
individuation boundary already computes a seeded ensemble's `null_mean`/`null_std`;
this change factors the same statistical posture into a general, boundary-neutral
harness so any experiment can assert stability the same way.

## What Changes

A new **boundary-neutral** harness `kaine/experiment/stability.py` (no dependency
on `kaine.evaluation`, like the rest of `kaine/experiment/`, so both the core
cycle and the evaluation sidecar may use it):

- `run_multi_seed(run_fn, seeds, *, metric_fn, tolerance=0.0)` runs `run_fn(seed)`
  for each seed (pinning `set_global_seed(seed)` before each call), collects the
  per-seed headline metric via `metric_fn`, and returns a `StabilityReport`:
  `seeds`, `values`, `mean`, `std`, `cv` (coefficient of variation = `std/|mean|`),
  `verdict_counts` (distribution of verdict outcomes across seeds), `tolerance`,
  and `stable: bool`. It also exposes `verdict_unanimous` and `reasons()`.
- **Stability criterion:** the ensemble is `stable` iff the metric's CV is within
  `tolerance` AND the verdict is unanimous across seeds (a metric-only ensemble
  has no verdict to disagree on and is vacuously unanimous). Verdict disagreement
  makes the ensemble unstable even when the metric CV is within tolerance, because
  a flipped WIN/NULL is a qualitative instability the scalar dispersion hides.
- `assert_stable(...)` raises a `StabilityError` (carrying `report.reasons()`)
  unless the ensemble is stable — honest failure over a fake pass.

The summary statistics mirror `kaine.evaluation.individuation` (`_mean`/`_std`),
so the two instruments report dispersion the same way.

It is **demonstrated on a real experiment**: a thin adapter
`kaine/evaluation/benchmarks/oscillatory_ablation/stability.py` runs the
oscillatory-ablation runner across K seeds and reports stability of its
selection-divergence-fraction effect plus verdict unanimity. (The adapter lives
under `kaine/evaluation/` — where the experiments live and where importing the
boundary-neutral `kaine.experiment` is allowed — never the reverse.)

## Capabilities

### Modified Capabilities

- `experiment-foundation`: ADD a reusable multi-seed stability harness — the
  longitudinal / multi-run control. It runs an experiment across several seeds and
  reports summary statistics (mean, std, coefficient of variation, verdict
  distribution) and a stability verdict (stable when variation is within tolerance
  and verdicts are unanimous), as the multi-seed analog of the bit-for-bit
  seed-determinism guarantee.

## Impact

- **Code (new):**
  - `kaine/experiment/stability.py` — the harness (`run_multi_seed`,
    `assert_stable`, `StabilityReport`, `StabilityError`).
  - `kaine/evaluation/benchmarks/oscillatory_ablation/stability.py` — the
    demonstration adapter (`run_ablation_stability`).
- **Code (touch):** `kaine/experiment/__init__.py` re-exports the harness symbols.
  No cycle/workspace internals change.
- **Docs:** `docs/processes/longitudinal-stability.md` — what the harness is, the
  stability criterion, how to run the ablation demonstration, and the honest scope
  limitation.
- **Tests:** harness unit tests (low-variance → stable, high-variance → unstable
  with reasons, verdict disagreement → not unanimous → unstable, infinite-CV edge,
  `assert_stable`, global-seed pinning); a boundary test asserting the harness does
  not import `kaine.evaluation`; an integration test running the ablation adapter
  across K seeds → stable report (unanimous WIN, effect CV within tolerance).
- **Safety:** offline analysis instrument; reads no entity interior; enables no
  module, boots no entity, opens no network connection.

## Limitations

This harness is the right instrument for genuinely nondeterministic *live*
longitudinal experiments — raise the tolerance to whatever spread the live process
admits and run more seeds. As exercised here it runs *offline* runners that are
deterministic per seed, so it proves the stability *machinery* is correct and
demonstrates those offline experiments are seed-robust (the ablation effect is in
fact identical across seeds because its scripted stimulus is seed-independent). It
does NOT itself collect weeks-long live longitudinal data — that is the operator's
job once an entity is running; this is the analysis instrument waiting for that
data. The scope is stated honestly so no one mistakes a clean offline demonstration
for a live-stability claim.
