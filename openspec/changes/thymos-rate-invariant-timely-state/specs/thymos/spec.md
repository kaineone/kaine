## ADDED Requirements

### Requirement: Appraisal nudges are per unit time
Thymos SHALL scale each broadcast's appraisal nudges to valence and arousal by the subjective time since its previous update divided by `appraisal_reference_interval_s` (default 0.3 seconds), capped at 4, so that the nudge per second does not depend on the broadcast rate.

#### Scenario: The broadcast rate does not change the arousal gained per second
- **WHEN** the same novel coalition is broadcast for ten seconds at 3.3 broadcasts per second and, separately, at 10 broadcasts per second, with relaxation held off
- **THEN** arousal rises by the same amount in both runs, within one nudge

### Requirement: Thymos publishes its state on a timer
Thymos SHALL update its state and publish `thymos.state` every `publish_interval_s` of subjective time whether or not a workspace broadcast arrives.

#### Scenario: State without broadcasts
- **WHEN** Thymos runs for three publish intervals with no workspace broadcast
- **THEN** it publishes at least two `thymos.state` events
