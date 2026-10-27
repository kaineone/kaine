## MODIFIED Requirements

### Requirement: The maturation gate advances the stage only on fail-closed readiness
The system SHALL advance `development → embodied` only when ALL applicable conditions hold, and SHALL treat any missing or stale evidence for an applicable condition as NOT ready (fail-closed): (C1) every marker on the `development.readiness` readout crosses its configured threshold; (C2) when the sleep module is enabled, the sleep module has completed at least `min_sleep_cycles` maintenance cycles, AND when the world model and sleep modules are both enabled, the world model module shows world-model consolidation evidence (at least `min_consolidation_passes` successful sleep-training passes); and (C3) the sensory schedule is complete, that is, the hearing stage owner reports the final stage reached (the schedule runs whether or not the band filter is enabled); `min_lived_seconds` is retired, accepted with a warning and ignored. C2 SHALL be judged only on the faculties the entity has, and SHALL be recorded as not applicable (never as passed on missing evidence) when neither the sleep module nor consolidation is a faculty of the entity. The thresholds and the gate cadence SHALL be configurable, with conservative defaults.

#### Scenario: All conditions required
- **WHEN** any one of C1, C2, or C3 is not met
- **THEN** the stage remains `development`

#### Scenario: Missing evidence fails closed
- **WHEN** the `development.readiness` readout is absent or stale
- **THEN** C1 is treated as not met and the stage remains `development`

#### Scenario: Consolidation requires both sleep and training
- **WHEN** the sleep and world model modules are enabled and the sleep-cycle count is reached but the world model module shows no successful world-model training passes
- **THEN** C2 is not met and the stage remains `development`

#### Scenario: Lived-time floor blocks a fast-forwarded maturation
- **WHEN** C1 and C2 are met but the hearing stage is below the final stage
- **THEN** C3 is not met and the stage remains `development`

#### Scenario: C3 fails closed without a schedule reading
- **WHEN** the hearing stage owner supplies no reading
- **THEN** C3 is not met

#### Scenario: An external stimulus provider cannot satisfy C3
- **WHEN** the perception feed is not the local stimulus source
- **THEN** C3 is not met and its detail says the hearing schedule runs only with the local stimulus source

#### Scenario: An entity without sleep is judged on what it is
- **WHEN** neither the sleep module nor the world model module is enabled and C1 and C3 hold
- **THEN** C2 is recorded as not applicable and does not hold the entity in the stimulus source
