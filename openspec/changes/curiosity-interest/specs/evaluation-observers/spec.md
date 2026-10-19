## ADDED Requirements

### Requirement: Curiosity's welfare readout is an interest share
The `affect_welfare` record SHALL give `curiosity_interest_share`, the share of awake time with curiosity at or above its threshold, and SHALL NOT give `curiosity_uncontrolled_share`, `curiosity_uncontrolled_per_awake_hour` or `curiosity_deprivation_share`. Boredom, the social drive and restlessness SHALL keep their uncontrolled and deprivation keys.

#### Scenario: The frozen control ranks worst through boredom
- **WHEN** a never-relieved boredom history and an intermittently relieved one are each observed with and without sleeps every 25 min
- **THEN** the never-relieved history has the larger `boredom_deprivation_share` at both cadences, and no record key for curiosity names a cost
