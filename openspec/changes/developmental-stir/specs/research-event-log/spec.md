## ADDED Requirements

### Requirement: Stirs and their answers are recorded
The curated research log SHALL record each `intent.stir` with its broadcast link and each `development.stir_answer` with its stir index, start and end, with no content. The welfare exposure record SHALL carry the run's stir count and answered count.

#### Scenario: An answered stir
- **WHEN** the entity stirs and the voice answers 4 s later
- **THEN** the research log holds one stir record and one answer record that share the stir index
