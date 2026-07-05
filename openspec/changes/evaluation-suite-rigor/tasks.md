# Tasks — Evaluation suite rigor

> **Design-of-record only.** Plan, not implement. Resolve `design.md` §7 open
> questions first.

## 1 — Shared-seed suite orchestrator
- [ ] 1.1 One entry point runs all seven experiments from a single `RunContext.seed`.
- [ ] 1.2 Thread the seed uniformly; derive the active-inference rng from the master
      seed (SeedSequence.spawn) instead of an independent default_rng.
- [ ] 1.3 Emit a combined verdict report.

## 2 — GPU/cuDNN determinism
- [ ] 2.1 Extend `set_global_seed` with `use_deterministic_algorithms(True)`,
      `cudnn.deterministic=True`, `cudnn.benchmark=False` for the deterministic path.
- [ ] 2.2 Document the perf cost; keep it opt-in for offline runs.

## 3 — Multiple-comparisons correction
- [ ] 3.1 Apply Holm-Bonferroni (recommended) across p-value experiments.
- [ ] 3.2 Report raw p, corrected p, and the decision under a stated alpha.

## 4 — Oscillatory ablation can fail
- [ ] 4.1 Add an adverse/insufficient-effect outcome class (real NULL reachable).
- [ ] 4.2 Add a non-engineered stimulus battery.
- [ ] 4.3 Set a real `min_effect`; keep the bit-for-bit disabled-arm control.

## 5 — Individuation runner + fail-closed warm-up
- [ ] 5.1 Add a runner/CLI supplying real `observations` + `lived_time_s`.
- [ ] 5.2 Missing counters ⇒ NOT warmed up (fail closed); never silent `warmed_up=True`.
- [ ] 5.3 Test: a fresh/sensory-starved entity cannot trip individuation.

## 6 — Self-model scorer honesty
- [ ] 6.1 Calibrate thresholds against a small labeled set, OR rename to
      "fixed-threshold heuristic" in code + paper.
- [ ] 6.2 Distinguish "no scorable claims" from 0.0 accuracy.

## 7 — Paper reproducibility wording
- [ ] 7.1 Add the reproducibility-tiers note (offline metric / deterministic exact /
      live distributional) to `paper/paper.md` + the arXiv manuscript §6.
- [ ] 7.2 Reframe the determinism test's claim (pure function of scripted input, not
      seeded).
