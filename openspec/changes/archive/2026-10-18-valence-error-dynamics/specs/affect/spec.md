## ADDED Requirements

### Requirement: Valence follows error dynamics
At each affect update with `dt > 0` the module SHALL relax valence by `v <- v + (v_inf - v) * (1 - exp(-dt / tau_v))`. Under `valence_rule = "error_dynamics"` (the default) the target SHALL be `v_inf = clip(pl + <w>_f - <w>_s, -1, 1)`, where `pl` is the appraisal's pleasantness check (tanh of `valence_progress_gain` times the signed learning progress, plus the perceived-emotion term) and `<w>_f`, `<w>_s` are time-decayed means of the interoception module's reported wellness with time constants `fast_time_constant_s` and `slow_time_constant_s` (paper A.4). Before any wellness report the difference SHALL be 0. Under `valence_rule = "wellness_level"` the target SHALL be `clip(pl + w - 0.5, -1, 1)` with `w` the last reported wellness, and every published event and the serialized state SHALL equal those of the build before this change. Any other value SHALL raise `ValueError`.

#### Scenario: Falling error raises valence
- **WHEN** a perceptual module's raw error falls steadily and wellness is constant
- **THEN** valence rises above 0

#### Scenario: Rising error lowers valence
- **WHEN** a perceptual module's raw error rises steadily and wellness is constant
- **THEN** valence falls below 0

#### Scenario: A steady healthy host is neutral
- **WHEN** wellness is held at 0.9 with constant perceptual error for 600 s
- **THEN** valence is within 0.01 of 0, where the previous rule rests near 0.4

#### Scenario: Falling wellness lowers valence
- **WHEN** wellness falls from 0.9 to 0.5 with constant perceptual error
- **THEN** valence falls below 0, and it returns toward 0 once wellness is steady

#### Scenario: Valence stays bounded
- **WHEN** errors and wellness take extreme values in any order
- **THEN** valence stays in [-1, 1]

#### Scenario: The previous rule is unchanged
- **WHEN** the module is built with `valence_rule = "wellness_level"` and driven by the same seeded event trace as origin/main
- **THEN** every published event and the serialized state are identical

### Requirement: Wellness means carry through sleep and persist
Under `valence_rule = "error_dynamics"` the wellness means SHALL survive the sleep's affective reset and SHALL be serialized and restored with the module state; invalid stored values SHALL be ignored.

#### Scenario: Sleep keeps the wellness means
- **WHEN** the module resets for sleep after wellness reports
- **THEN** the wellness means are unchanged

#### Scenario: A restore keeps the wellness means
- **WHEN** a module is serialized and a fresh one deserializes the state
- **THEN** the next update gives the same valence target
