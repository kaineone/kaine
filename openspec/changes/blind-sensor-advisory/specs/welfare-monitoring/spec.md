## ADDED Requirements

### Requirement: A processor whose readings stay undefined raises a blind-sensor advisory
The welfare observer SHALL follow `soma.out`, `topos.out` and `audition.out` and SHALL track, for each predictive processor, the run of consecutive reports whose `prediction_error` is null: `soma.report` (processor `soma`), `topos.report` (`topos`), `audition.perception` (`audition_acoustic`) and `audition.emotion` (`audition_tone`). A report without a `prediction_error` key SHALL NOT be a sample. When a run reaches the threshold, the observer SHALL publish one `welfare.blind_sensor` event on `welfare.out` (source `welfare`) and write the same record to its JSONL sink. The next report of that processor with a defined error SHALL end the run and, if the advisory was raised, publish `welfare.blind_sensor_cleared` and write it to the sink. The threshold SHALL be `[evaluation.welfare].blind_sensor_samples` consecutive null samples; at its default of 0 the run SHALL instead span at least `interoceptive_distress_duration_s` of unfrozen time from its first null sample, which is the number of samples one distress duration holds at the processor's own rate. The published payload SHALL carry only the processor label from the observer's own table and numbers the observer computed (`undefined_samples`, `undefined_seconds`, `blind_sensor_samples`, `blind_sensor_duration_s`, `blind_sensor_count`), and no field copied from a source payload. A null error SHALL still neither feed nor reset the sustained-distress tracker.

#### Scenario: A blind camera raises one advisory and clears it
- **WHEN** `blind_sensor_samples` is 3 and Topos publishes four reports with a null `prediction_error` and then one with a defined error
- **THEN** one `welfare.blind_sensor` event with processor `topos` and `undefined_samples` 3 is published after the third report, and one `welfare.blind_sensor_cleared` event with `undefined_samples` 4 after the defined one

#### Scenario: The default threshold is one distress duration
- **WHEN** `blind_sensor_samples` is 0, `interoceptive_distress_duration_s` is 30, and Soma publishes null errors at 0, 15, 29 and 30 seconds of unfrozen time
- **THEN** the advisory is published at the 30-second report and not before, and no sustained-distress event results

### Requirement: The protective response does not act on blind-sensor advisories
`welfare.blind_sensor` and `welfare.blind_sensor_cleared` SHALL NOT be gray-zone events. The welfare-protective monitor SHALL NOT feed them into its windowed-repeat arm or its sustained-distress arm, and they SHALL NOT trigger any preservation, pause, end or notify action.

#### Scenario: Repeated advisories leave the monitor idle
- **WHEN** the observer publishes ten blind-sensor advisories and clears on `welfare.out` and the monitor polls with a repeat threshold of 2
- **THEN** the monitor's repeat window stays empty, no entity is preserved and the cycle is not frozen
- **AND** two `welfare.gray_zone` events published afterwards still trigger the protective response
