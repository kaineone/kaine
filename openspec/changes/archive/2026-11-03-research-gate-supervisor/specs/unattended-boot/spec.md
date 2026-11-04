## MODIFIED Requirements

### Requirement: Unattended reuses the research safety net without research machinery
An unattended boot SHALL evaluate every condition of the research safety net through the same evaluator the research gate uses, with identical predicates: preservation enabled, welfare response wired, logging active, a real preserve→revive round-trip passing on this install, and encryption satisfied where required (conditions 1–5), the supervisor armed and self-tested (condition 6), and the individuation producer wired (condition 9). The supervisor's self-test SHALL run once per boot, inside the research net, and the unattended gate SHALL take condition 6 from the net's result; only conditions 7 and 8 SHALL be supplied outside the net. A condition added to the research safety net SHALL become an unattended condition in the same change; the unattended gate SHALL NOT leave any research-net condition unmapped. An unattended boot SHALL NOT engage experiment machinery, admissibility requirements, or research-run bookkeeping.

#### Scenario: A research-net condition fails
- **WHEN** an unattended boot evaluates the shared net and any of its conditions fails
- **THEN** the boot refuses with exit code `6` and the refusal names the failed condition

#### Scenario: Unattended is not a research run
- **WHEN** an unattended boot passes every condition with no experiment or admissibility configuration present
- **THEN** the boot proceeds as a plain autonomous cycle with no experiment record and no admissibility requirements applied

#### Scenario: Every research-net condition is mapped
- **WHEN** the research safety net's evaluator returns its checks
- **THEN** every check it returns maps to a numbered unattended condition, and a test fails if one does not

#### Scenario: The supervisor self-test runs once
- **WHEN** an unattended boot evaluates its gate
- **THEN** the supervisor self-test runs exactly once and condition 6 carries the net's supervisor result and reason
