# Tasks

## 1. Design (this change)

- [x] 1.1 Record the estimator, records, trigger, feedback arm and persistence (proposal, design, specs).
- [x] 1.2 Cite prior work: the processors' error ratios, the planning module's certainty words, `workspace-feedback`, `interest-goal-factor` (per-source learning progress).

## 2. Before any code (gate)

- [ ] 2.1 The workspace-mediation ablation has run.
- [ ] 2.2 Paper change settled: §4 row, §9 line, §6.4 sixth feedback arm, Table A1 (`k`, `eta_c`, `W_c`, `c_low`, `Delta_c`, calibration floor, hourly cap).

## 3. Stage A (records)

- [ ] 3.1 Estimator and feature assembly from bus events. Tests: `tests/test_metacognition_estimator.py` (zero start, learning from outcomes, no learning in sleep), with a mutation check on the target.
- [ ] 3.2 Module, factory, config, diagnostics stream, persistence and fork copy. Tests: `tests/test_metacognition_module.py`, `tests/test_metacognition_persistence.py`.
- [ ] 3.3 Offline calibration check on recorded test-boot streams: Brier score and type-2 AUROC per processor recorded under `docs/records/`; the estimator is compared with a first-order baseline (confidence from the last error ratio alone). Test: `tests/test_metacognition_calibration_metrics.py` on synthetic data with known calibration.

## 4. Stage B (monitor)

- [ ] 4.1 `metacognition.uncertain` with hysteresis, calibration floor and cap; felt phrases. Tests: `tests/test_metacognition_uncertain_event.py`, `tests/test_felt_metacognition_phrases.py`. Opus second review.
- [ ] 4.2 Welfare isolation. Test: `tests/test_metacognition_welfare_isolation.py`.
- [ ] 4.3 One supervised validation boot on a branch before study use.

## 5. Stage C (feedback arm)

- [ ] 5.1 After `workspace-feedback` tasks 3.2 and 3.3: the `confidence` arm in `kaine/workspace/feedback.py`, `config/studies/workspace_feedback_confidence.toml`, and the spec delta on the archived `workspace-feedback` capability. Tests: `tests/test_workspace_feedback_confidence_arm.py`.

## 6. Docs and checks

- [ ] 6.1 `docs/09-modules/metacognition.md`, Appendix A rows.
- [ ] 6.2 `openspec validate metacognitive-confidence --strict` passes.
