## MODIFIED Requirements

### Requirement: Positive control of the information-gain measure
When `[positive_control].enabled` is true in mode `ladder` or `control`, Topos, Audition and Soma SHALL each run informative and non-informative shadows of their forward model: copies of the live model whose context is one component wider, with zero weights on that component at creation, trained on the same inputs. At each report a shadow SHALL form, from the state the previous report left, the prediction of the current input with the live model's previous context plus the component, and its null prediction with the live model's previous null context plus the component's running mean. The informative component SHALL be v_j^T (x - mu_j) plus seeded Gaussian noise whose variance is that of the earlier projections divided by the SNR, where v_j and mu_j are the first principal component and the mean of the processor's inputs recorded by the preliminary run (paper Appendix A.8; Jolliffe 2002); the non-informative component SHALL be a seeded series with the running mean and variance of the informative one, computed without the current input, so it is independent of it. The live model, its reports, its intensities and the competition SHALL be unchanged by the control.

#### Scenario: The component follows the principal direction
- **WHEN** an informative component at a very high SNR is fed inputs
- **THEN** its values correlate above 0.999 with v_j^T (x - mu_j), and the non-informative component's values do not

#### Scenario: Hindsight equals the live prediction
- **WHEN** a shadow is fed the same inputs and contexts as the live model with the extra component held at 0
- **THEN** its hindsight errors and null errors equal the live model's errors and null errors at every report

#### Scenario: Live weights and random states are untouched
- **WHEN** a full Topos, Audition or Soma run with the control enabled is compared with the same run without it, from the same seeds
- **THEN** the live model's weights and the Python, numpy and torch random states are identical

### Requirement: Within-run verdict per processor
In mode `control` the control SHALL count an awake report whose entity time is after T_learn from the settings record when the live gain, the live model's running mean error and both shadow error differences are defined and finite and the mean error is above 0; the shadows SHALL be stepped on every report, counted or not. All gains SHALL be divided by that same live mean error. It SHALL report the cumulative means `ig_with`, `ig_without` and `ig_noise`, `effect = ig_with - ig_without`, `noise_effect = ig_noise - ig_without`, and the record's `min_effect`, `min_reports`, `snr`, `t_learn_s` and `settings_sha256`. The processor SHALL pass when at least `min_reports` reports were counted, `effect` reaches `min_effect` and `noise_effect` does not.

#### Scenario: Reports before the learning period
- **WHEN** a control with T_learn 50 s sees reports at entity times 1 to 100 s
- **THEN** it counts the 50 reports after 50 s, and both shadows were stepped on all 100

### Requirement: Off by default, set only from the study configuration
The shipped configuration SHALL leave `[positive_control]` disabled. Its keys SHALL be `enabled`, `mode`, `seed`, `principal_components_run` and `settings_record`; `snr`, `min_effect` and `min_reports` SHALL be refused as keys, because they come from the settings record. Mode `estimate_pc` SHALL accumulate the processor's awake, finite inputs and, at shutdown, write the first principal component and mean to `data/evaluation/positive_control/<run_id>/principal_component_<processor>.json` with its sha256 in the terminal record; no input SHALL be stored. Mode `ladder` SHALL load the principal components of the run named by `principal_components_run`, run one informative and one non-informative shadow at each SNR of the ladder 4^-2 to 4^4, and publish one `positive_control.ladder` record per counted report with the entity time, the live gain and each shadow's gain. Mode `control` SHALL load SNR_j, min_effect, min_reports, T_learn and the principal components from the settings record named by `settings_record`, verifying the files' sha256. The control SHALL never delay a report: the processor SHALL publish its report first and then queue the control's step for that report, one worker per processor SHALL run the steps in submission order off the report path with the live model's sleep flag and wakefulness as they were at the report, more than 256 waiting steps SHALL fail the control, and at shutdown the processor SHALL wait for the queued steps before it publishes the terminal record. A control that raises SHALL publish a last result marked failed, final and not passed, and SHALL be switched off for the run without interrupting perception.

#### Scenario: The report does not wait for the control
- **WHEN** a control step is blocked
- **THEN** the processor's report is already on its stream, and the control's record follows once the step runs

#### Scenario: Typed-in settings are refused
- **WHEN** `[positive_control]` sets `snr`
- **THEN** construction fails with a message that the value comes from the settings record

#### Scenario: The preliminary run records the direction
- **WHEN** a preliminary run in mode `estimate_pc` sees inputs with a planted leading direction and shuts down
- **THEN** the written file's direction has an absolute dot product above 0.99 with the planted one, and its sha256 is in the terminal record

### Requirement: Results are recorded and checked for every processor
Each counted report in mode `control` SHALL publish the cumulative result as `positive_control.result` on `positive_control.out`, and the cycle's shutdown SHALL have each processor publish a terminal record marked `final` before the research log stops. `python -m kaine.experiment.positive_control RUN_ID [RUN_ID ...]` SHALL consider only results in mode `control`, SHALL require each run's terminal record to be complete (no failed record, exactly one terminal record and nothing after it, finite numbers, effects equal to the differences of the IG means), and SHALL pool consecutive complete runs in the given order, weighting each run's means by its report count, until a processor reaches `min_reports`; later runs SHALL not be used for that processor, an incomplete run inside the pool SHALL fail the processor, and runs with different settings SHALL fail. The verdict SHALL be re-derived from the numbers, never from a record's `passed`, and the check SHALL exit 0 only when Topos, Audition and Soma all pass and no record line failed to parse.

#### Scenario: Two short runs
- **WHEN** two complete runs each count 60 reports and `min_reports` is 100
- **THEN** each alone fails with fewer than min_reports reports, and together they pass when the pooled effect reaches `min_effect`

#### Scenario: Pooling stops at min_reports
- **WHEN** three runs of 60 reports are given and `min_reports` is 100
- **THEN** only the first two are used, and a failure in the third does not change the verdict
