# soma-predictive (spec delta — DESIGN ONLY)

## ADDED Requirements

### Requirement: Developmental warm-up gates the cold-start allostatic response
Soma SHALL apply a bounded developmental **warm-up** while its interoceptive forward
model is still learning this host's substrate baseline, during which it WITHHOLDS the
punitive allostatic actions that its untrained prediction error would otherwise
trigger, WITHOUT altering the prediction-error signal it publishes. The
warm-up SHALL be controlled by `[soma]` config: `regulation_warmup_enabled` (a
boolean, default enabled), `regulation_warmup_min_samples`, and
`regulation_warmup_min_seconds`, with an optional error-stabilization guard
(`regulation_warmup_require_error_stabilized`, default off).

While `warmup_active` is true, Soma SHALL WITHHOLD publishing a `soma.regulation`
advisory (`reduce_rate`, `shed_module`, `request_maintenance`) whose sole cause is
learned prediction error, so the cycle engine does not throttle the rate, shed a
module, or trigger early maintenance; and Soma SHALL DAMPEN the cold-start
prediction error's contribution to the fatigue accumulator so an untrained model
does not artificially cross `fatigue_maintenance_threshold`.

Soma SHALL NOT withhold or dampen anything driven by the absolute
`[soma.thresholds]` limits (see the hard-threshold-override requirement), and SHALL
NOT alter the `soma.report` / `soma.fatigue` signal path (see the observability
requirement). When `regulation_warmup_enabled` is false, Soma's cold-start behavior
SHALL be identical to a build without this warm-up.

#### Scenario: Untrained cold-start error does not actuate regulation
- **WHEN** a freshly-booted Soma's prediction error is sustained above
  `regulation_threshold` for the sustain window during warm-up, with no
  `[soma.thresholds]` limit breached
- **THEN** no actuating `soma.regulation` advisory is published, and the cycle
  engine does not reduce the rate, shed a module, or schedule early maintenance

#### Scenario: Cold-start error does not force premature maintenance
- **WHEN** the same sustained cold-start error is integrated by the fatigue
  accumulator during warm-up
- **THEN** the cold-start contribution is dampened such that the accumulator does
  not cross `fatigue_maintenance_threshold` from model ignorance alone

#### Scenario: Warm-up ends and normal regulation resumes
- **WHEN** the warm-up end condition is met (see the end-condition requirement)
- **THEN** `warmup_active` becomes false and subsequent sustained prediction error
  actuates `soma.regulation` and fatigue exactly as in a build without warm-up

#### Scenario: Feature disabled reproduces prior behavior
- **WHEN** `regulation_warmup_enabled` is false
- **THEN** cold-start prediction error drives regulation and fatigue exactly as it
  did before this change, with no warm-up gating

### Requirement: Hard substrate-safety thresholds are never gated by warm-up
Soma SHALL keep the absolute substrate-safety limits in `[soma.thresholds]` (CPU/RAM
percent, GPU temperature and VRAM, cycle latency), detected by the threshold anomaly
detector, fully live during warm-up. These limits are NOT learned predictions and
SHALL NOT be gated. A concurrent hard-threshold breach SHALL OVERRIDE the warm-up
gate: on any tick where a `[soma.thresholds]` limit is breached, Soma SHALL publish
and allow actuation of the corresponding `soma.regulation` advisory and SHALL
integrate the fatigue accumulator at full weight, even during warm-up. The
alert-driven salience and the `alerts` list on `soma.report` SHALL be unaffected by
warm-up at all times.

#### Scenario: Real overheat during warm-up still triggers regulation
- **WHEN** a `[soma.thresholds]` limit (e.g. GPU temperature ≥ 83 °C) is breached
  during warm-up
- **THEN** the regulation advisory is published and actuated, and fatigue integrates
  at full weight, exactly as outside warm-up

#### Scenario: Threshold alerts remain visible during warm-up
- **WHEN** a hard threshold is breached during warm-up
- **THEN** the breach still appears in the `alerts` list and drives alert salience on
  `soma.report`, unchanged by warm-up

### Requirement: Warm-up completion is signal-based and configurable
Soma SHALL end the warm-up only when BOTH a minimum number of forward-model
online-adaptation samples (`regulation_warmup_min_samples`) AND a minimum of lived
subjective time (`regulation_warmup_min_seconds`, measured on the injected entity
clock) have accumulated — mirroring the individuation boundary's warmed-up-signal
precedent (a minimum of logged lived events and a minimum of lived running time). An
optional error-stabilization guard, when enabled, SHALL be an ADDITIONAL required
condition that can only extend, never shorten, the warm-up window.

#### Scenario: Both minimums are required
- **WHEN** only one of the sample-count or lived-time minimums has been reached
- **THEN** `warmup_active` remains true

#### Scenario: Conjunction satisfied ends warm-up
- **WHEN** both the sample-count and lived-time minimums are reached (and the
  optional stabilization guard, if enabled, is satisfied)
- **THEN** `warmup_active` becomes false

### Requirement: Warm-up withholding is observable and never silent
Soma SHALL make the warm-up auditable and SHALL NEVER silently drop an action. Soma
SHALL emit a `soma.warmup.started` marker at boot and a `soma.warmup.completed`
event carrying the `samples_seen` and `lived_seconds` that ended it. Each time an
allostatic action is withheld because of warm-up, Soma SHALL emit a
`soma.regulation.withheld` event carrying the would-be `action`, the current
`prediction_error`, and `reason: "warmup"`, and SHALL log it. Soma SHALL include a
`warmup_active` boolean on `soma.report` without altering any numeric field. The
`soma.regulation.withheld` event SHALL be non-actuating: the cycle engine SHALL NOT
change rate, shed a module, or schedule maintenance in response to it.

#### Scenario: A withheld advisory is recorded, not dropped
- **WHEN** a `reduce_rate` (or `shed_module` / `request_maintenance`) advisory is
  withheld during warm-up
- **THEN** Soma emits a `soma.regulation.withheld` event with the would-be action,
  the current prediction error, and `reason: "warmup"`, and logs it

#### Scenario: The withheld event does not actuate
- **WHEN** the cycle engine drains a `soma.regulation.withheld` event
- **THEN** it takes no allostatic action and does not raise

#### Scenario: Warm-up boundaries are marked
- **WHEN** warm-up begins and later completes
- **THEN** `soma.warmup.started` and `soma.warmup.completed` are emitted, the latter
  carrying the samples-seen and lived-seconds at completion

## MODIFIED Requirements

### Requirement: Advisory homeostatic regulation
Soma SHALL publish a `soma.regulation` event whose `action` is one of
`reduce_rate`, `shed_module`, or `request_maintenance` when prediction error
stays above `regulation_threshold` for `regulation_sustain_window_s`. These
events SHALL be advisory: Soma SHALL NOT itself mutate the cycle rate or
unregister any module. **While the developmental warm-up is active
(`warmup_active` true), Soma SHALL WITHHOLD any such advisory whose sole cause is
learned prediction error with no concurrent `[soma.thresholds]` breach, emitting a
non-actuating `soma.regulation.withheld` record instead; a concurrent
hard-threshold breach SHALL override the warm-up gate and cause the advisory to be
published and actuated normally.**

#### Scenario: Sustained stress requests regulation
- **WHEN** prediction error remains above `regulation_threshold` for the full
  sustain window
- **THEN** Soma publishes a `soma.regulation` event with a valid `action`

#### Scenario: Transient stress does not request regulation
- **WHEN** prediction error briefly exceeds `regulation_threshold` for less than
  the sustain window
- **THEN** no `soma.regulation` event is published

#### Scenario: Cold-start advisory is withheld during warm-up
- **WHEN** sustained prediction error would raise an advisory during warm-up with no
  `[soma.thresholds]` limit breached
- **THEN** the advisory is not published, a `soma.regulation.withheld` record is
  emitted, and the cycle takes no allostatic action

### Requirement: Fatigue accumulator triggers maintenance
Soma SHALL maintain a fatigue accumulator that integrates prediction error over
waking time and decays continuously. When the accumulator crosses
`fatigue_maintenance_threshold`, Soma SHALL publish a `soma.fatigue` event
carrying the current value, the threshold, and a `crossed` flag. The accumulator
SHALL reset to baseline at the end of an offline-maintenance cycle. **While the
developmental warm-up is active, Soma SHALL dampen the cold-start prediction
error's contribution to the accumulator so an untrained model does not
artificially cross the threshold; genuine error above the warming baseline, and any
tick with a concurrent `[soma.thresholds]` breach, SHALL still integrate at full
weight, and the published `fatigue_value` SHALL honestly reflect whatever actually
accrued.**

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

#### Scenario: Cold-start does not force premature maintenance during warm-up
- **WHEN** cold-start prediction error is integrated during warm-up with no
  `[soma.thresholds]` breach
- **THEN** its contribution is dampened so the accumulator does not cross
  `fatigue_maintenance_threshold` from model ignorance alone, while the published
  `fatigue_value` reflects the actual (dampened) accrual
