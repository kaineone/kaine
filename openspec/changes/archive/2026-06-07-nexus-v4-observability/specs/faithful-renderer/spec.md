## ADDED Requirements

### Requirement: Templates for remaining v4 event types
The FaithfulRenderer SHALL provide named, human-readable templates for the v4
event types that currently fall back to raw-dict rendering: `nous.timeout`,
`audition.prosody`, `vox.synthesized`, `mnemos.replay`, `hypnos.sleep.started`,
`hypnos.sleep.completed`, `hypnos.association`, and `eidolon.self_model`. Each
SHALL render readable text, never a raw dict.

#### Scenario: New event types render via named templates
- **WHEN** any of the listed v4 event types is passed to the renderer
- **THEN** the output is produced by that event's named template, not the fallback

#### Scenario: Replay and self-model render no raw content
- **WHEN** a `mnemos.replay` or `eidolon.self_model` event is rendered
- **THEN** the output contains memory IDs / trait labels and numeric attributes
  only, and no raw transcript or sense-data text

### Requirement: Report templates include v4 predictive fields
The `soma.report` template SHALL render `prediction_error` and `fatigue_value`,
and the `chronos.report` template SHALL render `temporal_prediction_error`, so the
forward-model signals are visible in the conscious-coalition view rather than
silently dropped.

#### Scenario: Soma report shows predictive fields
- **WHEN** a `soma.report` carrying `prediction_error` and `fatigue_value` is rendered
- **THEN** the rendered line includes both values

#### Scenario: Chronos report shows temporal prediction error
- **WHEN** a `chronos.report` carrying `temporal_prediction_error` is rendered
- **THEN** the rendered line includes that value
