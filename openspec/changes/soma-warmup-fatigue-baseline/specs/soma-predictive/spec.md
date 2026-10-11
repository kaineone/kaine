## MODIFIED Requirements

### Requirement: Fatigue accumulator triggers maintenance
Soma SHALL maintain a fatigue accumulator that integrates **unexpected** prediction error over waking time and decays continuously. Unexpected error is the error beyond each channel's learned expected band (see "Learned expected prediction error per interoceptive channel"). While a hard-threshold breach is live, the accumulator SHALL integrate the raw prediction error at full weight. During the developmental warm-up, the accumulator input SHALL be damped by subtracting the warming baseline, the mean of the accumulator's own recent inputs (unexpected error, or raw error while a hard threshold is breached) before the current tick, floored at zero. When the accumulator crosses `fatigue_maintenance_threshold`, Soma SHALL publish a `soma.fatigue` event carrying the current value, the threshold and a `crossed` flag. The accumulator SHALL reset to baseline at the end of an offline-maintenance cycle.

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

#### Scenario: The warm-up baseline is the accumulator's own recent input
- **WHEN** during warm-up the unexpected error steps far above its own recent mean while staying below the mean raw prediction error
- **THEN** the accumulator input is the excess over the recent unexpected-error mean, not zero
