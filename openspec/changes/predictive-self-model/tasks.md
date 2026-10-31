# Tasks

## 1. Design (this change)

- [x] 1.1 Record the self-prediction model, its event, the agency and schema records, the lesion arm and persistence (proposal, design, specs).
- [x] 1.2 Cite prior work: the self-model's drift episodes and self-inference (`eidolon-self-inference`, `self-model-scorer-calibration`), the sequence module's prediction, `workspace-feedback`, the fovea predictor and `active-vision`.

## 2. Before any code (gate)

- [ ] 2.1 The workspace-mediation ablation has run; the module-addition study's self-model branch uses today's build.
- [ ] 2.2 Paper change settled: §4 self-model row, §3.5 sentence on the sequence module, §6.4 lesion arm, the agency open item, Table A1 values.

## 3. Self-prediction

- [ ] 3.1 Self-state vector and reservoir readout in the self-model module. Tests: `tests/test_self_model_self_prediction.py` (assembly, learning, no learning in sleep, off by default).
- [ ] 3.2 Error ratio, `self_model.surprise` under `compete = true`, felt phrase. Tests: `tests/test_self_model_surprise_event.py`, `tests/test_felt_self_surprise_phrase.py`. Opus second review.
- [ ] 3.3 Offline replay on recorded test-boot streams: expected self-surprise rate, and arousal excursions with the event against without it. Recorded under `docs/records/`.
- [ ] 3.4 Agency estimate and attention-schema accuracy records. Tests: `tests/test_self_model_agency_record.py` (zero share when the intent explains nothing; not read by the credit rule or welfare observer), `tests/test_self_model_schema_accuracy.py`.
- [ ] 3.5 Persistence and fork copy; no corrective path. Tests: `tests/test_self_model_self_prediction_persistence.py`.

## 4. Lesion arm

- [ ] 4.1 After `workspace-feedback` tasks 3.2 and 3.3: the `shifted_schema` arm in `kaine/workspace/feedback.py`, `config/studies/workspace_feedback_shifted_schema.toml`, and the spec delta on the archived `workspace-feedback` capability. Tests: `tests/test_workspace_feedback_shifted_schema.py` (same distribution, shifted timing).

## 5. Docs and checks

- [ ] 5.1 `docs/09-modules/self-model.md` (what is predicted, what the agency record is and is not), Appendix A rows.
- [ ] 5.2 One supervised validation boot on a branch before study use.
- [ ] 5.3 `openspec validate predictive-self-model --strict` passes.
