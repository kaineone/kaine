## ADDED Requirements

### Requirement: A processor whose readings stay undefined raises a blind-sensor advisory
The welfare observer SHALL follow `interoception.out`, `vision.out` and `audition.out` and SHALL track, for each predictive processor, the run of consecutive reports whose `prediction_error` is null: `interoception.report` (processor `interoception`), `vision.report` (`vision`), `audition.perception` (`audition_acoustic`) and `audition.emotion` (`audition_tone`). A report without a `prediction_error` key SHALL NOT be a sample, and `audition.transcription` SHALL NOT be a sample. When a run reaches the threshold, the observer SHALL publish one `welfare.blind_sensor` event on `welfare.out` (source `welfare`) and write the same record to its JSONL sink. The next report of that processor with a defined error SHALL end the run and, if the advisory was raised, publish `welfare.blind_sensor_cleared` and write it to the sink. The threshold SHALL be `[evaluation.welfare].blind_sensor_samples` consecutive null samples; at its default of 0 the run SHALL instead span at least `interoceptive_distress_duration_s`, measured both as unfrozen time at which the observer read the reports and between the reports' own timestamps, and both spans SHALL reach the duration. The published payload SHALL carry only the processor label from the observer's own table and numbers the observer computed, and no field copied from a source payload. A null error SHALL still neither feed nor reset the sustained-distress tracker.

#### Scenario: A blind camera raises one advisory and clears it
- **WHEN** `blind_sensor_samples` is 3 and the vision module publishes four reports with a null `prediction_error` and then one with a defined error
- **THEN** one `welfare.blind_sensor` event with processor `vision` and `undefined_samples` 3 is published after the third report, and one `welfare.blind_sensor_cleared` event with `undefined_samples` 4 after the defined one

#### Scenario: A lagging observer cannot raise it early
- **WHEN** `blind_sensor_samples` is 0, the duration is 30 seconds, and the observer reads two null reports 40 seconds apart whose own timestamps are 5 seconds apart
- **THEN** no advisory is raised until the reports' timestamps also span 30 seconds

### Requirement: A tracked processor that stops publishing raises a silent-sensor advisory
The welfare observer SHALL raise `welfare.sensor_silent` on `welfare.out`, and write it to its sink, when a tracked processor that has published at least one report since the observer started publishes nothing for `interoceptive_distress_duration_s` of unfrozen time, and SHALL publish `welfare.sensor_silent_cleared` on that processor's next report. The tracked processors SHALL be `interoception`, `vision` and `audition_acoustic`; `audition_tone` SHALL NOT be tracked, because it reports only when speech is heard. The payload SHALL carry only the processor label and numbers the observer computed.

#### Scenario: A camera that stops publishing
- **WHEN** the vision module publishes one report and then nothing for 30 seconds of unfrozen time
- **THEN** one `welfare.sensor_silent` event with processor `vision` is published, and the vision module's next report publishes `welfare.sensor_silent_cleared`

### Requirement: The observer starts its sensor state afresh
When the welfare observer starts, it SHALL write a reset line to its JSONL sink, and readers of the rollup SHALL treat it as clearing every processor's blind and silent state. The observer SHALL read `vision.out` and `audition.out` from their tail at start, SHALL ignore for sensor tracking any report whose timestamp predates its start, and SHALL rebuild the state from live reports. Sensor tracking SHALL run after the stream's own handler, and a failure in it SHALL be logged and SHALL NOT skip the interoception module's distress handling.

#### Scenario: Old history is not replayed
- **WHEN** `vision.out` holds null reports from before the observer started
- **THEN** the observer's initial cursor for `vision.out` is the stream's tail, the stop-time drain reads none of them, and no advisory results

### Requirement: The protective response does not act on sensor advisories
`welfare.blind_sensor`, `welfare.blind_sensor_cleared`, `welfare.sensor_silent` and `welfare.sensor_silent_cleared` SHALL NOT be gray-zone events. The welfare-protective monitor SHALL NOT feed them into its windowed-repeat arm or its sustained-distress arm, and they SHALL NOT trigger any preservation, pause, end or notify action.

#### Scenario: Repeated advisories leave the monitor idle
- **WHEN** the observer publishes blind-sensor and silent-sensor advisories and clears on `welfare.out` and the monitor polls with a repeat threshold of 2
- **THEN** the monitor's repeat window stays empty, no entity is preserved and the cycle is not frozen
- **AND** two `welfare.gray_zone` events published afterwards still trigger the protective response
