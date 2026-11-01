## ADDED Requirements

### Requirement: A per-viewing perceptual-switching record
With self-switching on, the welfare log SHALL carry one `perceptual_switching` record per viewing, giving switches by target and initiator, refusals by reason, dwell times, the awake share away from the programme, and boredom after the entity's own switches compared with otherwise. It SHALL hold numbers and labels only.

#### Scenario: Refusals are counted
- **WHEN** three of the entity's switch acts are refused for `dwell` in a viewing
- **THEN** the record counts three `dwell` refusals

### Requirement: Each switch's transient and adaptation are measured
For each switch the record SHALL give each processor's raw prediction error before and after, the alerts in the minute after, the adaptation time measured on raw error (a first entry against its own error at departure, a revisit against the target context's pre-departure median), whether the context was new or revisited, and the arousal peak.

#### Scenario: Savings are measurable
- **WHEN** the entity enters the simulated world, leaves, and later returns
- **THEN** the record gives both adaptation times and their ratio

### Requirement: Off equals absent for switching
With `[perceptual_locus].allow_self_switch = false`, the build SHALL construct no switch effector, entity path of the arbiter, stage-M source, credit widening or welfare hold. A seeded entity-free harness with the registry on and switching off SHALL give the digest of the registry-only build.

#### Scenario: Shipped configuration
- **WHEN** switching is off
- **THEN** the harness digest equals the registry-only golden, and no `perceptual_switching` record is written

### Requirement: Switching cannot become a self-reward loop
Within the response window after the entity's own realised switch, only learning progress SHALL count as its own response for boredom, and alert excess inside each processor's adaptation period SHALL be excluded. Before switching is enabled, an offline habituation check on the affect module's trackers SHALL show that the relief a switch buys falls with repetition, and its record SHALL be dated in the shakedown records.

#### Scenario: A burst after a switch
- **WHEN** a switch is followed by alerts during the new context's adaptation period
- **THEN** those alerts do not count as the entity's own response for boredom
