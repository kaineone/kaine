## ADDED Requirements

### Requirement: The research record of affect state keeps the windowed progress terms
The research event observer SHALL copy `vision_learning_progress`, `audition_learning_progress` and `signed_learning_progress` into every `affect.state` record, null values included, and the post-run log range check SHALL declare them in [-1, 1].

#### Scenario: A periodic affect state record keeps the terms
- **WHEN** the observer builds a record from an `affect.state` event that carries the windowed progress terms
- **THEN** the record has each of them with the payload's value

### Requirement: The run manifest marks the learning-progress estimator
The run manifest SHALL carry `learning_progress_scheme`, 2 for runs whose `affect.state` field `learning_progress` is the windowed estimator. A manifest without the field marks scheme 1, the fast and slow time-decayed means.

#### Scenario: A new run's manifest
- **WHEN** a run context is minted and its manifest written
- **THEN** the manifest has `learning_progress_scheme` equal to 2
