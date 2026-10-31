## ADDED Requirements

### Requirement: Novelty after the entity's own stimulus act is its own response
When stimulus control is enabled, boredom relief by alert excess or learning progress arriving within `Delta_resp` after a realized stimulus act of the entity SHALL be credited `own`, and a boredom crossing that ends in that window SHALL count as ended by the entity's own response. Outside such a window the credit rule SHALL be unchanged.

#### Scenario: A skip brings a scene cut
- **WHEN** the entity's `next` act is realized and the resulting alerts relieve boredom within `Delta_resp`
- **THEN** that relief is credited `own`

#### Scenario: Stimulus control off
- **WHEN** stimulus control is disabled
- **THEN** relief by alert excess is credited as the current rule credits it
