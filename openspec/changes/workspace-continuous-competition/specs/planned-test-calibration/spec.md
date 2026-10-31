## ADDED Requirements

### Requirement: The divergence statistics are computed per run and arm
For each run and arm, over broadcasts awake and after `T_learn`, the calibration tool SHALL compute φ, the share of broadcasts with an accessed count strictly between zero and the pool size; D, the mean of `1 − 1/C(|E|, a)` with zero when `a` is zero or `|E|`; and for the matched arm D^obs, the mean realised membership divergence from the logged counterfactual.

#### Scenario: Known counts
- **WHEN** a run has 2,000 included broadcasts, half with five candidates and one accessed and half inhibited
- **THEN** φ is 0.5 and D is 0.4

### Requirement: NOT EXERCISED is decided by divergence and opportunity
A run SHALL be NOT EXERCISED for the matched contrast when D is below `D_min = 0.25` or fewer than `n_min = 1000` broadcasts had an accessed count strictly between zero and the pool size, and for the pooled contrast when the share of broadcasts whose pooled membership differs from the competitive arm's is below `φ^pool_min = 0.25`. The three values SHALL be fixed constants of `calibration_rules.py`, checked by the settings-record loader, and the record SHALL report φ, D and D^obs for every run.

#### Scenario: Too few opportunities
- **WHEN** a pilot's D is 0.5 over 800 included broadcasts with an opportunity
- **THEN** the pilot is NOT EXERCISED for the matched contrast with the reason naming `n_min`

#### Scenario: A changed constant is refused
- **WHEN** a settings record carries `D_min = 0.2`
- **THEN** the loader refuses it

### Requirement: K = 2 sensitivity pilots never set a value
Pilot runs at `top_k = 2` SHALL declare `[planned_test].role = "sensitivity"`. The calibration tool SHALL report their contrasts and divergence statistics beside the K = 1 pilots and SHALL NOT use them to derive any setting, and a live test run SHALL refuse a seed a sensitivity pilot used.

#### Scenario: A sensitivity pilot in the plan
- **WHEN** the plan names K = 2 pilots
- **THEN** the record lists their statistics and every derived value equals the value computed without them
