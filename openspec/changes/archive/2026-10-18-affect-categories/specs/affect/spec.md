## ADDED Requirements

### Requirement: Disgust follows the Table 3 appraisal profile
`classify()` SHALL return `disgust` when intrinsic pleasantness is at or below -0.5, novelty is above 0.3 and the absolute goal score is below 0.3, whatever the norm compatibility score, provided the near-neutral, surprise, fear and anger rules did not match first. Novelty stands for Table 3's familiarity check: KAINE's single novelty check covers suddenness, familiarity and predictability, so low familiarity maps to high novelty. Norm compatibility SHALL stay unavailable: the module SHALL keep its numeric value at 0.0 and publish `norm_compatibility_available: false`.

#### Scenario: The Table 3 profile with no norm signal yields disgust
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.7, goal score 0.0, coping 0.0, norm 0.0 and `coping_available` false
- **THEN** the returned emotion is `disgust`

#### Scenario: A norm violation alone does not yield disgust
- **WHEN** `classify()` gets novelty 0.0, pleasantness -0.7 and norm -0.6, with every other score 0.0
- **THEN** the returned emotion is not `disgust`

#### Scenario: Relevant content does not yield disgust
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.7 and goal score 0.5, with coping 0.0
- **THEN** the returned emotion is not `disgust`

#### Scenario: Fear keeps precedence when coping is low
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.6, goal score 0.2 and coping -0.5 with coping available
- **THEN** the returned emotion is `fear`

## MODIFIED Requirements

### Requirement: affect.emotion event discloses unavailable appraisal dimensions

The `affect.emotion` event payload SHALL carry `"norm_compatibility_available": false` while KAINE holds no standards to check content against. The models reviewed take standards as authored input, so the norm check stays undefined until an operator writes a list. No categorical rule SHALL require a norm score.

#### Scenario: norm_compatibility not wired

- **WHEN** a `affect.emotion` event is published
- **AND** no standards list exists
- **THEN** the payload carries `"norm_compatibility_available": false`
- **AND** downstream consumers MUST NOT interpret the numeric norm value as a real measurement
