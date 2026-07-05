# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## 1. Boundary-neutral harness

- [x] 1.1 `kaine/experiment/stability.py`: pure summary stats (`_mean`/`_std`
      mirroring individuation) + coefficient of variation (`std/|mean|`, with the
      zero-mean edge documented).
- [x] 1.2 `StabilityReport` dataclass: `seeds`, `values`, `mean`, `std`, `cv`,
      `verdict_counts`, `tolerance`, `stable`; `verdict_unanimous` property;
      `reasons()`; JSON-safe `to_dict()`.
- [x] 1.3 `run_multi_seed(run_fn, seeds, *, metric_fn, tolerance=0.0,
      pin_global_seed=True)`: per-seed `set_global_seed`, metric collection,
      verdict extraction (Verdict / Outcome / dict / `.verdict` attr), stability
      criterion (CV within tolerance AND verdicts unanimous).
- [x] 1.4 `assert_stable(...)` + `StabilityError` carrying `report.reasons()`
      (honest failure over a fake pass).
- [x] 1.5 Re-export the harness symbols from `kaine/experiment/__init__.py`.

## 2. Demonstration adapter

- [x] 2.1 `kaine/evaluation/benchmarks/oscillatory_ablation/stability.py`:
      `run_ablation_stability(seeds, *, ticks, tolerance, base_config)` runs the
      ablation runner per seed via `run_multi_seed`, headline metric =
      `selection_divergence_fraction`, verdict from the runner's `Verdict`.

## 3. Docs

- [x] 3.1 `docs/processes/longitudinal-stability.md`: what the harness is, the
      stability criterion, how to run the ablation demonstration, and the honest
      scope limitation (offline / per-seed deterministic; not live data).

## 4. Tests

- [x] 4.1 Harness units: low-variance → stable + exact mean/std/cv/verdict_counts;
      small-within-tolerance → stable; high-variance → unstable with reasons;
      infinite-CV (zero mean, non-zero spread) → unstable + JSON-safe serialization;
      all-zero ensemble → stable.
- [x] 4.2 Verdict unanimity: unanimous → counted + stable; disagreement → not
      unanimous → unstable even with CV 0; verdict pulled from an object result.
- [x] 4.3 `assert_stable` returns report when stable / raises with reasons when
      not; empty-seeds + negative-tolerance rejected; global-seed pinning.
- [x] 4.4 Boundary: `kaine/experiment/stability.py` does not import
      `kaine.evaluation` (AST + git-grep guards).
- [x] 4.5 Integration: ablation adapter across K seeds → stable report (unanimous
      WIN, effect CV within tolerance); report serializes.

## 5. Verify

- [x] 5.1 `pytest -k "stability or multi_seed or longitudinal"` green.
- [x] 5.2 Sidecar-boundary tests green (harness in kaine/experiment must not import
      kaine.evaluation).
- [x] 5.3 `openspec validate longitudinal-stability --strict`.
