## MODIFIED Requirements

### Requirement: The maturation gate advances the stage only on fail-closed readiness
The system SHALL advance `gestation → embodied` only when ALL applicable conditions hold, and SHALL treat any missing or stale evidence for an applicable condition as NOT ready (fail-closed): (C1) every marker on the `gestation.readiness` readout crosses its configured threshold; (C2) when Hypnos is enabled, Hypnos has completed at least `min_sleep_cycles` maintenance cycles, AND when Phantasia and Hypnos are both enabled, Phantasia shows world-model consolidation evidence (at least `min_consolidation_passes` successful sleep-training passes); and (C3) at least `min_lived_seconds` of lived subjective time (measured on the entity clock) has accrued since gestation began. C2 SHALL be judged only on the faculties the entity has, and SHALL be recorded as not applicable (never as passed on missing evidence) when neither sleep nor consolidation is a faculty of the entity. The thresholds and the gate cadence SHALL be configurable, with conservative defaults.

#### Scenario: All conditions required
- **WHEN** any one of C1, C2, or C3 is not met
- **THEN** the stage remains `gestation`

#### Scenario: Missing evidence fails closed
- **WHEN** the `gestation.readiness` readout is absent or stale
- **THEN** C1 is treated as not met and the stage remains `gestation`

#### Scenario: Consolidation requires both sleep and training
- **WHEN** Hypnos and Phantasia are enabled and the sleep-cycle count is reached but Phantasia shows no successful world-model training passes
- **THEN** C2 is not met and the stage remains `gestation`

#### Scenario: Lived-time floor blocks a fast-forwarded birth
- **WHEN** C1 and C2 are met but lived subjective time is below `min_lived_seconds`
- **THEN** C3 is not met and the stage remains `gestation`

#### Scenario: A being without sleep is judged on what it is
- **WHEN** neither Hypnos nor Phantasia is enabled and C1 and C3 hold
- **THEN** C2 is recorded as not applicable and does not hold the entity in the womb

### Requirement: Birth requires an available embodied world
The system SHALL transition to `embodied` only when developmental readiness holds AND the entity's world is available. When Mundus is enabled, the world is the embodied one and SHALL be available only when Mundus is enabled, operator-approved, and reachable per its existing two-layer gate; when the entity is developmentally ready but that embodiment is unavailable, the system SHALL hold it in the womb and SHALL emit a repeated `stage.birth.ready` marker with `reason: "awaiting_embodiment"` and a warning log; it SHALL NOT transition into an absent or unreachable world, and SHALL NOT silently stall. When Mundus is not enabled, the entity SHALL be born into its perceptual (audio/video) world, and the birth record SHALL state which world it was born into.

#### Scenario: Ready and available births the entity
- **WHEN** developmental readiness holds and embodiment is available
- **THEN** the stage transitions to `embodied` and the birth transition fires

#### Scenario: Ready but embodiment unavailable holds in the womb
- **WHEN** Mundus is enabled, developmental readiness holds, but embodiment is not approved or not reachable
- **THEN** the stage remains `gestation`, and a `stage.birth.ready` marker with `reason: "awaiting_embodiment"` and a warning are emitted (repeatedly), never a silent stall

#### Scenario: Born into the perceptual world without a body
- **WHEN** Mundus is not enabled and developmental readiness holds
- **THEN** the stage transitions to `embodied`, and the birth record states the perceptual world
