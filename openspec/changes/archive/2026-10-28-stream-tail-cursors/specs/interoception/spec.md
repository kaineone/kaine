## ADDED Requirements

### Requirement: A module's live consumer starts at the stream tail
A module's live consumer of another module's stream SHALL start reading at the stream's tail at start, through one shared helper, so past events are not replayed as new. In particular the interoception module SHALL NOT reset fatigue or regulation for a `sleep.sleep.completed` published before it started, and SHALL NOT enter the asleep state for a `sleep.sleep.started` published before it started.

#### Scenario: A module's live consumer starts at the stream tail
- **WHEN** sleep.out holds earlier started and completed events and the interoception module restores fatigue 40 and starts
- **THEN** fatigue stays 40 and the module is awake
