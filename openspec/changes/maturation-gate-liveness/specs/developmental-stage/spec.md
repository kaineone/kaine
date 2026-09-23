## ADDED Requirements

### Requirement: Lived time and evidence accumulate across restarts
The maturation gate SHALL persist the entity's lived subjective time and its consolidation evidence in the stage file, accumulating the entity-clock delta and module-counter deltas while gestating, so that restarts neither reset the evidence nor count downtime as lived time.

#### Scenario: Restart mid-gestation
- **WHEN** a gestating entity has accumulated 3 hours of subjective time and two sleeps, and Nexus and the cycle restart
- **THEN** after restart the gate reports at least 3 hours lived and two sleeps

#### Scenario: Downtime is not lived time
- **WHEN** the host is down for 12 hours between two boots
- **THEN** the lived-time total does not increase by those 12 hours

### Requirement: Gestation requires a live womb stimulus
Gestation staging SHALL require evidence of a live womb stimulus on the perception seam (a fresh womb event within a bounded window) and SHALL NOT rely on a configuration value. Without it, the system SHALL refuse staging with a repeated operator-visible reason and SHALL NOT lock the perception locus.

#### Scenario: No womb present
- **WHEN** `[developmental_stage].enabled` is true and no womb event has been observed
- **THEN** staging is refused with a visible reason, the locus stays unlocked, and the entity is not pinned to a senseless locus

### Requirement: Embodiment is inactive during gestation
While the stage is `gestation`, the embodiment module SHALL NOT be initialised, and birth readiness SHALL be judged with a public reachability probe of the embodiment adapter.

#### Scenario: Mundus enabled during gestation
- **WHEN** Mundus is enabled in configuration and the stage is `gestation`
- **THEN** Mundus is not started, and the gate still determines embodiment availability through the adapter's reachability probe

### Requirement: Readiness readouts are fresh and typed
The gate SHALL decode readiness readouts with the bus codec, accept only events whose type is `gestation.readiness`, and reject readouts older than a configured multiple of the gate cadence or published before the current boot.

#### Scenario: Stale readout from a previous boot
- **WHEN** the only `gestation.readiness` event on the stream was published before the current boot
- **THEN** C1 is not satisfied
