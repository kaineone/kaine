## ADDED Requirements

### Requirement: The planned test's rules are fixed in code with their sources
`kaine/experiment/calibration_rules.py` SHALL hold the paper's fixed constants (c_eff 0.5, n_cal 30, q_pow 0.65, power 0.9 per control, alpha 0.05, alpha and beta of the positive control 0.05, Browne's 80 percent upper confidence limit, batch size 5, five bins, the SNR ladder 4^-2 to 4^4) and implement each rule of paper Appendix A.8 as a pure function that cites its source and raises `CalibrationError` when it cannot be applied. The exact sign-test power SHALL be computed with integer arithmetic, and the run count SHALL be the smallest n whose power reaches the target at n and at every larger n up to a horizon of 1000.

#### Scenario: The run count of the paper
- **WHEN** the stable run count is computed at q = 0.65, power 0.9 and alpha 0.05
- **THEN** it is 102, with critical count 60 and power 0.920, and it is 76 at power 0.8 and 35 at q = 0.75

#### Scenario: Attrition
- **WHEN** 3 of 33 attempted pilot runs were NOT EXERCISED
- **THEN** the planned run count is ceil(102 / (1 - 3/33)) = 113, and runs are added until at least 102 enter each control's test

#### Scenario: MSER-5 on a known transient
- **WHEN** MSER-5 runs on a series with an exponential transient that has decayed below the noise by about the 90th value, with the final batches left out of the search
- **THEN** the truncation point lies in the first half and between the 30th and 120th value

#### Scenario: The literal MSER range is degenerate
- **WHEN** MSER-5 searches every d with 0 <= d < b
- **THEN** it returns d = b - 1, in the second half, for any series

#### Scenario: The ladder does not reach the minimum effect
- **WHEN** the informative component's mean effect stays below theta_PC at SNR 256
- **THEN** the SNR rule raises `CalibrationError`, and the live test does not run

### Requirement: The calibration tool writes one versioned settings record
`python -m kaine.experiment.calibrate PLAN --out PATH` SHALL read the preliminary run and every attempted pilot run named in the plan, in attempt order, and write one JSON record with a schema name and version, the tool name and version, the git sha, the fixed constants, its inputs (each run's id, seed, manifest sha256 and records sha256) and every derived value. It SHALL check that each run's manifest names the expected study, that the three runs of a pilot share a seed, that no seed repeats and the preliminary seed is not a pilot seed, that every run used the same film program, and that every report carries `entity_time_s` and `awake`; a failed check SHALL write nothing and exit 2. It SHALL apply, in the paper's order: NOT EXERCISED classification and r_NE; T_learn by MSER-5 on cross-pilot averages of each arm's and processor's gains, the largest median entity time of the truncated report, rounded up to a whole second, failing closed when any truncation point lies in the second half; s_cal and theta_eff = 0.5 s_cal per control over reports after T_learn; theta_PC as the smaller theta_eff and min_effect = theta_PC / 2; SNR_j by log-linear interpolation on the ladder; n_PC from the larger of the two components' run-level variances at the bracketing rungs, the mean reports per run and Browne's factor; and the principal-component files' paths and hashes. A rule that cannot be applied SHALL leave its value null, name the reason under `blocked`, mark the record incomplete and make the tool exit 1.

#### Scenario: Synthetic pilots with known spreads
- **WHEN** the tool runs on synthetic pilots whose contrasts against the matched arm have standard deviation 0.0258 and one of five pilots never has more candidates than the coalition holds
- **THEN** r_NE is 0.2, the planned run count is 128, s_cal for the matched arm is within 0.003 of 0.0258, min_effect is theta_PC / 2 and each processor's SNR lies between the bracketing rungs

#### Scenario: The MSER search range is not fixed
- **WHEN** the tool runs with `MSER_IGNORE_END` unset
- **THEN** `t_learn_s`, `s_cal`, `snr` and `min_reports` are null with reasons under `blocked`, and the record is incomplete

#### Scenario: Settings the environment cannot compute
- **WHEN** the tool runs
- **THEN** `theta_band`, `b_band`, `age_bins` and the threshold contrast's minimum effect are blocked as requiring rdrobust, and the tone bins and the tone analysis's minimum effect are blocked because the tone variant is not built

### Requirement: A live planned-test run needs a valid settings record
A study whose name starts with `workspace_mediation_` SHALL set `[planned_test].role` to `preliminary`, `pilot`, `test` or `positive_control`. For roles `test` and `positive_control` the boot SHALL refuse to start, with exit code 12 and a message naming the reason, unless `[planned_test].settings_record` names a record whose schema, version and digest verify, that is complete with nothing blocked, whose values are in range, and whose principal-component files match their recorded sha256; and unless the run's seed was not used by the preliminary or any pilot run. Role `positive_control` SHALL also require `[positive_control]` enabled in mode `control` with the same record. Boots without a study, and other studies, SHALL be unaffected.

#### Scenario: No record
- **WHEN** a run starts with `KAINE_STUDY=workspace_mediation_competitive` and the record file does not exist
- **THEN** the boot stops with exit code 12 and a message about the settings record

#### Scenario: A reused seed
- **WHEN** a live arm starts with a valid record and the seed of one of the pilot runs
- **THEN** the boot stops and names the seed

#### Scenario: An edited record
- **WHEN** a value in the record was changed after the tool wrote it
- **THEN** the loader reports that the record was edited after it was written

#### Scenario: Pilots need no record
- **WHEN** a run starts with `KAINE_STUDY=workspace_mediation_pilot_matched`
- **THEN** the boot check passes without a record
