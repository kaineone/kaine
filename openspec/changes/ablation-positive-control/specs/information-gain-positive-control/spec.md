## ADDED Requirements

### Requirement: Positive control of the information-gain measure
When `[positive_control].enabled` is true, Topos, Audition and Soma SHALL each run an informative and a non-informative shadow of their forward model: a copy of the live model whose context is one component wider, with zero weights on that component at creation, trained on the same inputs. At each report a shadow SHALL form, from the state the previous report left, the prediction of the current input with the live model's previous context plus the component, and its null prediction with the live model's previous null context plus the component's running mean. The informative component SHALL be a seeded projection of the current input plus seeded noise at the configured signal-to-noise ratio; the non-informative component SHALL be a seeded series with the running mean and variance of the earlier inputs' projections, computed without the current input, so it is independent of it. The live model, its reports, its intensities and the competition SHALL be unchanged by the control.

#### Scenario: Hindsight equals the live prediction
- **WHEN** a shadow is fed the same inputs and contexts as the live model with the extra component held at 0
- **THEN** its hindsight errors and null errors equal the live model's errors and null errors at every report

#### Scenario: The live report is untouched
- **WHEN** two identically seeded Topos instances receive the same frames and broadcasts, one with the control enabled
- **THEN** their reports carry equal `prediction_error`, `context_gain`, `null_prediction_error` and `mean_prediction_error`

#### Scenario: Live weights and random states are untouched
- **WHEN** a full Topos or Soma run with the control enabled is compared with the same run without it, from the same seeds
- **THEN** the live model's weights and the Python, numpy and torch random states are identical

### Requirement: Within-run verdict per processor
The control SHALL count an awake report when the live gain, the live model's running mean error and both shadow error differences are defined and finite and the mean error is above 0. All three gains SHALL be divided by that same live mean error. It SHALL report the cumulative means `ig_with`, `ig_without` (the live gain) and `ig_noise`, `effect = ig_with - ig_without` and `noise_effect = ig_noise - ig_without`. With `min_effect` (above 0) and `min_reports` (at least 1) configured, the processor SHALL pass when at least `min_reports` reports were counted, `effect` reaches `min_effect` and `noise_effect` does not. Without either, the verdict fields SHALL be null.

#### Scenario: An informative component is detected and a non-informative one is not
- **WHEN** the control runs on a processor whose inputs are unpredictable from the past, with `snr` 100 and `min_effect` 0.02
- **THEN** `detected` is true, `noise_detected` is false and `passed` is true

#### Scenario: Too few reports
- **WHEN** the informative component is detected but fewer than `min_reports` reports were counted
- **THEN** `passed` is false

#### Scenario: No minimum effect, no verdict
- **WHEN** the control runs without `min_effect`
- **THEN** the information-gain means are numbers and `detected`, `noise_detected` and `passed` are null

### Requirement: Off by default, set only from the study configuration
The shipped configuration SHALL leave `[positive_control]` disabled with no `min_effect` or `snr`. The control SHALL be read only from that section, SHALL refuse to start when enabled without `snr`, and SHALL reject unknown keys. A control that raises SHALL publish a last result marked failed, final and not passed, and SHALL be switched off for the run without interrupting perception; a failure to publish that record SHALL be logged at ERROR level. The shadows SHALL skip a non-finite input without changing their state, and SHALL run off the event loop.

#### Scenario: Enabled without a signal-to-noise ratio
- **WHEN** a processor is built with `[positive_control]` enabled and no `snr`
- **THEN** construction fails with an error naming `[positive_control].snr`

### Requirement: Results are recorded and checked for every processor
Each counted report SHALL publish the cumulative result as `positive_control.result` on `positive_control.out`, a stream the cycle never reads as candidates, and a clean shutdown SHALL publish a terminal record marked `final`. An offline check SHALL take each processor's last result in a run and re-derive its verdict from the numbers, never from the record's `passed`: the record SHALL be terminal and not failed, its numbers finite, `min_effect` above 0, `n_reports` at least `min_reports`, `effect` at least `min_effect` and `noise_effect` below it. The run SHALL pass only when Topos, Audition and Soma all pass and no record line failed to parse.

#### Scenario: A stale cumulative pass
- **WHEN** a processor's last record says `passed` true but is not a terminal record
- **THEN** the check reports no pass for that processor

#### Scenario: Unreadable records
- **WHEN** a run's records include a line that cannot be parsed
- **THEN** the check exits non-zero even if every processor's numbers pass

#### Scenario: One processor missing
- **WHEN** a run's records hold passing results for Topos and Audition and none for Soma
- **THEN** the check reports no pass, names Soma as missing, and exits non-zero
