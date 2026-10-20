## ADDED Requirements

### Requirement: NOT EXERCISED is the harness's own outcome
The development harness SHALL report a run that is not exercised (the workspace-on
arm never had more candidates than its capacity on a tick, had no accessed broadcast,
or left `dIG` undefined) with the shared outcome NOT_EXERCISED and its reason, not as
a NULL. The suite SHALL apply its two sign tests only to the `dIG` of seeds that were
exercised, SHALL report NOT_EXERCISED when no seed was exercised, and SHALL record
how many seeds were and were not exercised.

#### Scenario: A run without competition is NOT EXERCISED
- **WHEN** the workspace-on arm's candidates never exceed its capacity
- **THEN** the run's verdict outcome is NOT_EXERCISED and its detail gives the reason

#### Scenario: An unexercised seed is not evidence
- **WHEN** a seed is not exercised but its `dIG` is defined
- **THEN** that `dIG` does not enter either sign test

#### Scenario: No exercised seed
- **WHEN** no seed of a suite run is exercised
- **THEN** the suite verdict is NOT_EXERCISED and carries no p-value
