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
- **WHEN** MSER-5 runs on a series with an exponential transient that has decayed below the noise by about the 90th value, searching 0 <= d <= b - 5
- **THEN** the truncation point lies in the first half and between the 30th and 120th value

#### Scenario: A degenerate end of the series no longer wins
- **WHEN** the last batch means of a series are equal
- **THEN** a search over 0 <= d <= b - 1 picks a final batch, and the paper's search over 0 <= d <= b - 5 does not

#### Scenario: The ladder does not reach the minimum effect
- **WHEN** the informative component's mean effect stays below theta_PC at SNR 256
- **THEN** the SNR rule raises `CalibrationError`, and the live test does not run

### Requirement: The calibration tool writes one versioned settings record
`python -m kaine.experiment.calibrate PLAN --out PATH` SHALL read the preliminary run and every attempted pilot run named in the plan, in attempt order, and write one JSON record with a schema name and version, the tool name and version, the git sha, the fixed constants, its inputs (each run's id, seed, manifest sha256 and records sha256) and every derived value. It SHALL check that each run's manifest names the expected study, that the three runs of a pilot share a seed, that no seed repeats and the preliminary seed is not a pilot seed, that every run used the same film program, and that every report carries `entity_time_s` and `awake`; a failed check SHALL write nothing and exit 2. It SHALL apply, in the paper's order: NOT EXERCISED classification and r_NE; T_learn by MSER-5 on cross-pilot averages of each arm's and processor's gains, searching 0 <= d <= b - 5, the largest median entity time of the truncated report, rounded up to a whole second, failing closed when any series has fewer than ten batch means or d* > b/2; s_cal and theta_eff = 0.5 s_cal per control over reports after T_learn; theta_PC as the smaller theta_eff and min_effect = theta_PC / 2; SNR_j by log-linear interpolation on the ladder; n_PC from the larger of the two components' run-level variances at the two rungs that bracket SNR_j (an approximation to the variance at SNR_j, which the ladder does not measure), the mean reports per run and Browne's factor; and the principal-component files' paths and hashes. It SHALL also record every counted pilot run's report rate per arm and processor, and for each processor and control arm the mean rates, the control arm's run-to-run standard deviation and whether the difference exceeds it, for inspection only; nothing SHALL be blocked on them, because the paper has no rule on report rates. A rule that cannot be applied SHALL leave its value null, name the reason under `blocked`, mark the record incomplete and make the tool exit 1.

#### Scenario: Synthetic pilots with known spreads
- **WHEN** the tool runs on synthetic pilots whose contrasts against the matched arm have standard deviation 0.0258 and one of five pilots never has more candidates than the coalition holds
- **THEN** r_NE is 0.2, the planned run count is 128, s_cal for the matched arm is within 0.003 of 0.0258, min_effect is theta_PC / 2 and each processor's SNR lies between the bracketing rungs

#### Scenario: Pilot runs too short for the learning period
- **WHEN** the pilot series have fewer than ten batch means, or a truncation point lies beyond half of its series
- **THEN** `t_learn_s` and every later value are null with reasons under `blocked`, and the record is incomplete

#### Scenario: The on arm reports at another rate
- **WHEN** the on arm's mean report rate differs from a control arm's by more than that arm's run-to-run standard deviation
- **THEN** the record carries every pilot run's report rate and the comparison, with `exceeds_control_sd` true, and nothing is blocked on it

#### Scenario: A ladder that did not finish
- **WHEN** a counted on-arm pilot's ladder has a failed result
- **THEN** the record is written with `snr` and `min_reports` blocked, and the tool exits 1

#### Scenario: Settings the environment cannot compute
- **WHEN** the tool runs
- **THEN** `theta_band`, `b_band`, `age_bins` and the threshold contrast's minimum effect are blocked as requiring rdrobust, and the tone bins and the tone analysis's minimum effect are blocked because the tone variant is not built

### Requirement: A live planned-test run needs a valid settings record
Each shipped study whose name starts with `workspace_mediation_` SHALL set the `[planned_test].role` that matches its name (`test` for the three live arms, `pilot` for the three pilot studies, `preliminary`, `positive_control`), and an unknown `workspace_mediation_*` study SHALL be refused. Whatever the study is called, including none, roles `test` and `positive_control` SHALL refuse to start, with exit code 12 and a message naming the reason, unless `[planned_test].settings_record` names a record whose schema, version and digest verify, that is complete with nothing blocked, whose constants equal the paper's (n_cal 30, c_eff 0.5, q_pow 0.65, power 0.9, alpha 0.05, the MSER batch, search end and minimum batches, five bins, the SNR ladder), with thirty counted pilots and n_exact 102, whose values are in range, and whose principal-component files match their recorded sha256; and unless the run's seed was not used by the preliminary or any pilot run. Role `test` SHALL refuse an enabled `[positive_control]` in any mode but `control`; role `positive_control` SHALL require `[positive_control]` enabled in mode `control` with the same record. The loader SHALL also require exactly thirty pilot entries with `counted` true, distinct seeds across the preliminary and pilot runs, a reason on every NOT EXERCISED entry, and attempted and NOT EXERCISED counts that agree with the entries. Whenever `[positive_control]` is enabled under a role, its `settings_record` SHALL equal `[planned_test].settings_record`. At boot the gate SHALL recompute the sha256 of each preliminary and pilot run's manifest and research-log records when they are present and refuse a mismatch. A gated run SHALL record the record's digest in its run manifest as `settings_record_sha256`, and the run-data status (`verified`, `absent` or `partial`) as `settings_record_run_data`. Configurations without a role SHALL be unaffected.

#### Scenario: No record
- **WHEN** a run starts with `KAINE_STUDY=workspace_mediation_competitive` and the record file does not exist
- **THEN** the boot stops with exit code 12 and a message about the settings record

#### Scenario: A reused seed
- **WHEN** a live arm starts with a valid record and the seed of one of the pilot runs
- **THEN** the boot stops and names the seed

#### Scenario: An edited record
- **WHEN** a value in the record was changed after the tool wrote it
- **THEN** the loader reports that the record was edited after it was written

#### Scenario: A renamed study cannot skip the record
- **WHEN** a configuration sets `[planned_test].role = "test"` under a study that is not one of the shipped names, or with no study
- **THEN** the boot stops unless a valid record is named

#### Scenario: A study with the wrong role
- **WHEN** `workspace_mediation_competitive` sets role `pilot`
- **THEN** the boot stops and names the expected role

#### Scenario: Pilot data that changed after calibration
- **WHEN** a pilot run's research log on the host no longer matches the hash in the record
- **THEN** the boot stops and names the run

#### Scenario: A record with a duplicate seed
- **WHEN** two pilot entries of a record share a seed
- **THEN** the loader refuses the record

#### Scenario: The manifest names the record
- **WHEN** a live arm boots with a valid record
- **THEN** its run manifest carries the record's digest in `settings_record_sha256`

#### Scenario: Pilots need no record
- **WHEN** a run starts with `KAINE_STUDY=workspace_mediation_pilot_matched`
- **THEN** the boot check passes without a record
