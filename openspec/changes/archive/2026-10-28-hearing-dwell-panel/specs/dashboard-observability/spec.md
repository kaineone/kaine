## ADDED Requirements

### Requirement: The development panel shows the hearing stage's dwell
`/diagnostics/maturation.json` SHALL carry, in `hearing`, `dwell_seconds` read from `state/lifecycle/hearing_stage.json` (null when the file is missing, unusable, or names a different stage than the runtime reading) and the configured `min_dwell_seconds` and `max_dwell_seconds`. The development panel SHALL show the dwell in hours against the bounds, for example "1.2 h of 1.5 to 7 h", after the band, and SHALL show no dwell when the dwell or a bound is missing or the stage is 4.

#### Scenario: Stage 3 with 4320 s of dwell
- **WHEN** the owner file holds stage 3 and dwell 4320 s, and the bounds are 5400 s and 25200 s
- **THEN** the panel shows "stage 3 of 4, below 1732.1 Hz, 1.2 h of 1.5 to 7 h"

#### Scenario: The owner file is missing
- **WHEN** `hearing_stage.json` cannot be read
- **THEN** `dwell_seconds` is null and the panel shows the stage and band without a dwell
