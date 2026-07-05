# Multi-seed stability (the longitudinal / multi-run control)

A reusable, offline analysis instrument for the case where bit-for-bit
determinism is NOT enforced. The experiment foundation gives single-seed
experiments a determinism guarantee — same seed + same input +
`deterministic=True` ⇒ identical verdict — and that is what makes one run
trustworthy. The longitudinal / live case has no such guarantee: real timing and
real perception are genuinely stochastic. The control there is the **multi-seed
analog**: run the SAME configuration under several seeds and assert the SUMMARY
STATISTICS are stable across them. If the headline metric's spread is small and
the verdict does not flip, nondeterminism has washed out — N is large enough that
the result is robust to the seed.

The harness lives in `kaine/experiment/stability.py`. Like the rest of
`kaine/experiment/` it is **boundary-neutral**: it imports nothing from
`kaine.evaluation`, so both the core cognitive cycle and the evaluation sidecar
may use it. It takes a callable, not an experiment object.

## What it computes

`run_multi_seed(run_fn, seeds, *, metric_fn, tolerance=0.0)` runs `run_fn(seed)`
once per seed (pinning `set_global_seed(seed)` before each call), pulls the
per-seed headline metric via `metric_fn`, and returns a `StabilityReport`:

| Field            | Meaning                                                       |
| ---------------- | ------------------------------------------------------------- |
| `seeds`          | The seeds run, in order.                                      |
| `values`         | The per-seed headline metric (aligned with `seeds`).          |
| `mean` / `std`   | Mean and population std of `values` (mirrors individuation).  |
| `cv`             | Coefficient of variation = `std / \|mean\|` (scale-free).     |
| `verdict_counts` | Distribution of verdict outcomes across seeds, e.g. `{WIN:5}`.|
| `tolerance`      | The CV tolerance the verdict was evaluated against.           |
| `stable`         | Whether the ensemble passed the stability criterion.          |

`verdict_unanimous` and `reasons()` explain the verdict; `to_dict()` is JSON-safe
(an infinite CV — non-zero spread around a zero mean — serializes as `null` plus a
`cv_is_infinite` flag).

## The stability criterion

The ensemble is `stable` iff **both** hold:

1. the metric's coefficient of variation is within `tolerance` (`cv <= tolerance`;
   an infinite CV is never within a finite tolerance), AND
2. the verdict is unanimous across seeds (a metric-only ensemble has no verdict to
   disagree on and is vacuously unanimous).

Verdict disagreement makes the ensemble unstable **even when the metric CV is
within tolerance**, because a flipped WIN/NULL is a qualitative instability the
scalar dispersion would otherwise hide.

`assert_stable(...)` runs the ensemble and raises `StabilityError` — carrying
`report.reasons()` — unless it is stable. Honest failure over a fake pass.

## Demonstration: the oscillatory-ablation runner across seeds

`kaine/evaluation/benchmarks/oscillatory_ablation/stability.py` runs the
controlled oscillatory-ablation runner across K seeds and reports stability of its
`selection_divergence_fraction` effect plus verdict unanimity:

```python
from kaine.evaluation.benchmarks.oscillatory_ablation.stability import (
    run_ablation_stability,
)

report = run_ablation_stability([1234, 2025, 7], ticks=16, tolerance=0.01)
assert report.stable
print(report.verdict_counts)  # {"WIN": 3}
print(report.cv)              # 0.0 — effect identical on every seed
```

The ablation runner is deterministic per seed and its scripted stimulus is
seed-independent, so the effect is in fact identical across seeds (CV = 0) and the
WIN verdict is unanimous — the strongest possible demonstration that the experiment
is seed-robust.

## Scope (honest)

This harness is the right instrument for genuinely nondeterministic **live**
longitudinal experiments: raise `tolerance` to whatever spread the live process
admits and run more seeds. As exercised in this codebase it runs **offline**
runners that are deterministic per seed, so it proves the stability *machinery* is
correct and demonstrates those offline experiments are seed-robust. It does **not**
itself collect weeks-long live longitudinal data — that is the operator's job once
an entity is running; this is the analysis instrument waiting for that data.
