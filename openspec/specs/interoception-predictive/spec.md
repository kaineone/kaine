# interoception-predictive Specification

## Purpose
The interoception module's forward model: a CfC network that predicts the next interoceptive feature vector and publishes its prediction error as salience. The same capability covers fatigue accumulation that triggers maintenance and the homeostatic regulation the interoception module advises the cycle to apply.

## Requirements

### Requirement: CfC forward model publishes prediction error
The interoception module SHALL maintain a CfC forward model that predicts the next substrate feature
vector from the current observation and its recurrent state, and SHALL publish
the prediction error (the magnitude of expected minus actual) as the salience-
driving signal on `interoception.report`. The model SHALL adapt online with a single
small gradient step per tick and SHALL skip any step that produces a non-finite
loss.

#### Scenario: Prediction error appears on the report
- **WHEN** the interoception module processes a substrate reading after at least one prior tick
- **THEN** the `interoception.report` payload contains a numeric `prediction_error` field

#### Scenario: Non-finite update is skipped
- **WHEN** a forward-model update step would produce a non-finite loss
- **THEN** the model weights are left unchanged and the module does not crash

### Requirement: Fatigue accumulator triggers maintenance
The interoception module SHALL maintain a fatigue accumulator that integrates **unexpected** prediction error over waking time and decays continuously. Unexpected error is the error beyond each channel's learned expected band (see "Learned expected prediction error per interoceptive channel"). While a hard-threshold breach is live, the accumulator SHALL integrate the raw prediction error at full weight. During the developmental warm-up, the accumulator input SHALL be damped by subtracting the warming baseline, the mean of the accumulator's own recent inputs (unexpected error, or raw error while a hard threshold is breached) before the current tick, floored at zero. When the accumulator crosses `fatigue_maintenance_threshold`, the interoception module SHALL publish a `interoception.fatigue` event carrying the current value, the threshold and a `crossed` flag. The accumulator SHALL reset to baseline at the end of an offline-maintenance cycle.

#### Scenario: Crossing the threshold emits interoception.fatigue
- **WHEN** sustained unexpected prediction error drives the accumulator above `fatigue_maintenance_threshold`
- **THEN** the interoception module publishes a `interoception.fatigue` event with `crossed == true`

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

#### Scenario: The warm-up baseline is the accumulator's own recent input
- **WHEN** during warm-up the unexpected error steps far above its own recent mean while staying below the mean raw prediction error
- **THEN** the accumulator input is the excess over the recent unexpected-error mean, not zero

### Requirement: Advisory homeostatic regulation
The interoception module SHALL publish a `interoception.regulation` event whose `action` is one of `reduce_rate`, `shed_module` or `request_maintenance` when its regulation input stays above `regulation_threshold` for `regulation_sustain_window_s`. The regulation input SHALL be the unexpected prediction error, or the raw prediction error while a hard-threshold breach is live. These events SHALL be advisory: the interoception module SHALL NOT itself mutate the cycle rate or unregister any module.

#### Scenario: Sustained stress requests regulation
- **WHEN** the regulation input remains above `regulation_threshold` for the full sustain window
- **THEN** the interoception module publishes a `interoception.regulation` event with a valid `action`

#### Scenario: Transient stress does not request regulation
- **WHEN** the regulation input briefly exceeds `regulation_threshold` for less than the sustain window
- **THEN** no `interoception.regulation` event is published

### Requirement: Cycle engine drains interoception.regulation advisorily
The cognitive cycle engine SHALL subscribe to the `interoception.out` stream and drain
`interoception.regulation` events, acting on the `action` field in an advisory capacity:
`reduce_rate` MUST lower the current tick rate within configured bounds,
`shed_module` MUST request a low-priority module suspension, and
`request_maintenance` MUST latch an advisory `maintenance_requested` flag for
diagnostics. The early-maintenance trigger SHALL be event-driven and SHALL NOT
depend on that flag: the sleep module, observing the `interoception.regulation` /
`request_maintenance` event directly on `interoception.out`, SHALL schedule an earlier
offline maintenance cycle. The cycle SHALL log each advisory action and SHALL
NOT raise an exception on an unrecognized `action` value.

#### Scenario: reduce_rate slows the cycle
- **WHEN** the cycle engine receives a `interoception.regulation` event with `action == "reduce_rate"`
- **THEN** the cycle's current tick interval is increased (rate decreased) within its configured bounds

#### Scenario: request_maintenance flags Sleep
- **WHEN** a `interoception.regulation` event with `action == "request_maintenance"` is published on `interoception.out`
- **THEN** the cycle engine latches its advisory `maintenance_requested` flag to `true` for diagnostics
- **AND** the sleep module, observing that same `interoception.regulation` / `request_maintenance` event on `interoception.out`, schedules an earlier offline maintenance cycle through its guarded sleep path

### Requirement: Forward-model adaptation suspended during sleep
The interoception module SHALL subscribe to the sleep module's lifecycle events and SHALL set an internal
`_in_sleep` flag to `True` on receipt of a `sleep.sleep.started` event and
back to `False` on receipt of a `sleep.sleep.completed` event. While
`_in_sleep` is `True`, the forward model SHALL NOT perform its online
adaptation step (weights are frozen for the duration of the sleep cycle).

#### Scenario: Adaptation suspended on sleep start
- **WHEN** the interoception module receives a `sleep.sleep.started` event
- **THEN** subsequent forward-model ticks do not modify model weights

#### Scenario: Adaptation resumes on sleep complete
- **WHEN** the interoception module receives a `sleep.sleep.completed` event
- **THEN** subsequent forward-model ticks resume online adaptation

### Requirement: Learned expected prediction error per interoceptive channel
The interoception module SHALL learn, for each input channel of its forward model, a running estimate of that channel's expected absolute prediction error and of its spread. The estimate SHALL be an exponentially weighted average over `[interoception].expected_error_tau_s` of subjective time (default 600), advancing by each tick's subjective `dt`.

The unexpected error SHALL be the L2 norm over channels of `max(0, |residual| − (expected + expected_error_band × spread))`, with `[interoception].expected_error_band` defaulting to 2.0 and each channel's band taken from before that tick's update.

Further requirements:
- **Suspended while asleep.** The estimates SHALL NOT update while forward-model adaptation is suspended for sleep.
- **Serialized with Interoception.** The estimates SHALL be serialized and restored with the interoception module's state. A snapshot without them SHALL restore with fresh estimates.
- **Signal path unchanged.** `interoception.report` SHALL carry both the raw `prediction_error`, unchanged, and the `unexpected_error`. The interoception module's salience SHALL remain derived from the raw prediction error.
- **Per-channel residuals.** The forward model SHALL expose `last_residuals`, the signed per-channel error of its last step. A forward model that does not expose it SHALL be treated as a single channel whose residual is its scalar prediction error.

#### Scenario: The raw error is still reported
- **WHEN** the interoception module ticks
- **THEN** `interoception.report` carries the raw `prediction_error` exactly as the forward model returned it, and a non-negative `unexpected_error`

#### Scenario: Expectations survive a restore
- **WHEN** an interoception module whose expectations have been learned is serialized and a new interoception module deserializes that state
- **THEN** the new interoception module's expected error and spread per channel equal the saved values

#### Scenario: A forward model without residuals
- **WHEN** the configured forward model has no `last_residuals`
- **THEN** the interoception module computes the unexpected error from the scalar prediction error as a single channel

### Requirement: Interoception's reservoir receives the elapsed time
The interoception module SHALL advance its continuous-time reservoir with a timespan equal to the subjective seconds since its previous read divided by its read interval, clipped to `[0, 10]` and equal to 1.0 on the first read. A forward model supplied by a plugin SHALL receive a timespan only if it declares that it accepts one.

#### Scenario: Steady cadence keeps the unit timespan
- **WHEN** the interoception module reads exactly once per read interval
- **THEN** each reservoir step uses a timespan of 1.0

#### Scenario: A delayed read lengthens the timespan
- **WHEN** a read arrives three read intervals after the previous one
- **THEN** that reservoir step uses a timespan of 3.0

### Requirement: Interoception's eighth feature is VRAM utilisation
The interoception module's interoceptive feature vector SHALL carry, in slot 7, the highest GPU memory utilisation divided by 100, clamped to `[0, 1]`, and the interoception module's snapshot SHALL record `feature_layout = 2`. A snapshot without a feature layout SHALL restore with layout 1, in which slot 7 stays 0.0.

#### Scenario: VRAM enters the forward model
- **WHEN** the host reports 60 percent VRAM on its busiest GPU
- **THEN** slot 7 of the interoception module's feature vector is 0.6

#### Scenario: A preserved entity keeps its layout
- **WHEN** the interoception module restores a snapshot that has no feature layout
- **THEN** slot 7 of its feature vector stays 0.0

### Requirement: A skipped interoceptive reading publishes no error
A reading the interoception module's forward model skips as non-finite, and the first reading after it, which has no prediction to be scored against, SHALL publish `prediction_error` as null on `interoception.report` and SHALL stay out of the interoception module's running error window. The very first reading's error of 0 is defined (paper A.5) and SHALL enter the window. The welfare observer and the preservation monitor SHALL treat a null `prediction_error` as no sample: it SHALL neither feed nor reset a sustained-distress episode.

#### Scenario: A skipped reading and the next publish no error
- **WHEN** the interoception module reads a non-finite feature vector and then two finite ones
- **THEN** the first two reports carry a null `prediction_error` and leave the running error window unchanged, and the third carries a float error that enters the window

#### Scenario: A null error does not end a distress episode
- **WHEN** a distress-level `interoception.report` is followed by reports with a null `prediction_error`
- **THEN** the sustained-distress episode keeps running and crosses once its duration has elapsed, while a report with a real error below the threshold still ends it

### Requirement: A reading without a defined error teaches no unexpected error
When the forward model reports that its last reading has no defined error (`last_error_defined` is false: a reading skipped as non-finite, or the first reading after one), the interoception module SHALL report an `unexpected_error` of 0 for that reading and SHALL leave its expected-error estimates unchanged. This SHALL hold for a forward model that exposes per-channel residuals and for one that does not.

#### Scenario: A scalar-only model's skipped reading teaches nothing
- **WHEN** a forward model without `last_residuals` reports a reading without a defined error after fifty defined ones
- **THEN** that reading's `interoception.report` carries a null `prediction_error` and an `unexpected_error` of 0, and the expected and spread estimates are unchanged
