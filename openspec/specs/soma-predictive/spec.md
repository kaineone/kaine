# soma-predictive Specification

## Purpose
Soma's forward model: a CfC network that predicts the next interoceptive feature vector and publishes its prediction error as salience. The same capability covers fatigue accumulation that triggers maintenance and the homeostatic regulation Soma advises the cycle to apply.

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
Soma SHALL maintain a fatigue accumulator that integrates **unexpected** prediction error over waking time and decays continuously. Unexpected error is the error beyond each channel's learned expected band (see "Learned expected prediction error per interoceptive channel"). While a hard-threshold breach is live, the accumulator SHALL integrate the raw prediction error at full weight. During the developmental warm-up, the existing dampening against the warming baseline SHALL apply to the accumulator input. When the accumulator crosses `fatigue_maintenance_threshold`, Soma SHALL publish a `soma.fatigue` event carrying the current value, the threshold and a `crossed` flag. The accumulator SHALL reset to baseline at the end of an offline-maintenance cycle.

#### Scenario: Crossing the threshold emits soma.fatigue
- **WHEN** sustained unexpected prediction error drives the accumulator above `fatigue_maintenance_threshold`
- **THEN** Soma publishes a `soma.fatigue` event with `crossed == true`

#### Scenario: Fatigue decays without error
- **WHEN** unexpected prediction error is zero for a period
- **THEN** the accumulator value strictly decreases over that period

#### Scenario: Irreducible channel variability does not build sleep pressure
- **WHEN** one input channel carries steady but unpredictable variability, such as a driven self-rhythm, and every other channel is steady, after its expectation has been learned
- **THEN** the raw prediction error stays well above zero, the unexpected error stays near zero, and the accumulator does not cross its threshold over hours

#### Scenario: Genuine interoceptive surprise still builds sleep pressure
- **WHEN** a channel's error rises far beyond its learned band and stays there, such as a sustained CPU surge
- **THEN** the unexpected error rises with it and the accumulator accrues toward its threshold

#### Scenario: A hard-threshold breach integrates raw error
- **WHEN** a hard-threshold breach is live
- **THEN** the accumulator integrates the raw prediction error, not the unexpected error

#### Scenario: Maintenance resets fatigue
- **WHEN** an offline-maintenance cycle completes
- **THEN** the fatigue accumulator returns to its baseline value

### Requirement: Advisory homeostatic regulation
Soma SHALL publish a `soma.regulation` event whose `action` is one of `reduce_rate`, `shed_module` or `request_maintenance` when its regulation input stays above `regulation_threshold` for `regulation_sustain_window_s`. The regulation input SHALL be the unexpected prediction error, or the raw prediction error while a hard-threshold breach is live. These events SHALL be advisory: Soma SHALL NOT itself mutate the cycle rate or unregister any module.

#### Scenario: Sustained stress requests regulation
- **WHEN** the regulation input remains above `regulation_threshold` for the full sustain window
- **THEN** Soma publishes a `soma.regulation` event with a valid `action`

#### Scenario: Transient stress does not request regulation
- **WHEN** the regulation input briefly exceeds `regulation_threshold` for less than the sustain window
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

### Requirement: Learned expected prediction error per interoceptive channel
Soma SHALL learn, for each input channel of its forward model, a running estimate of that channel's expected absolute prediction error and of its spread. The estimate SHALL be an exponentially weighted average over `[soma].expected_error_tau_s` of subjective time (default 600), advancing by each tick's subjective `dt`.

The unexpected error SHALL be the L2 norm over channels of `max(0, |residual| − (expected + expected_error_band × spread))`, with `[soma].expected_error_band` defaulting to 2.0 and each channel's band taken from before that tick's update.

Further requirements:
- **Suspended while asleep.** The estimates SHALL NOT update while forward-model adaptation is suspended for Hypnos sleep.
- **Serialized with Soma.** The estimates SHALL be serialized and restored with Soma's state. A snapshot without them SHALL restore with fresh estimates.
- **Signal path unchanged.** `soma.report` SHALL carry both the raw `prediction_error`, unchanged, and the `unexpected_error`. Soma's salience SHALL remain derived from the raw prediction error.
- **Per-channel residuals.** The forward model SHALL expose `last_residuals`, the signed per-channel error of its last step. A forward model that does not expose it SHALL be treated as a single channel whose residual is its scalar prediction error.

#### Scenario: The raw error is still reported
- **WHEN** Soma ticks
- **THEN** `soma.report` carries the raw `prediction_error` exactly as the forward model returned it, and a non-negative `unexpected_error`

#### Scenario: Expectations survive a restore
- **WHEN** a Soma whose expectations have been learned is serialized and a new Soma deserializes that state
- **THEN** the new Soma's expected error and spread per channel equal the saved values

#### Scenario: A forward model without residuals
- **WHEN** the configured forward model has no `last_residuals`
- **THEN** Soma computes the unexpected error from the scalar prediction error as a single channel
