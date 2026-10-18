## ADDED Requirements

### Requirement: The research record of affect state keeps the windowed progress terms
The research event observer SHALL copy `vision_learning_progress`, `audition_learning_progress` and `signed_learning_progress` into every `affect.state` record, null values included, and the post-run log range check SHALL declare them in [-1, 1].

#### Scenario: A periodic affect state record keeps the terms
- **WHEN** the observer builds a record from an `affect.state` event that carries the windowed progress terms
- **THEN** the record has each of them with the payload's value
