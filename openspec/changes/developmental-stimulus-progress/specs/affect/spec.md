## ADDED Requirements

### Requirement: The hearing-stage reading waits for a full window
`Affect.audition_learning_progress(stage)`, the reading the hearing-stage owner uses, SHALL return None until audition's estimator holds `learning_progress_span_s / learning_progress_bin_s` completed bins since its last restart, and the estimator's value after that. The learning progress that drives curiosity, boredom and interest, and the `audition_learning_progress` field of `affect.state`, SHALL be computed as before.

#### Scenario: Less than a full window after a step
- **WHEN** audition's estimator restarted at a band step 3000 s of awake time ago
- **THEN** the hearing-stage reading is None, while the drives' learning progress and the state event's field carry the estimator's value

#### Scenario: A full window
- **WHEN** 90 bins of 60 s have completed since the restart
- **THEN** the hearing-stage reading equals the estimator's value
