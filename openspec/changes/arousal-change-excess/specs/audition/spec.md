## ADDED Requirements

### Requirement: Acoustic perception reports carry the change ratio
Every `audition.perception` event SHALL carry `normalised_change`, the acoustic change score divided by the running mean of acoustic change scores used by the acoustic change alert, or 0.0 when that mean is 0 (paper A.2).

#### Scenario: An acoustic onset carries a large change ratio
- **WHEN** four steady windows are followed by a very different window
- **THEN** the fifth `audition.perception` carries a `normalised_change` of at least the acoustic change alert factor

#### Scenario: The first report carries zero
- **WHEN** the first window is processed
- **THEN** its `audition.perception` carries `normalised_change` 0.0
