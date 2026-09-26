## ADDED Requirements

### Requirement: Conscious-access rate adapts to arousal and salience
When `[cycle.access_rate].enabled` is true, the cycle SHALL compute, on every tick before deciding whether the tick is an experiential broadcast, an access drive in [0, 1] equal to the larger of a tonic part (Thymos arousal above its resting baseline, normalised to [0, 1]) and a phasic part (the highest salience among this tick's module reports above a floor, normalised to [0, 1], held as a peak that decays exponentially in subjective time). The effective experiential rate for the tick SHALL be `resting + (processing − resting) × drive`, where `resting` is the configured experiential rate and `processing` is the processing rate. Events whose source is `cycle` or `syneidesis` SHALL NOT contribute to the phasic part.

#### Scenario: Calm entity broadcasts at the resting rate
- **WHEN** arousal equals its baseline and no report exceeds the salience floor, at 10 Hz processing and a 3.333 Hz resting rate, for 300 ticks
- **THEN** between 95 and 105 ticks are experiential broadcasts

#### Scenario: Full arousal broadcasts every tick
- **WHEN** arousal is 1.0 for 100 ticks
- **THEN** every tick is an experiential broadcast

#### Scenario: A salient report raises access briefly
- **WHEN** one module report with salience 1.0 arrives on a calm tick
- **THEN** the access drive is 1.0 on that tick and decays toward 0 over the following subjective second, and the broadcast rate returns to the resting rate

#### Scenario: The cycle's own telemetry is not a report
- **WHEN** the only high-salience event on a tick has source `cycle` or `syneidesis`
- **THEN** the phasic part is 0

### Requirement: Adaptation stays within the resting rate and the processing rate
The effective experiential rate SHALL never fall below the resting rate nor exceed the processing rate. Operator rate control and fork timing profiles SHALL set the resting rate; the effective rate SHALL be recomputed every tick and SHALL NOT overwrite the resting rate.

#### Scenario: Operator lowers the resting rate
- **WHEN** the operator sets the experiential rate to 2 Hz while arousal is high
- **THEN** the effective rate stays between 2 Hz and the processing rate, and the reported resting rate is 2 Hz

### Requirement: Adaptive rate is observable and can be disabled
Every `cycle.tick` event SHALL carry the tick's effective `experiential_rate_hz` and `access_drive`, and `runtime.json` SHALL carry the resting rate, the effective rate and the drive. With `[cycle.access_rate].enabled = false` the cycle SHALL behave exactly as a fixed-rate cycle at the resting rate.

#### Scenario: Disabled adaptation is the fixed-rate cycle
- **WHEN** adaptation is disabled and arousal is 1.0
- **THEN** broadcasts occur at the resting rate and `access_drive` is reported as 0

#### Scenario: Deterministic runs stay reproducible
- **WHEN** two deterministic runs are given the same events and affect snapshots
- **THEN** they make identical broadcast decisions and report identical drives
