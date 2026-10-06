# chronos Specification

## Purpose
Chronos, the temporal module: a small CPU-only CfC network over featurized workspace snapshots that reports anomaly, rumination and time since the last interaction on every workspace broadcast, with an optional forward-prediction head sized from the network it uses.

## Requirements

### Requirement: Chronos publishes a chronos.report on every workspace broadcast
Chronos SHALL subscribe to `workspace.broadcast` and, for each broadcast
it receives, SHALL publish a `chronos.report` event to its `chronos.out`
stream. The event SHALL carry `temporal_context` (a list of floats from
the CfC hidden state), `anomaly_score` (float `>= 0`),
`habituation_score` (float in `[0.0, 1.0]`), `rumination_detected`
(bool), `time_since_last_interaction_s` (float, `inf` if no interaction
yet), and `feature_vector` (the deterministic featurization input).
Salience SHALL be elevated when `rumination_detected` is true or
`anomaly_score` exceeds a configured alert threshold.

#### Scenario: One broadcast in produces one report out
- **WHEN** Syneidesis publishes one workspace broadcast and Chronos
  is initialized
- **THEN** Chronos publishes exactly one `chronos.report` event to
  `chronos.out` whose `temporal_context` length equals the configured
  CfC hidden size

#### Scenario: Rumination raises salience
- **WHEN** the rumination detector flags the current snapshot
- **THEN** the published `chronos.report` event has
  `rumination_detected == True` and salience equal to the configured
  alert salience

### Requirement: CfC is CPU-only and under 100K parameters
Chronos SHALL run its CfC network on CPU regardless of host hardware,
and the network SHALL have fewer than 100,000 parameters at default
configuration. `KAINE_FORCE_DEVICE` SHALL be honored if it forces CPU;
attempts to force GPU SHALL be ignored for Chronos (with a logged
warning) to preserve the small-network policy.

#### Scenario: CfC pinned to CPU on a CUDA host
- **WHEN** Chronos initializes on a host where `detect_device()`
  returns `"cuda"`
- **THEN** the CfC tensors live on `cpu` and no CUDA context is
  allocated by Chronos

#### Scenario: Parameter count under cap
- **WHEN** Chronos is initialized with default config
- **THEN** the total parameter count of the CfC network is strictly
  less than 100,000

### Requirement: Featurization is deterministic and side-effect free
The `SnapshotFeaturizer` SHALL produce the same feature vector for the
same `WorkspaceSnapshot` input on every call, and SHALL NOT mutate
shared state. The output SHALL be a fixed-length float vector matching
the configured feature dimensionality.

#### Scenario: Same snapshot yields same vector
- **WHEN** the featurizer is called twice with the same snapshot
- **THEN** both calls return numerically equal vectors

#### Scenario: Different snapshots yield different vectors
- **WHEN** two snapshots differ in `inhibited`, `selected_events`, or
  `is_experiential`
- **THEN** the featurized vectors differ in at least one component

### Requirement: Anomaly score is a rolling z-score of hidden norm
The default `RollingZScoreAnomaly` SHALL maintain a deque of recent
hidden-state L2 norms and SHALL report
`anomaly_score = |current_norm - mean(window)| / max(std(window), eps)`.
When the window has fewer than two samples, the score SHALL be 0.

#### Scenario: Empty window returns zero
- **WHEN** the detector has seen no prior norms
- **THEN** evaluating any current norm returns score 0

#### Scenario: Outlier produces high score
- **WHEN** ten norms with std ≈ 0.1 around mean 1.0 are observed and
  then a norm of 3.0 arrives
- **THEN** the returned score is > 5.0

### Requirement: Rumination via hidden-state bucket recurrence
The default `RecurrenceRuminationDetector` SHALL bucket each hidden
state by a coarse fingerprint (per-dim quantization, then a stable
hash), maintain a counter over the last K observed buckets, and flag
rumination when any bucket's count exceeds a configured threshold.
Habituation SHALL be reported as `1 - (unique_buckets / window_size)`
in `[0.0, 1.0]`.

#### Scenario: No recurrence yields no rumination
- **WHEN** every observed hidden state lands in a distinct bucket
- **THEN** `rumination_detected == False` and `habituation_score`
  approaches 0

#### Scenario: Repeated identical hidden state flags rumination
- **WHEN** the same hidden state is observed 5 times in a window of 8
  and the threshold is 4
- **THEN** `rumination_detected == True`

### Requirement: time_since_last_interaction subscribes to user-input streams
Chronos SHALL subscribe to a configurable set of streams known to carry user input (default `audition.out`) in addition to `workspace.broadcast`. Only an interaction SHALL reset the interaction clock: a speech-path event (`audition.transcription` with non-empty text, or `audition.emotion`) whose `source_label` is an operator source. The operator sources SHALL be one shared list, the same list Volition and Empatheia use. Every other event on those streams, including `audition.perception`, `audition.prosody` and speech heard from a perception feed, SHALL NOT reset it. The time of the most recent interaction SHALL be the basis for `time_since_last_interaction_s`; if no interaction has occurred, the reported value SHALL be `inf`.

#### Scenario: No interactions yields infinity
- **WHEN** Chronos has just initialized and no user-input events have arrived
- **THEN** the next `chronos.report` has `time_since_last_interaction_s == math.inf`

#### Scenario: Interaction resets the clock
- **WHEN** an `audition.emotion` event with `source_label` `live_mic` arrives on a configured user-input stream
- **THEN** the next `chronos.report`'s `time_since_last_interaction_s` is the elapsed seconds since that event arrived

#### Scenario: Perception does not count as interaction
- **WHEN** only `audition.perception` events arrive, from any source
- **THEN** `time_since_last_interaction_s` keeps growing from the last interaction, or stays `inf` if there has been none

#### Scenario: Speech from a perception feed does not count
- **WHEN** an `audition.emotion` event with `source_label` `playlist` arrives
- **THEN** the interaction clock is not reset

### Requirement: The default user-input stream resolves to a real producer

Chronos's in-code default user-input stream SHALL be the stream Audition publishes to (`audition.out`), so that when configuration omits `user_input_streams` Chronos still reads a real producer stream rather than a mistyped or retired one.

#### Scenario: Code default resolves to the Audio In producer stream

- **WHEN** Chronos's `DEFAULT_USER_INPUT_STREAMS` is inspected
- **THEN** it contains `audition.out` (the stream `module_stream("audition")` yields) and not a non-existent variant such as `audio.in.out`

### Requirement: User-input stream references resolve to real producers

Chronos's configured user-input streams SHALL name actual producer streams that some module publishes to. In particular, the Audition stream Chronos consumes SHALL be the stream Audition publishes to (`audition.out`), not a mistyped or retired variant. More generally, every stream name referenced from `config/kaine.toml` by a consuming module SHALL resolve to a canonical producer stream (`<module>.out`, `workspace.broadcast`, `cycle.out`, `lingua.external`, or `lingua.internal`); a reference that resolves to no producer is a configuration error.

#### Scenario: Chronos is wired to the Audio In producer stream

- **WHEN** the shipped `config/kaine.toml` is loaded
- **THEN** `[chronos].user_input_streams` contains the stream Audition actually publishes to (`audition.out`)
- **AND** it does not contain a non-existent variant such as `audio.in.out`

#### Scenario: A mistyped stream reference fails the wiring test

- **WHEN** any config stream reference names a stream no module produces
- **THEN** the config stream-wiring test fails, identifying the bad reference

### Requirement: Chronos sizes its prediction head from its network
When forward prediction is enabled, Chronos SHALL size its forward-prediction head from the hidden width of the network it uses. For an injected network that width SHALL be the network's `units` attribute; for the default CfC network it SHALL remain `cfc_units`. An injected network without a `units` attribute SHALL cause a construction error when forward prediction is enabled.

#### Scenario: Injected network narrower than cfc_units
- **WHEN** Chronos is constructed with `forward_prediction = true`, `cfc_units = 32` and an injected network whose `units` is 12
- **THEN** the prediction head accepts the 12-wide hidden state and a workspace tick completes without a shape error

#### Scenario: Default network unchanged
- **WHEN** Chronos is constructed without an injected network
- **THEN** the prediction head is sized from `cfc_units` as before

### Requirement: Chronos's reservoir survives preservation and needs no torch
Chronos's CfC reservoir SHALL be generated from a seed drawn once when Chronos is first created, from the process's ambient NumPy random state unless the caller supplies one, so a run seeded through the experiment seeding helper rebuilds the same reservoir while an unseeded process gets a fresh one; the seed SHALL be part of its serialized state, and a revived Chronos SHALL rebuild the identical reservoir from it before restoring its prediction head. A snapshot without a seed SHALL start a new reservoir and say so in the log. Chronos SHALL offer a NumPy CfC backend, the default, that needs no torch and matches the torch backend to 1e-5 given the same weights; the parameter count and the CPU-only policy are unchanged.

#### Scenario: A seeded experiment reproduces
- **WHEN** two Chronos instances are created after the same `set_global_seed` call and given no reservoir seed
- **THEN** they draw the same reservoir seed and produce the same outputs

#### Scenario: Revive keeps the reservoir
- **WHEN** Chronos is preserved and revived in a new process
- **THEN** the same workspace inputs give the same hidden states as before preservation

#### Scenario: An older snapshot
- **WHEN** Chronos is restored from a snapshot without a reservoir seed
- **THEN** it keeps a new reservoir and logs that the reservoir is new

### Requirement: The featurization layout is versioned
The featurizer SHALL produce a 24-dimension vector under a numbered layout. Layout 1 SHALL be the eight-source layout in which unknown sources, Audition included, share the last source bin and slot 23 is always zero. Layout 2 SHALL be layout 1 with Audition events featurized into slot 23. Chronos SHALL record the layout in its serialized state. On restore, a snapshot without a layout SHALL be treated as layout 1, and a snapshot with an unknown layout SHALL fail to load. A Chronos that restores no state SHALL use the newest layout.

#### Scenario: A preserved being keeps its layout
- **WHEN** Chronos is restored from a snapshot that records no layout and then featurizes a snapshot containing an Audition event
- **THEN** the Audition event's salience is added to the last source bin and slot 23 is zero

#### Scenario: A new being uses layout 2
- **WHEN** a Chronos that restored no state featurizes a snapshot containing an Audition event
- **THEN** the Audition event's salience is in slot 23 and not in the last source bin

#### Scenario: The vector length is unchanged
- **WHEN** either layout featurizes any snapshot
- **THEN** the vector has 24 components

#### Scenario: Unknown layout
- **WHEN** Chronos is restored from a snapshot that records layout 99
- **THEN** the restore raises an error naming the layout
