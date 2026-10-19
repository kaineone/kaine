## ADDED Requirements

### Requirement: In-flight guards release on the organ's published output
The action selection module SHALL release the speak guard when the language organ publishes an `external_speech` event and the think guard when it publishes an `internal_speech` event, whether or not that event is selected or accessed. The cycle SHALL forward every such event it reads from the bus to the action selection module on the tick it reads it, before that tick's selection. Each guarded policy, and the planning proposal wrapper, SHALL release its own guard of the matching kind, and the wrapper SHALL also forward the release to the wrapped policy. An event of one channel SHALL NOT release the other channel's guard, and an event from any other source SHALL release nothing. The release when the organ's output is in the coalition, and the 48 s wall-clock guard timeout, SHALL remain.

#### Scenario: Unaccessed internal speech frees the next think
- **WHEN** a think intent is in flight, the organ publishes `internal_speech` that is never accessed, and within 48 s, after the think refractory, an accessed drive crossing scores at least the think bar
- **THEN** the policy emits a think intent

#### Scenario: Unaccessed external speech frees the next speak
- **WHEN** a speak intent is in flight, the organ publishes `external_speech` that is never accessed, and within 48 s, after the speak refractory, an accessed coalition with a new signature scores at least the speak bar
- **THEN** the policy emits a speak intent

#### Scenario: The other channel stays armed
- **WHEN** both guards are armed and the organ publishes `internal_speech`
- **THEN** the think guard is released and the speak guard is still armed

#### Scenario: A failed realization still times out
- **WHEN** a guard is armed and the organ publishes nothing
- **THEN** the guard stays armed until 48 s of wall time have passed and is then released

#### Scenario: The planning wrapper holds no stale guard
- **WHEN** the planning wrapper realized a think proposal under a policy without a think guard and the organ then publishes `internal_speech`
- **THEN** the wrapper's own think guard is released and a later think proposal can be realized
