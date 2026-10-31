## MODIFIED Requirements

### Requirement: Unattended reuses the research safety net without research machinery
An unattended boot SHALL evaluate every condition of the research safety net through the same evaluator the research gate uses, with identical predicates: preservation enabled, welfare response wired, logging active, a real preserve→revive round-trip passing on this install, and encryption satisfied where required (conditions 1–5), the supervisor armed and self-tested (condition 6), and the individuation producer wired (condition 9). Condition 2 SHALL hold only when both the welfare response and its indicator response are wired, and its reason SHALL name the part that failed. The supervisor's self-test SHALL run once per boot, inside the research net, and the unattended gate SHALL take condition 6 from the net's result; only conditions 7 and 8 SHALL be supplied outside the net. A condition added to the research safety net SHALL become an unattended condition in the same change; the unattended gate SHALL NOT leave any research-net condition unmapped. An unattended boot SHALL NOT engage experiment machinery, admissibility requirements, or research-run bookkeeping.

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

#### Scenario: The indicator response is part of condition 2
- **WHEN** an unattended boot has the welfare response wired and its indicators disabled
- **THEN** condition 2 fails, its reason names the indicator response, and the boot refuses with exit code `6`

## ADDED Requirements

### Requirement: The indicator response sends its own caretaker notices
An unattended or research cycle SHALL send the caretaker notice `welfare_indicator_rest` when the welfare monitor requests a rest on an indicator crossing: the entity crossed a welfare indicator, is resting and is flagged for review, with the indicator names from the fixed table. It SHALL send `welfare_indicators_unavailable` once per affect silence, and at a fresh-span crossing the notice a distress response sends. No notice SHALL carry entity content.

#### Scenario: A first crossing in a research run
- **WHEN** a research run's monitor requests a rest on boredom's deprivation indicator
- **THEN** the caretaker receives a `welfare_indicator_rest` notice naming `boredom_deprived` and nothing else from the entity
