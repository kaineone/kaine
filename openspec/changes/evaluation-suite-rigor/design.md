# Design — Evaluation suite rigor

> **Design-of-record only.** Plan, not implementation.

## 1. Reproducibility: what is and is not achievable (item 2, 3, 7)

Be precise, because the paper currently overclaims.

- **Offline experiment runners** (oscillatory ablation, A/B, memory, self-model,
  active-inference, stability): these can and should be **metric-reproducible** from
  a seed. Adding cuDNN/deterministic flags to `set_global_seed` closes the CUDA gap
  for any torch ops they touch.
- **Deterministic-mode cycle** (`deterministic=true`): reproducible by construction
  (scripted bus, no wall-clock projection). Keep and test as-is; but the current
  determinism test asserts seed-independence, which should be reframed as "trajectory
  is a pure function of scripted input" rather than "seeded."
- **Live cycle** (`deterministic=false`, real UTC, temperature-0.7 LLM): **cannot**
  be bit- or metric-reproduced from a seed — server-side LLM sampling is outside the
  seed's reach, and wall-clock enters timing. The paper must say so. Options: pin the
  organ to temperature 0 for reproducibility runs (changes behavior, arguably not the
  "real" entity), or state plainly that live runs are characterized by multi-seed
  stability distributions, not point reproduction. Recommend the latter wording + the
  multi-seed stability harness as the live-run reproducibility story.

Deliverable: a short "reproducibility tiers" note in the paper (offline: metric-
reproducible; deterministic cycle: exact; live cycle: distributional via multi-seed).

## 2. Shared-seed orchestrator (item 1)

One entry point takes a single `seed`, constructs a `RunContext`, and runs all seven
experiments, threading that seed into each — including replacing the active-inference
benchmark's local `default_rng(seed)` with the shared `set_global_seed` path (or
explicitly deriving its rng from the master seed via `SeedSequence.spawn`, which is
cleaner for independent-but-reproducible streams). Emits a combined report with per-
experiment verdicts + the corrected family-wise view (§3).

## 3. Multiple comparisons (item 4)

Across the p-value-producing experiments (active-inference Mann-Whitney,
individuation permutation, and any others), apply Holm-Bonferroni (control FWER) or
Benjamini-Hochberg (control FDR) at the suite level. Report raw p, corrected p, and
the decision under a stated alpha. Document the choice; Holm is the safer default for
a small family with a falsification posture.

## 4. Oscillatory ablation must be able to fail (item 5)

Today: WIN/NULL only, engineered stimulus, `min_effect=0.0`. Change to:
- add an adverse/insufficient-effect class so the runner can return NULL ("no
  meaningful effect") and, where applicable, a directionally-wrong result;
- add a non-engineered stimulus battery (not only phase-locked sources handed lower
  raw salience) so a real null is reachable;
- set a real `min_effect` so "layer does essentially nothing" resolves to NULL and
  justifies removing the layer, exactly as the paper's §6.4 and §9.3 promise.
Keep the existing bit-for-bit disabled-arm negative control (it is real and correct).

## 5. Individuation runner + fail-closed warm-up (item 6)

- Add a runner/CLI that constructs `IndividuationTest` with real `observations` and
  `lived_time_s` sourced from the run.
- Change the warm-up so **missing counters fail closed** (treated as not-warmed-up),
  never silently `warmed_up=True`. The paper's safeguard ("a just-booted or sensory-
  starved entity never trips a false individuation") must hold even when a caller
  forgets to pass counters.

## 6. Self-model scorer (item 7)

Either calibrate the thresholds against a small hand-labeled set and report the
calibration, or rename the claim to "fixed-threshold heuristic" in code and paper.
Stop scoring "no scorable claims" as 0.0 accuracy — distinguish "no evidence" from
"wrong."

## 7. Open questions for the operator
- Live-cycle reproducibility: temperature-0 reproducibility runs vs. distributional-
  only story (recommend distributional).
- FWER (Holm) vs. FDR (BH) for the suite (recommend Holm).
