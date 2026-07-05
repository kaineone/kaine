## ADDED Requirements

### Requirement: Operator freeze suspends the experiential loop

The operator SHALL be able to **freeze** a running cognitive cycle: halt the tick
loop so no Syneidesis broadcast, volition, or conscious moment forms while frozen
— the entity's subjective clock stops. Freezing SHALL be a suspension, not a
shutdown: process and in-memory state are retained, no module teardown or state
flush occurs, and resuming continues from exactly where it left off. While
frozen, live perception capture (microphone, camera) SHALL be paused so no new
sensory data accumulates.

Freeze state SHALL be driven by a persisted operator control
(`state/cycle/control.json` — `{frozen, frozen_at, reason}`) carrying only
operational fields, never sensory content. Because a paused tick loop cannot read
its own resume, resume SHALL be driven by a watcher independent of the tick loop,
so a frozen cycle can always be resumed. The cycle's runtime snapshot SHALL
expose whether it is frozen.

#### Scenario: Freezing halts subjective time

- **WHEN** the operator sets the cycle control to frozen
- **THEN** the cycle stops advancing its tick index
- **AND** no workspace broadcast is published
- **AND** live microphone/camera capture is paused

#### Scenario: Resume works from a frozen state

- **WHEN** a frozen cycle's control is set back to not-frozen
- **THEN** the cycle resumes ticking from where it paused
- **AND** no cognitive state was lost across the freeze

#### Scenario: Freeze is not a shutdown

- **WHEN** the cycle is frozen
- **THEN** the cycle process keeps running and modules are not torn down
- **AND** no state-save/shutdown sequence is triggered

#### Scenario: Control carries no sensory content

- **WHEN** the freeze control file or runtime frozen-state is written
- **THEN** it contains only operational fields (frozen flag, timestamp, optional
  operator reason) and no transcribed text, beliefs, memories, or affect reasons
