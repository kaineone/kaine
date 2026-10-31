## ADDED Requirements

### Requirement: The welfare record gives stimulus-control use per viewing
When stimulus control is enabled, the welfare record SHALL give per viewing the count of stimulus commands by action, the count of refused commands, the share of awake time held by the `entity` pause holder, the time-weighted gain distribution, and the order of programme item identifiers visited, with no sensory content. The run manifest SHALL record whether stimulus control is enabled, its stage and every bound.

#### Scenario: A viewing with skips
- **WHEN** a viewing ends in which the entity issued two `next` commands and one refused `louder`
- **THEN** the welfare record for that viewing gives `next: 2`, one refused command and the item identifiers in the order visited
