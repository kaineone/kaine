## 1. Rules and records

- [x] 1.1 `kaine/experiment/calibration_rules.py`: constants with sources; exact sign-test power and stable run count; planned run count and attrition rule; sample SD and minimum effect; ensemble average and MSER-5; Browne factor and the n_PC term; SNR interpolation; quintile edges
- [x] 1.2 `kaine/experiment/principal_component.py`: streaming estimator, versioned file with sha256
- [x] 1.3 `kaine/experiment/planned_test_settings.py`: schema, digest, loader, boot check
- [x] 1.4 `kaine/experiment/calibrate.py` and `run_records.load_records_for_runs`
- [x] 1.5 Tests with known answers for every rule, the fail-closed paths and the synthetic pilot tree

## 2. Positive control

- [x] 2.1 Modes `estimate_pc`, `ladder` and `control`; principal-component direction; per-processor SNR; T_learn; settings from the record; typed-in keys refused
- [x] 2.2 Offline check pools consecutive complete runs
- [x] 2.3 Tests

## 3. Logs, boot and studies

- [x] 3.1 Reports carry `entity_time_s` and `awake`; broadcasts carry `coalition_capacity`; research log taxonomy and range sweep
- [x] 3.2 Studies may set `[planned_test]` and `[positive_control]`; boot check in the run-identity phase (exit 12)
- [x] 3.3 Preliminary, pilot and positive-control studies; live arms declare role `test`
- [x] 3.4 Docs: researchers, experiments, configuration reference, research event streams, verification

## 4. Open (operator)

- [ ] 4.1 Fix the MSER-5 search range in the paper and set `MSER_IGNORE_END`
- [ ] 4.2 Add rdrobust and record which broadcast preceded each prediction, for theta_band, b_band and the age bins
- [ ] 4.3 Build the tone variant and log the tone model's error ratio, for the tone bins
