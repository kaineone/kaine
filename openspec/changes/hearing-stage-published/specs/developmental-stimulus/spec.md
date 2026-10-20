## ADDED Requirements

### Requirement: Hearing-band stage transitions are logged and published
When the perception feed runs in stimulus-source mode with the audition module and the hearing band enabled, the cycle SHALL read the awake time from the same provider the stimulus-source audio stream reads, at least once a second, and SHALL compute the stage with the same `hearing_stage` function. On the first reading and on every change of stage it SHALL log the stage, its band and the awake time at INFO level, and SHALL publish a `development.hearing_stage` event with source `development` on `development.out` carrying `stage`, `previous_stage`, `low_hz`, `high_hz` and `awake_seconds`. A failed publish SHALL be retried on the next reading. Reporting SHALL NOT change the stage clock, the filter or the audio.

#### Scenario: The first stage is reported at start
- **WHEN** the watch first reads an awake time of 0
- **THEN** it publishes stage 0 with `previous_stage` null and the band 353.6 to 707.1 Hz, and logs it

#### Scenario: A transition is reported once
- **WHEN** the awake time crosses a quarter of `maturation_seconds`
- **THEN** one event with stage 1 and `previous_stage` 0 is published, and later readings in the same stage publish nothing

#### Scenario: A failed publish is not lost
- **WHEN** the publish of a stage-0 event fails
- **THEN** the stage-0 event is published on the next reading

#### Scenario: No watch without the audition module
- **WHEN** the audition module is disabled
- **THEN** no `development.hearing_stage` event is published
