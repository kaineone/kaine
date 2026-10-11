## ADDED Requirements

### Requirement: Sleep's affective reset starts affect afresh
`affective_reset()` SHALL also clear the per-source learning-progress error means, the perceptual alert-rate averages, the intent rate and its counter, and any perceived speaker emotion, so that affect after sleep is computed from what happens after sleep. It SHALL keep Soma's last wellness reading and the interaction history.

#### Scenario: Valence does not rebound from pre-sleep progress
- **WHEN** perceptual errors have fallen steadily for two minutes, `affective_reset()` is awaited, and Thymos then updates for 30 s of entity time with no perceptual reports
- **THEN** valence stays within 0.1 of its baseline

### Requirement: A malformed peer event does not stop the peer consumer
When handling one event from a peer stream raises an exception, Thymos SHALL log it and continue with the next event.

#### Scenario: A bad event is skipped
- **WHEN** a peer event whose handling raises is followed by a valid perceptual report
- **THEN** the valid report is handled
