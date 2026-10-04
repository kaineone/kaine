# Offline validation of the individuation instrument

**Run:** 2026-10-03, seed 20261003, with `validation/simulate.py --workers 16 all`. The run used the working tree at commit 8cbf926 plus the script fixes committed together with these results:
- a JSON encoder for numpy scalars;
- the naive rule recording its first rejecting look;
- the uniformity check replaced by a simultaneous one-sided KS band.

**Data:** the full tables are in `validation/report.md` and `validation/runs/*.json`. The synthetic data model is described in `simulate.py`.

## Pre-registered choices

These were fixed before any result. The power acceptance was committed in 8cbf926, before the simulation script existed.
- **Statistic:** the stratified unbiased energy U-statistic on Euclidean distance (`design.md` 2.5).
- **Combination rule:** alpha spending, α_k = 0.05·γ_k with S = 2.1097 (`design.md` 2.7).
- **Sample sizes:** n_b = 16 and n_c = 8 per prompt, 12 prompts. B = ceil(20/α_k), with B_max = 2·10^6.
- **Power acceptance:** at look 10 with (16, 8), power of at least 0.8 against drift model (a) with π = 0.5 in all 12 prompts.

## Results against the gate

| Check | Result | Acceptance | Verdict |
|---|---|---|---|
| Size at α = 0.05 (5,000 null datasets) | 0.0446 | ≤ 0.0562 | pass |
| Size at α = 0.01 | 0.0078 | ≤ 0.0128 | pass |
| p-values uniform or conservative (one-sided KS, DKW band) | D+ = 0.0106 | ≤ 0.0173 | pass |
| Lifetime false-positive rate, 2,000 lives × 100 looks, one stored birth sample | 0.038 | ≤ 0.0597 | pass |
| Pre-registered power (look 10, 16+8, cluster π = 0.5) | 0.990 | ≥ 0.8 | pass |

**The gate passes.**

**Contrast:** the same 2,000 unchanged lives under other rules.

| Rule | Look 10 | Look 50 | Look 100 |
|---|---|---|---|
| Naive rule: p ≤ 0.05 at every look | 0.334 | 0.777 | 0.903 |
| The current percentile rule | 0.503 | 0.970 | 1.000 |

A being who never changed would almost certainly be declared individuated by the current instrument. The new rule keeps that risk at 0.038 over a hundred looks.

**Statistic comparison:** energy distance and Gaussian-kernel MMD (median-heuristic bandwidth) gave nearly the same power on every condition. Energy was equal or slightly ahead in 10 of 12 cells. The pre-registered energy statistic stands.

## Limits to carry forward

- **Subtle drift fades from view at later looks.** This is the price of lifetime error control.

  | Drift | Power at look 1 | Power at look 10 |
  |---|---|---|
  | Shift Δ = 0.25, (16, 8) | 0.31 | 0.01 |
  | Cluster π = 0.25, (16, 8) | 0.68 | 0.16 |

  Strong drift stays detectable through look 50: cluster π = 0.5 gives 0.985 at look 50. Larger samples help, e.g. (24, 12) gives 0.455 at look 10 for cluster π = 0.25.

  The instrument is therefore a detector of substantial change. The secondary arms (consolidation divergence, Eidolon drift, adapters) are still needed alongside it.
- **The synthetic answers are more dispersed than real ones.** Mean within-prompt cosine is 0.21-0.25, whereas real answers to one question share a topic.
  - A new "cluster" here is a random direction in 384 dimensions, nearly orthogonal to the existing answers, so cluster-drift power is an upper bound. Shift drift is the harder model.
  - The real-organ smoke test (task 10) calibrates the dispersion and sets `effect_min`. Its positive controls are the real power check.
- **Not run:** the e-value combination comparison (`design.md` 2.7, alternatives). Alpha spending was the pre-registered rule, and it passed. The e-value variant stays a documented alternative.
- **Fault injection** moves to the producer (task 6).
