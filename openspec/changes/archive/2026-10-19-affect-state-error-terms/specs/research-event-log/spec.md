## ADDED Requirements

### Requirement: The research record of affect state keeps the valence-target terms
The research event observer SHALL copy into every `affect.state` record the valence-target terms the affect module publishes (`vision_error_fast`, `vision_error_slow`, `vision_progress`, `audition_error_fast`, `audition_error_slow`, `audition_progress`, `signed_progress`, `learning_progress`, `wellness`, `wellness_fast`, `wellness_slow`, `wellness_change`, `pleasantness`, `valence_target`), null values included. The post-run log range check SHALL declare their bounds: error means non-negative; `learning_progress`, `wellness`, `wellness_fast` and `wellness_slow` in [0, 1]; the progress terms, `wellness_change`, `pleasantness` and `valence_target` in [-1, 1].

#### Scenario: A periodic affect state record keeps the terms
- **WHEN** the observer builds a record from a periodic `affect.state` event published by the affect module
- **THEN** every payload key, the valence-target terms included, is in the record with the payload's value
