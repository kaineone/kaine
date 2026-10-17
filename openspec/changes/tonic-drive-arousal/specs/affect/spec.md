## ADDED Requirements

### Requirement: Arousal relaxes toward a drive-raised target
At each affect update the module SHALL relax arousal by `a <- a + (a_inf - a) * min(1, lambda * dt)` with `a_inf = a_0 + gamma_D * (1 - a_0) * v*`, where `a_0` is the baseline arousal, `lambda` is `drift_rate_per_s`, `gamma_D` is `drive_arousal_gain` (default 0.2) and `v*` is the largest drive value at the start of the update (paper A.4 item 3). Dominance SHALL keep relaxing toward its baseline. `gamma_D` SHALL be finite and in `[0, 1]`; with `gamma_D = 0` the update SHALL equal the previous relaxation toward `a_0`.

#### Scenario: A deprived entity rests above baseline
- **WHEN** boredom is held at 0.9 and the other drives at 0, no alert arrives, and the module ticks for 300 s of entity time
- **THEN** arousal is within 0.005 of 0.3 + 0.2 x 0.7 x 0.9 = 0.426

#### Scenario: A satisfied entity rests at baseline
- **WHEN** every drive is 0 and the module ticks from an arousal of 0.8
- **THEN** arousal relaxes to within 0.005 of 0.3

#### Scenario: The sleep reset returns arousal to baseline
- **WHEN** a deprived module at the raised target is reset by sleep
- **THEN** arousal is 0.3 and the next tick's target is 0.3

#### Scenario: A gain of 0 keeps the old relaxation
- **WHEN** the module is built with `drive_arousal_gain = 0` and ticks with deprived drives
- **THEN** every arousal value equals that of the relaxation toward `a_0`

#### Scenario: The gain is validated
- **WHEN** the module is built with `drive_arousal_gain` of -0.1, 1.5 or NaN
- **THEN** construction raises `ValueError`
