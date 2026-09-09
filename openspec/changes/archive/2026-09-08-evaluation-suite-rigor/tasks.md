# Tasks — Evaluation suite rigor

> **Reconciliation note.** This change was authored as design-of-record, but the
> work it plans shipped in the initial evaluation-suite release and these boxes
> were simply never ticked. Each item below is checked with a `file:symbol`
> evidence pointer to the already-shipped code/docs/tests that satisfy it. No item
> was operator-supervised or live; nothing remains to implement in this repo. The
> only out-of-repo residue is the arXiv manuscript §6 wording (7.1) — the public
> docs mirror carries the identical tiers note; see that item.

## 1 — Shared-seed suite orchestrator
- [x] 1.1 One entry point runs all seven experiments from a single `RunContext.seed`.
      → `kaine/evaluation/benchmarks/suite.py:run_suite` (drives all seven in
      `EXPERIMENT_NAMES` from one `SuiteConfig.seed`).
- [x] 1.2 Thread the seed uniformly; derive the active-inference rng from the master
      seed (SeedSequence.spawn) instead of an independent default_rng.
      → `suite.py:run_suite` spawns one child seed per experiment via
      `np.random.SeedSequence(config.seed).spawn`; the active-inference stream is
      derived from the master through `BenchmarkConfig.master_seed` +
      `kaine/evaluation/benchmarks/active_inference/runner.py:derive_seed`
      (`SeedSequence([master_seed, seed])`).
- [x] 1.3 Emit a combined verdict report.
      → `suite.py:run_suite` returns the combined report (per-experiment verdicts +
      `family_wise`); `suite.py:format_suite_report` renders it. Covered by
      `tests/test_evaluation_suite.py:test_suite_runs_all_seven_and_reports_verdicts_and_holm`.

## 2 — GPU/cuDNN determinism
- [x] 2.1 Extend `set_global_seed` with `use_deterministic_algorithms(True)`,
      `cudnn.deterministic=True`, `cudnn.benchmark=False` for the deterministic path.
      → `kaine/experiment/seeding.py:set_global_seed` (the `deterministic=True`
      branch sets all three plus `CUBLAS_WORKSPACE_CONFIG`). Test:
      `tests/test_experiment_foundation.py:test_seeding_deterministic_flag_sets_cudnn_state`.
- [x] 2.2 Document the perf cost; keep it opt-in for offline runs.
      → `seeding.py` module docstring ("GPU / cuDNN determinism (opt-in)") documents
      the autotuning/kernel cost; `deterministic` defaults to `False` and only the
      offline `SuiteConfig.deterministic=True` path requests it. Torch-absent safety:
      `tests/test_experiment_foundation.py:test_seeding_deterministic_flag_default_off_never_raises`.

## 3 — Multiple-comparisons correction
- [x] 3.1 Apply Holm-Bonferroni (recommended) across p-value experiments.
      → `kaine/experiment/multiple_comparisons.py:holm_bonferroni` (step-down FWER),
      wired at suite level in `suite.py:run_suite` via `holm_report`. Tests:
      `tests/test_multiple_comparisons.py` (12 cases).
- [x] 3.2 Report raw p, corrected p, and the decision under a stated alpha.
      → `multiple_comparisons.py:Comparison` / `holm_report` carry `raw_p`, `holm_p`,
      `reject` under `alpha`; surfaced in the suite report's `family_wise` and
      `format_suite_report`.

## 4 — Oscillatory ablation can fail
- [x] 4.1 Add an adverse/insufficient-effect outcome class (real NULL reachable).
      → `kaine/evaluation/benchmarks/oscillatory_ablation/runner.py:_classify`
      returns WIN / NULL / NEGATIVE (`Outcome`). Tests:
      `tests/test_oscillatory_ablation_runner.py:test_neutral_battery_yields_null_not_win`,
      `:test_classifier_below_min_effect_is_null`,
      `:test_mislabeled_battery_yields_real_negative_via_pipeline`.
- [x] 4.2 Add a non-engineered stimulus battery.
      → `oscillatory_ablation/stimulus.py:NEUTRAL_STIMULUS` (no coherence contrast;
      real NULL reachable) plus `MISLABELED_STIMULUS` (adverse via the real
      pipeline). Selectable through `STIMULUS_BY_NAME`.
- [x] 4.3 Set a real `min_effect`; keep the bit-for-bit disabled-arm control.
      → `runner.py:AblationConfig.min_effect = 0.10` (non-zero); disabled arm is the
      layer-absent baseline (`_run_arm(enabled=False)` passes `coherence=None`),
      proven bit-for-bit by
      `tests/test_oscillatory_ablation_runner.py:test_disabled_arm_is_bit_for_bit_layer_absent_baseline`.

## 5 — Individuation runner + fail-closed warm-up
- [x] 5.1 Add a runner/CLI supplying real `observations` + `lived_time_s`.
      → `kaine/evaluation/benchmarks/individuation_runner.py:run_individuation`
      REQUIRES both counters (raises `ValueError` if absent) and emits a shared
      `Verdict`; `main()` is its CLI over an operator transcript bundle. Test:
      `tests/test_individuation.py:test_runner_requires_real_counters`.
- [x] 5.2 Missing counters ⇒ NOT warmed up (fail closed); never silent `warmed_up=True`.
      → `kaine/evaluation/individuation.py:IndividuationTest.run` treats a missing
      counter as ZERO (`obs_val = int(observations) if observations is not None else 0`,
      likewise `lived_val`); `warmed_up` is true only when both meet their floors, and
      `significant` is `exceeds_null and warmed_up`. (The old force-`warmed_up=True`
      shortcut is gone.)
- [x] 5.3 Test: a fresh/sensory-starved entity cannot trip individuation.
      → `tests/test_individuation.py:test_missing_counters_fail_closed_cannot_trip_individuation`
      (also `:test_warmup_below_floor_is_never_significant`,
      `:test_runner_null_when_not_warmed_up`).

## 6 — Self-model scorer honesty
- [x] 6.1 Calibrate thresholds against a small labeled set, OR rename to
      "fixed-threshold heuristic" in code + paper.
      → RENAMED. `kaine/evaluation/eidolon_accuracy.py` module docstring + the
      `_signals_snapshot` "FIXED (heuristic) thresholds — hand-chosen … NOT fitted"
      comment state it is a fixed-threshold heuristic, not a calibrated instrument.
      Spec renamed in `specs/evaluation-observers/spec.md` (RENAMED Requirements).
- [x] 6.2 Distinguish "no scorable claims" from 0.0 accuracy.
      → `eidolon_accuracy.py:EidolonAccuracyRunner.run_once`: `aggregate` is `None`
      when no claim is scorable (never averaged to 0.0); `_score_claim` returns
      `None` for an unavailable signal. Tests:
      `tests/test_eidolon_scorer_calibration.py:test_run_once_aggregate_none_when_no_scoreable_signal`,
      `:test_score_claim_high_when_signal_supports` (1.0),
      `:test_score_claim_low_when_signal_contradicts` (0.0),
      `:test_run_once_aggregate_is_mean_of_scored_claims`.

## 7 — Paper reproducibility wording
- [x] 7.1 Add the reproducibility-tiers note (offline metric / deterministic exact /
      live distributional) to `paper/paper.md` + the arXiv manuscript §6.
      → The public-repo paper mirror `docs/reproducing-results.md` carries the
      "Reproducibility tiers (what 'reproducible' means here)" section with all three
      tiers (offline metric-reproducible / deterministic exact / live distributional).
      NB: this public repo has no `paper/paper.md` or arXiv `.tex` source (the
      manuscript is maintained as a separate, vendor-neutral artifact per the paper
      conventions); the identical tiers wording lives in the docs mirror above.
- [x] 7.2 Reframe the determinism test's claim (pure function of scripted input, not
      seeded).
      → `tests/test_deterministic_cycle.py` module docstring reframes the guarantee
      as "the cognitive trajectory is a PURE FUNCTION of the scripted input" (seed
      pinned for hygiene only); `:test_different_seeds_same_scripted_stimulus_documents_seed_independence`
      documents seed-independence explicitly.
