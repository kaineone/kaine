## ADDED Requirements

### Requirement: Spot selftest against a synthetic probe
Spot SHALL provide a selftest that constructs a scratch Spot from the given `[spot]` section, with snapshot and incident paths redirected to a temporary directory, registers one synthetic probe module, induces a failure in it, and passes only if Spot detects the failure, freezes, snapshots the probe, restarts it, releases the freeze, and writes an incident record within a bounded window. The selftest SHALL NOT import or construct any entity module, read or write entity state, or act on a live supervised target, and SHALL remove its scratch directory when it finishes.

#### Scenario: Healthy Spot passes
- **WHEN** the selftest runs against a valid `[spot]` section
- **THEN** it reports pass with the timing of each step

#### Scenario: Broken freeze path fails
- **WHEN** the freeze step does not take effect during the selftest
- **THEN** the selftest reports failure naming the freeze step

#### Scenario: Window exceeded
- **WHEN** the drill does not finish within the bounded window
- **THEN** the selftest reports failure with the reason "timed out" and the step it was in

#### Scenario: Scratch storage removed
- **WHEN** the selftest finishes, passing or failing
- **THEN** its scratch directory no longer exists

### Requirement: Loss of supervision escalates during an unattended run
When the cycle runs in unattended mode and Spot's supervision task exits for any reason other than shutdown, the cycle SHALL run Spot's escalation — final snapshot, shutdown of every module, and `escalation.json` — and SHALL send a caretaker notice. In operator-present and research modes this requirement SHALL NOT apply.

#### Scenario: Spot task crashes unattended
- **WHEN** Spot's supervision task raises during an unattended run
- **THEN** the cycle escalates, the entity is preserved and shut down, and a caretaker notice is sent

#### Scenario: Operator-present boot unaffected
- **WHEN** Spot's supervision task exits during an operator-present boot
- **THEN** the unattended escalation is not applied and behavior is unchanged
