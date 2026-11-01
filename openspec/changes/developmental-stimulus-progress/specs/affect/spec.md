## ADDED Requirements

### Requirement: The hearing-stage reading waits for a full window
`Affect.audition_learning_progress(stage)`, the reading the hearing-stage owner uses, SHALL be None until its audition bins hold `learning_progress_span_s / learning_progress_bin_s` completed bins since the last restart, and their value after that. The learning progress that drives curiosity, boredom and interest, and the `audition_learning_progress` field of `affect.state`, SHALL be computed as before.

#### Scenario: Less than a full window after a step
- **WHEN** audition's estimator restarted at a band step 3000 s of awake time ago
- **THEN** the hearing-stage reading is None, while the drives' learning progress and the state event's field carry the estimator's value

#### Scenario: A full window
- **WHEN** 90 bins of 60 s have completed since the restart
- **THEN** the hearing-stage reading equals the estimator's value

### Requirement: The hearing-stage reading bins awake reports only
The hearing-stage reading SHALL have audition bins of its own on audition's awake time. A report whose payload has `awake` false, made during a rest while the forward model is suspended, SHALL be left out, and a rest SHALL add no time to those bins. The bins SHALL persist with the module's state.

#### Scenario: A rest inside the span
- **WHEN** a 1410 s rest, whose audition reports carry `awake` false, begins 2000 s after a band step
- **THEN** the hearing-stage reading stays None until 5400 s of awake reports have been binned, while the drives' learning progress bins the rest on the entity clock

#### Scenario: A restart keeps the bins
- **WHEN** the module's state is saved with a full hearing-stage window and restored
- **THEN** the hearing-stage reading after the restore equals the one before
