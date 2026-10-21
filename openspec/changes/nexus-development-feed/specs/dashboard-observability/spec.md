## ADDED Requirements

### Requirement: The development panel shows the hearing stage and the gate's conditions
`/diagnostics/maturation.json` SHALL return the runtime file's `hearing_stage` as `hearing` (or null), and its `development` object SHALL keep the gate status's `world` and `conditions` beside the existing keys. The development panel SHALL show the hearing stage as "stage N of 4" with its band (both edges, "below" the upper edge, or "open"), the world, each readiness marker the gate reports as not applicable, and the consolidation passes only when `conditions.c2_consolidation_required` is true; when it is false the panel SHALL say that consolidation is not required.

#### Scenario: A perceptual world without a world model
- **WHEN** the gate reports `world` "perceptual", `c2_sleep_required` and `c2_consolidation_required` false and the marker `C2_reality_model_consolidated` as not applicable
- **THEN** the panel shows the world, marks C2 not applicable and says consolidation is not required, with no pass count

#### Scenario: The hearing band in its second step
- **WHEN** runtime.json holds `hearing_stage` with stage 1 and the band 158.1 to 707.1 Hz
- **THEN** the panel shows "stage 1 of 4" and "158.1 to 707.1 Hz"

### Requirement: The perception-feed panel describes the developmental feed
In stimulus-source mode the perception-feed block SHALL carry a `stimulus_source` summary with the base heartbeat rate and drift, the colour ramp's time constant and hue gain, whether the maternal voice is on (null when its parameters cannot be read), and the hearing band's span and whether it is on, all read from the feed configuration. The panel SHALL show them and the current hearing stage. The summary SHALL hold only numbers and booleans.

#### Scenario: The shipped stimulus source
- **WHEN** the feed is `stimulus_source` with the shipped parameters
- **THEN** the panel shows a 70 bpm heartbeat, a 3600 s colour ramp, the maternal voice on and a 43200 s hearing span

### Requirement: The module grid shows the perception modules on a deterministic feed as capturing
The module grid SHALL mark the vision and audition modules capturing when the running cycle has them and the feed mode is `seeded`, `playlist`, `screen` or `stimulus_source`, or when their live sensor is active, and SHALL name the feed (the mode, or "live").

#### Scenario: The stimulus-source feed
- **WHEN** the cycle runs with the vision module and the feed mode is `stimulus_source`
- **THEN** the vision row reads capturing with the feed "stimulus_source"

#### Scenario: Feed off and no live sensor
- **WHEN** the feed mode is `off` and the camera is not live
- **THEN** the vision row is not capturing
