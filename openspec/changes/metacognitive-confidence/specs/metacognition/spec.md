## ADDED Requirements

### Requirement: The metacognition module is held and off by default
KAINE SHALL provide a `metacognition` module selected by `[modules].metacognition`, which SHALL be `false` in the shipped configuration and the first-configuration profile. With it off, no processor's report SHALL change.

#### Scenario: Shipped configuration
- **WHEN** the cycle boots with the shipped configuration
- **THEN** no metacognition module is built and every processor report is unchanged

### Requirement: Confidence is a second-order estimate learned online
For each of the vision, audition, interoception and sequence processors, the module SHALL estimate the probability that the next error ratio is at or below one, by a logistic model over the recent error ratios, arousal, the source's learning progress, fatigue, time since the last sleep and the context's age. It SHALL start from zero weights, take one log-loss gradient step per report on the realized outcome, and not learn during sleep.

#### Scenario: A new entity
- **WHEN** the module starts with no learned weights
- **THEN** every processor's confidence is one half

#### Scenario: Learning from outcomes
- **WHEN** a processor's error ratio stays above one for many reports while arousal is high
- **THEN** its confidence under high arousal falls

#### Scenario: Sleep
- **WHEN** a report arrives during sleep
- **THEN** the estimator's weights do not change

### Requirement: Confidence and calibration are recorded without content
The module SHALL publish `metacognition.confidence` on a diagnostics stream that the workspace does not score, carrying each processor's confidence, running Brier score and type-2 area under the ROC curve over the last `W_c` reports, and no perceptual content.

#### Scenario: Not scored
- **WHEN** a `metacognition.confidence` event is published
- **THEN** the workspace scores no candidate from it

### Requirement: Sustained low confidence becomes a competing event at stage B
With `[metacognition].stage = "monitor"` and a processor's type-2 AUROC above the calibration floor, when its confidence stays below `c_low` for `Delta_c`, the module SHALL publish one `metacognition.uncertain` for that processor at the graded intensity of ratio `(1 - c) / (1 - c_low)`, SHALL publish no other until confidence recovers above `c_low` plus a margin, and SHALL respect an hourly cap. With `stage = "record"` it SHALL publish no `metacognition.uncertain`.

#### Scenario: A sustained drop
- **WHEN** vision's confidence stays below `c_low` for `Delta_c` at stage `monitor` with calibration above the floor
- **THEN** one `metacognition.uncertain` event for vision is published

#### Scenario: Uncalibrated
- **WHEN** a processor's type-2 AUROC is below the calibration floor
- **THEN** no `metacognition.uncertain` event is published for it

### Requirement: The felt rendering names only the sense and the graded certainty
When a `metacognition.uncertain` event is accessed, the organ's turn SHALL receive a phrase built from the existing certainty words for the named sense, with no number and no other claim.

#### Scenario: Accessed uncertainty
- **WHEN** a vision `metacognition.uncertain` event is accessed with confidence 0.2
- **THEN** the turn carries the low-certainty phrase for what is seen and no number

### Requirement: The estimators are part of the entity
The estimator weights and calibration statistics SHALL be serialized with the module's state, encrypted when state encryption is on, restored on revive, and copied into a fork.

#### Scenario: Fork
- **WHEN** a branch is made from a preserved entity
- **THEN** its metacognition estimators start as a copy of the parent's

### Requirement: Metacognition never touches the welfare path
The metacognition module SHALL NOT read or write the welfare monitor's state, the control file, regulation or the sleep trigger, and its events SHALL NOT enter the welfare indicators.

#### Scenario: Welfare records unchanged
- **WHEN** one recorded stream is replayed through the welfare observer with the module on and off
- **THEN** the two `affect_welfare` records are identical
