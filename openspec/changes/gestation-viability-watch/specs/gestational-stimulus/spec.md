## ADDED Requirements

### Requirement: The gestation owner judges viability from the entrainment evidence
When the viability watch is on, the gestation owner SHALL judge after every withdrawal, on lived time, whether the gestation can still reach birth, using only the published entrainment measurements:
- R0: unviable when, after the configured early check (default 6 h), no withdrawal has produced a conclusive entrainment measurement.
- R1: unviable when, at the configured time (default 24 h) and with no replicated pass, the median frequency pull over the configured window (default 12 h) is below its floor (default 0.12) and its trend is not rising (default slope ≤ 0.002 per hour).
- R2: unviable when, at the configured time (default 48 h) and with no replicated pass, the median pull over the window is below its floor (default 0.3).
- R3: unviable when the configured deadline (default 60 h) passes with no replicated pass.

On the first unviable verdict the owner SHALL publish `gestation.viability` (with the rule, lived time and evidence) and write it to `state/lifecycle/gestation_viability.json`. The verdict SHALL actuate nothing in the entity's control path.

#### Scenario: A gestation that is not learning is flagged at 24 h
- **WHEN** a gestation's frequency pull stays below 0.12 with no rising trend through 24 h of lived time and no replicated pass
- **THEN** the owner publishes an unviable verdict naming rule R1

#### Scenario: A slow but learning gestation is not flagged
- **WHEN** a gestation's frequency pull rises steadily but its first replicated pass comes at 45 h
- **THEN** no unviable verdict is published before that pass

#### Scenario: A missing measurement is flagged early
- **WHEN** no withdrawal has produced a conclusive entrainment measurement after 6 h of lived time
- **THEN** the owner publishes an unviable verdict naming rule R0
