## ADDED Requirements

### Requirement: Bus-driven rate control surface
The cognitive cycle SHALL subscribe to a `cycle.control` stream and,
on each event with type `cycle.set_rates`, SHALL update its
`processing_rate_hz` and/or `experiential_rate_hz` from the event's
payload (using whichever of `processing_rate_hz` or
`experiential_rate_hz` keys are present). After applying the update,
the cycle SHALL publish a `cycle.rates` event reflecting the new
state.

#### Scenario: cycle.set_rates with only processing_rate_hz
- **WHEN** an event with payload `{"processing_rate_hz": 5.0}`
  arrives on `cycle.control` while the cycle is running
- **THEN** the cycle's `processing_rate_hz` becomes `5.0` and a
  `cycle.rates` event is published whose payload reports the new
  value

#### Scenario: cycle.set_rates with both rates
- **WHEN** an event with payload
  `{"processing_rate_hz": 10.0, "experiential_rate_hz": 2.0}` arrives
- **THEN** both rates are updated and the published `cycle.rates`
  event reflects both

#### Scenario: Invalid rate value rejected without disrupting cycle
- **WHEN** an event arrives with `processing_rate_hz=-1`
- **THEN** the cycle's rate is NOT updated and the cycle continues
  ticking; a `cycle.rates` event is NOT published for the failed
  update

### Requirement: Experiential broadcast ratios accurate over many ticks
The cycle's experiential accumulator SHALL maintain accurate
broadcast ratios across an arbitrary number of ticks. Over 1000
ticks at the configured ratio R = experiential_rate / processing_rate,
the number of experiential broadcasts SHALL be within ±2 of
`1000 * R`.

#### Scenario: 3-to-1 ratio over 30 ticks broadcasts 10±2
- **WHEN** processing_rate_hz=3.0 and experiential_rate_hz=1.0 and
  the cycle runs 30 ticks
- **THEN** the count of experiential broadcasts is between 8 and 12

#### Scenario: 100-to-1 ratio over 200 ticks broadcasts 2±2
- **WHEN** processing_rate_hz=100.0 and experiential_rate_hz=1.0 and
  the cycle runs 200 ticks
- **THEN** the count of experiential broadcasts is between 0 and 4
