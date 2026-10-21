## ADDED Requirements

### Requirement: The runtime file carries the current hearing stage
While the hearing-stage watch runs, the cycle SHALL write the watch's newest reading into `state/cycle/runtime.json` as `hearing_stage`, an object with `stage`, `previous_stage`, `low_hz`, `high_hz` and `awake_seconds`, on every runtime write. The reading SHALL be the one the watch last computed with `hearing_stage` and `band_edges`. Without the watch the key SHALL be absent. Writing it SHALL NOT change the published `development.hearing_stage` events, the stage clock, the filter or the audio.

#### Scenario: The stage is in the runtime file
- **WHEN** the watch has read stage 1 with the band 158.1 to 707.1 Hz
- **THEN** the next runtime.json holds `hearing_stage` with `stage` 1, `low_hz` about 158.1 and `high_hz` about 707.1

#### Scenario: No watch, no key
- **WHEN** the feed is not in stimulus-source mode
- **THEN** runtime.json has no `hearing_stage` key
