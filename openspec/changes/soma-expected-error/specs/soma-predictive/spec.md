## MODIFIED Requirements

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

## ADDED Requirements

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
