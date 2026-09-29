## ADDED Requirements

### Requirement: Identity history is unbounded by default

`[eidolon].identity_history_cap` SHALL ship as `0`, and `0` SHALL mean that no
identity-history entry is ever dropped. A positive value SHALL keep the most
recent N entries. A negative value SHALL be rejected at construction.

#### Scenario: Cap 0 keeps every entry

- **WHEN** Eidolon runs with `identity_history_cap = 0` and records more than 256
  drift observations
- **THEN** `identity_history` holds every observation

#### Scenario: A positive cap keeps the most recent entries

- **WHEN** Eidolon runs with `identity_history_cap = 4` and records 10 drift
  observations
- **THEN** `identity_history` holds the 4 most recent observations

#### Scenario: A negative cap is rejected

- **WHEN** Eidolon is constructed with `identity_history_cap = -1`
- **THEN** construction raises `ValueError`
