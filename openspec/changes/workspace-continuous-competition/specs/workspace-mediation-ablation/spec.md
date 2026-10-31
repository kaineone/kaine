## MODIFIED Requirements

### Requirement: NOT EXERCISED is the run's own outcome
The offline development run SHALL use the held candidate pool and the count-yoked matched rule of the live cycle, and SHALL report a run that is not exercised with the shared outcome NOT_EXERCISED and its reason, not as a NULL. A run is not exercised when its expected membership divergence is below `D_min`, when fewer than `n_min` broadcasts had an accessed count strictly between zero and the pool size, when it had no accessed broadcast, or when `dIG` is undefined. The suite SHALL apply its two sign tests only to the `dIG` of seeds that were exercised, SHALL report NOT_EXERCISED when no seed was exercised, and SHALL record how many seeds were and were not exercised, with each seed's φ, D and realised divergence.

#### Scenario: A run without competition is NOT EXERCISED
- **WHEN** the workspace-on arm's expected membership divergence is 0.1, below `D_min`
- **THEN** the run's verdict outcome is NOT_EXERCISED and its detail gives the reason and the statistics

#### Scenario: An unexercised seed is not evidence
- **WHEN** a seed is not exercised but its `dIG` is defined
- **THEN** that `dIG` does not enter either sign test

#### Scenario: No exercised seed
- **WHEN** no seed of a suite run is exercised
- **THEN** the suite verdict is NOT_EXERCISED and carries no p-value
