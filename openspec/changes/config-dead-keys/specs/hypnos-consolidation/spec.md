## MODIFIED Requirements

### Requirement: NAR belief-revision burst removed
The sleep module SHALL NOT execute a standalone belief-revision step-burst during
maintenance, and SHALL NOT take a planning module collaborator to step. Belief revision
SHALL occur as replayed traces re-enter the workspace and the planning module (pymdp) updates
beliefs on them in the normal cognitive cycle.

#### Scenario: No NAR burst fires during maintenance
- **WHEN** a maintenance cycle runs
- **THEN** no phase named for belief revision runs and the planning module processes replayed
  traces via the standard pymdp update path

#### Scenario: Sleep has no Planning argument
- **WHEN** the sleep module's constructor's parameters are inspected
- **THEN** neither `nous_process` nor `nous_step_burst` is among them
