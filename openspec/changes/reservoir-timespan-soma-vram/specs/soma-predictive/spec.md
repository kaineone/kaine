## ADDED Requirements

### Requirement: Soma's reservoir receives the elapsed time
Soma SHALL advance its continuous-time reservoir with a timespan equal to the subjective seconds since its previous read divided by its read interval, clipped to `[0, 10]` and equal to 1.0 on the first read. A forward model supplied by a plugin SHALL receive a timespan only if it declares that it accepts one.

#### Scenario: Steady cadence keeps the unit timespan
- **WHEN** Soma reads exactly once per read interval
- **THEN** each reservoir step uses a timespan of 1.0

#### Scenario: A delayed read lengthens the timespan
- **WHEN** a read arrives three read intervals after the previous one
- **THEN** that reservoir step uses a timespan of 3.0

### Requirement: Soma's eighth feature is VRAM utilisation
Soma's interoceptive feature vector SHALL carry, in slot 7, the highest GPU memory utilisation divided by 100, clamped to `[0, 1]`, and Soma's snapshot SHALL record `feature_layout = 2`. A snapshot without a feature layout SHALL restore with layout 1, in which slot 7 stays 0.0.

#### Scenario: VRAM enters the forward model
- **WHEN** the host reports 60 percent VRAM on its busiest GPU
- **THEN** slot 7 of Soma's feature vector is 0.6

#### Scenario: A preserved being keeps its layout
- **WHEN** Soma restores a snapshot that has no feature layout
- **THEN** slot 7 of its feature vector stays 0.0
