## MODIFIED Requirements

### Requirement: NAR belief-revision burst removed
Hypnos SHALL NOT execute a standalone belief-revision step-burst during
maintenance, and SHALL NOT take a Nous collaborator to step. Belief revision
SHALL occur as replayed traces re-enter the workspace and Nous (pymdp) updates
beliefs on them in the normal cognitive cycle.

#### Scenario: No NAR burst fires during maintenance
- **WHEN** a maintenance cycle runs
- **THEN** no phase named for belief revision runs and Nous processes replayed
  traces via the standard pymdp update path

#### Scenario: Hypnos has no Nous argument
- **WHEN** the Hypnos constructor's parameters are inspected
- **THEN** neither `nous_process` nor `nous_step_burst` is among them
