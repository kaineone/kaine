# soma-predictive Specification

## Purpose
TBD - created by archiving change soma-forward-model-fatigue. Update Purpose after archive.
## Requirements
### Requirement: CfC forward model publishes prediction error
Soma SHALL maintain a CfC forward model that predicts the next substrate feature
vector from the current observation and its recurrent state, and SHALL publish
the prediction error (the magnitude of expected minus actual) as the salience-
driving signal on `soma.report`. The model SHALL adapt online with a single
small gradient step per tick and SHALL skip any step that produces a non-finite
loss.

#### Scenario: Prediction error appears on the report
- **WHEN** Soma processes a substrate reading after at least one prior tick
- **THEN** the `soma.report` payload contains a numeric `prediction_error` field

#### Scenario: Non-finite update is skipped
- **WHEN** a forward-model update step would produce a non-finite loss
- **THEN** the model weights are left unchanged and the module does not crash

### Requirement: Fatigue accumulator triggers maintenance
Soma SHALL maintain a fatigue accumulator that integrates prediction error over
waking time and decays continuously. When the accumulator crosses
`fatigue_maintenance_threshold`, Soma SHALL publish a `soma.fatigue` event
carrying the current value, the threshold, and a `crossed` flag. The accumulator
SHALL reset to baseline at the end of an offline-maintenance cycle.

#### Scenario: Crossing the threshold emits soma.fatigue
- **WHEN** sustained prediction error drives the accumulator above
  `fatigue_maintenance_threshold`
- **THEN** Soma publishes a `soma.fatigue` event with `crossed == true`

#### Scenario: Fatigue decays without error
- **WHEN** prediction error is zero for a period
- **THEN** the accumulator value strictly decreases over that period

#### Scenario: Maintenance resets fatigue
- **WHEN** an offline-maintenance cycle completes
- **THEN** the fatigue accumulator returns to its baseline value

### Requirement: Advisory homeostatic regulation
Soma SHALL publish a `soma.regulation` event whose `action` is one of
`reduce_rate`, `shed_module`, or `request_maintenance` when prediction error
stays above `regulation_threshold` for `regulation_sustain_window_s`. These
events SHALL be advisory: Soma SHALL NOT itself mutate the cycle rate or
unregister any module.

#### Scenario: Sustained stress requests regulation
- **WHEN** prediction error remains above `regulation_threshold` for the full
  sustain window
- **THEN** Soma publishes a `soma.regulation` event with a valid `action`

#### Scenario: Transient stress does not request regulation
- **WHEN** prediction error briefly exceeds `regulation_threshold` for less than
  the sustain window
- **THEN** no `soma.regulation` event is published

### Requirement: Cycle engine drains soma.regulation advisorily
The cognitive cycle engine SHALL subscribe to the `soma.out` stream and drain
`soma.regulation` events, acting on the `action` field in an advisory capacity:
`reduce_rate` MUST lower the current tick rate within configured bounds,
`shed_module` MUST request a low-priority module suspension, and
`request_maintenance` MUST latch an advisory `maintenance_requested` flag for
diagnostics. The early-maintenance trigger SHALL be event-driven and SHALL NOT
depend on that flag: Hypnos, observing the `soma.regulation` /
`request_maintenance` event directly on `soma.out`, SHALL schedule an earlier
offline maintenance cycle. The cycle SHALL log each advisory action and SHALL
NOT raise an exception on an unrecognized `action` value.

#### Scenario: reduce_rate slows the cycle
- **WHEN** the cycle engine receives a `soma.regulation` event with `action == "reduce_rate"`
- **THEN** the cycle's current tick interval is increased (rate decreased) within its configured bounds

#### Scenario: request_maintenance flags Hypnos
- **WHEN** a `soma.regulation` event with `action == "request_maintenance"` is published on `soma.out`
- **THEN** the cycle engine latches its advisory `maintenance_requested` flag to `true` for diagnostics
- **AND** Hypnos, observing that same `soma.regulation` / `request_maintenance` event on `soma.out`, schedules an earlier offline maintenance cycle through its guarded sleep path

### Requirement: Forward-model adaptation suspended during Hypnos sleep
Soma SHALL subscribe to Hypnos lifecycle events and SHALL set an internal
`_in_hypnos` flag to `True` on receipt of a `hypnos.sleep.started` event and
back to `False` on receipt of a `hypnos.sleep.completed` event. While
`_in_hypnos` is `True`, the forward model SHALL NOT perform its online
adaptation step (weights are frozen for the duration of the sleep cycle).

#### Scenario: Adaptation suspended on sleep start
- **WHEN** Soma receives a `hypnos.sleep.started` event
- **THEN** subsequent forward-model ticks do not modify model weights

#### Scenario: Adaptation resumes on sleep complete
- **WHEN** Soma receives a `hypnos.sleep.completed` event
- **THEN** subsequent forward-model ticks resume online adaptation

