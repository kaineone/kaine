## ADDED Requirements

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
Chronos SHALL subscribe to a configurable set of streams known to
carry user input (default `audio.in.out`) in addition to
`workspace.broadcast`. The timestamp of the most recent event on any
of these streams SHALL be the basis for
`time_since_last_interaction_s`; if no interaction has occurred since
Chronos started, the reported value SHALL be `inf`.

#### Scenario: No interactions yields infinity
- **WHEN** Chronos has just initialized and no user-input events have
  arrived
- **THEN** the next `chronos.report` has
  `time_since_last_interaction_s == math.inf`

#### Scenario: Interaction resets the clock
- **WHEN** an event arrives on a configured user-input stream
- **THEN** the next `chronos.report`'s
  `time_since_last_interaction_s` is the elapsed seconds since that
  event's timestamp
