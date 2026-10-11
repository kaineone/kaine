## ADDED Requirements

### Requirement: Retired Thymos keys are ignored with a warning
The Thymos factory SHALL accept `[thymos].social_drive_time_scale_s` and
`[thymos.coupling].coupling_max_rate_per_s`, retired keys that no longer drive
anything, SHALL NOT pass them to Thymos, and SHALL log a warning for each one
present that names the key and says it is ignored. The social drive SHALL build
at its configured build rate once an interaction has occurred, with no separate
time scale. Any other key outside the factory's accepted set SHALL still stop
boot.

#### Scenario: An old operator file still boots
- **WHEN** the operator configuration sets
  `[thymos].social_drive_time_scale_s = 600.0`
- **THEN** the factory builds Thymos and logs a warning naming
  `[thymos].social_drive_time_scale_s`

#### Scenario: The legacy coupling key warns too
- **WHEN** the operator configuration sets
  `[thymos.coupling].coupling_max_rate_per_s = 0.3`
- **THEN** the factory builds Thymos and logs a warning naming
  `[thymos.coupling].coupling_max_rate_per_s`

#### Scenario: Thymos takes no social time scale
- **WHEN** the Thymos constructor's parameters are inspected
- **THEN** `social_drive_time_scale_s` is not among them
