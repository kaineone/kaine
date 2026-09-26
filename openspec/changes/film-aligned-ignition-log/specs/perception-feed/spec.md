## ADDED Requirements

### Requirement: The programme waits while the entity cannot perceive
The playlist clock SHALL be paused by holder, so overlapping pauses (a Hypnos replay window and a cycle freeze) keep it paused until every holder has released it, and elapsed programme time SHALL exclude every paused span. While the cycle is frozen, by any freeze holder, the playlist clock SHALL be held paused, so the programme resumes where the entity left it and no part of it is skipped.

#### Scenario: A freeze does not skip the film
- **WHEN** the entity is frozen for 60 s at 10 min into a film and then thawed
- **THEN** the programme resumes at 10 min, not 11 min

#### Scenario: Overlapping pauses
- **WHEN** a freeze begins during a Hypnos replay window and the replay window ends first
- **THEN** the clock stays paused until the freeze ends
