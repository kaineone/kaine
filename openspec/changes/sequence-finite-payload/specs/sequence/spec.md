## MODIFIED Requirements

### Requirement: Sequence publishes a sequence.report on every workspace broadcast
The sequence module SHALL subscribe to `workspace.broadcast` and, for each broadcast
it receives, SHALL publish a `sequence.report` event to its `sequence.out`
stream. The event SHALL carry `temporal_context` (a list of floats from
the CfC hidden state), `anomaly_score` (float `>= 0`),
`habituation_score` (float in `[0.0, 1.0]`), `rumination_detected`
(bool), `time_since_last_interaction_s` (a finite float, or `null` if no
interaction yet), and `feature_vector` (the deterministic featurization input).
Salience SHALL be elevated when `rumination_detected` is true or
`anomaly_score` exceeds a configured alert threshold.

#### Scenario: One broadcast in produces one report out
- **WHEN** the workspace publishes one workspace broadcast and the sequence module
  is initialized
- **THEN** the sequence module publishes exactly one `sequence.report` event to
  `sequence.out` whose `temporal_context` length equals the configured
  CfC hidden size

#### Scenario: Rumination raises salience
- **WHEN** the rumination detector flags the current snapshot
- **THEN** the published `sequence.report` event has
  `rumination_detected == True` and salience equal to the configured
  alert salience

### Requirement: time_since_last_interaction subscribes to user-input streams
The sequence module SHALL subscribe to a configurable set of streams known to carry user input (default `audition.out`) in addition to `workspace.broadcast`. Only an interaction SHALL reset the interaction clock: a speech-path event (`audition.transcription` with non-empty text, or `audition.emotion`) whose `source_label` is an operator source. The operator sources SHALL be one shared list, the same list the action selection module and the social cognition module use. Every other event on those streams, including `audition.perception`, `audition.prosody` and speech heard from a perception feed, SHALL NOT reset it. The time of the most recent interaction SHALL be the basis for `time_since_last_interaction_s`; if no interaction has occurred, the reported value SHALL be `null` (Python `None`), never a non-finite float.

#### Scenario: No interactions yields null
- **WHEN** the sequence module has just initialized and no user-input events have arrived
- **THEN** the next `sequence.report` has `time_since_last_interaction_s` equal to `None`, and the payload serializes with `json.dumps(..., allow_nan=False)`

#### Scenario: Interaction resets the clock
- **WHEN** an `audition.emotion` event with `source_label` `live_mic` arrives on a configured user-input stream
- **THEN** the next `sequence.report`'s `time_since_last_interaction_s` is the elapsed seconds since that event arrived

#### Scenario: Perception does not count as interaction
- **WHEN** only `audition.perception` events arrive, from any source
- **THEN** `time_since_last_interaction_s` keeps growing from the last interaction, or stays `null` if there has been none

#### Scenario: Speech from a perception feed does not count
- **WHEN** an `audition.emotion` event with `source_label` `playlist` arrives
- **THEN** the interaction clock is not reset
