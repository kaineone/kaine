# interoception Specification

## Purpose
The interoception module, the interoceptive module: it reads the host substrate's metrics (and the cycle's latency) as the entity's body sense, scores wellness, predicts its own substrate state with a replaceable forward model, and reports on the bus without blocking the event loop.

## Requirements

### Requirement: Interoception publishes interoception reports at a configurable interval
The interoception module SHALL publish a `interoception.report` event to its `interoception.out` stream every
`read_interval_s` seconds (default 1.0) carrying three fields: `metrics`
(a flat dict of measured values), `wellness` (a float in `[0.0, 1.0]`),
and `alerts` (a list of metric keys whose values exceeded their
configured thresholds, possibly empty). The event's salience SHALL be
elevated (default 0.7) when `alerts` is non-empty and SHALL remain low
(default 0.1) when alerts is empty, so the workspace treats anomalies as
salient by default.

#### Scenario: Baseline report published with low salience
- **WHEN** the interoception module reads metrics under threshold and publishes
- **THEN** the published `interoception.report` event has empty `alerts` and
  salience equal to the configured baseline

#### Scenario: Threshold breach raises salience
- **WHEN** metrics include `cpu_percent=95` and the configured CPU
  threshold is 90
- **THEN** the published `interoception.report` event has `alerts` containing
  `"cpu_percent"` and salience equal to the configured alert level

### Requirement: Interoception consumes cycle.out latency events
The interoception module SHALL subscribe to the `cycle.out` stream and maintain a rolling
window of recent `cycle.tick` event `wall_duration_ms` payloads. The
mean of the window SHALL be exposed in subsequent metrics dicts as
`cycle_latency_avg_ms`. The window size SHALL be configurable.

#### Scenario: Latency average updates with new tick events
- **WHEN** the cycle publishes `cycle.tick` events with
  `wall_duration_ms` values 100, 200, and 300 to `cycle.out`
- **THEN** the next `metrics` dict the interoception module reads contains
  `cycle_latency_avg_ms == 200.0`

#### Scenario: Window respects configured size
- **WHEN** the window size is 4 and five `cycle.tick` events with
  `wall_duration_ms` 1, 2, 3, 4, 5 have been published
- **THEN** the metrics dict reports `cycle_latency_avg_ms == 3.5`

### Requirement: Graceful degradation when pynvml is unavailable
The default `SystemMetricsReader` SHALL attempt to initialize NVML once
when the interoception module initializes. If initialization fails for any reason, the interoception module
SHALL log a single warning and continue producing reports without any
`gpu_*` metric keys.

#### Scenario: NVML init failure does not stop Interoception
- **WHEN** `pynvml.nvmlInit()` raises an exception during
  `Interoception.initialize`
- **THEN** `Interoception.initialize` completes successfully and subsequent
  `interoception.report` events contain no `gpu_*` keys but still contain
  `cpu_percent`, `ram_percent`, and other CPU-side metrics

### Requirement: Wellness score is in [0,1] and weighted across present metrics
The interoception module SHALL compute a `wellness` score that:
- equals 1.0 when every present metric is at its healthy value,
- decreases linearly per per-metric normalization curve,
- weighted-averages the per-metric contributions using configured
  weights (default 1.0 each), with the weight basis automatically
  restricted to the metrics actually present in the metrics dict, and
- clamps to the closed interval `[0.0, 1.0]`.

#### Scenario: All metrics at healthy values yields wellness 1.0
- **WHEN** metrics contain only `cpu_percent=0`, `ram_percent=0`
- **THEN** `wellness == 1.0`

#### Scenario: Mid-range CPU produces mid-range wellness
- **WHEN** metrics contain only `cpu_percent=50`
- **THEN** `wellness == 0.5`

#### Scenario: GPU absence does not penalize wellness
- **WHEN** metrics contain `cpu_percent=10` and `ram_percent=20` with
  no `gpu_*` keys
- **THEN** `wellness` is computed only from CPU and RAM contributions
  and equals 0.85

### Requirement: AnomalyDetector strategy is replaceable
The interoception module SHALL accept an `AnomalyDetector` collaborator implementing
`evaluate(metrics) -> AlertResult`. The default
`ThresholdAnomalyDetector` SHALL apply per-metric `>` comparisons
against configured thresholds; missing metrics SHALL NOT trigger an
alert.

#### Scenario: Custom detector replaces the default
- **WHEN** the interoception module is constructed with a custom detector that always
  returns one alert key `"forced"`
- **THEN** every published `interoception.report` event has `alerts == ["forced"]`
  and the elevated alert salience

#### Scenario: Threshold not exceeded yields empty alerts
- **WHEN** `cpu_percent=80` and the configured CPU threshold is 90
- **THEN** the detector returns no alert for cpu_percent

### Requirement: Metrics reading does not block the event loop
The `SystemMetricsReader` SHALL execute its synchronous psutil and
pynvml calls off the asyncio event loop (via `asyncio.to_thread` or
equivalent) so that other modules' coroutines and the cognitive cycle
are not stalled while the interoception module reads metrics.

#### Scenario: Metrics read does not block cycle ticks
- **WHEN** the interoception module's read takes 50 ms wall time
- **THEN** other coroutines scheduled during that window still receive
  CPU time and the cycle's tick latency is not inflated by 50 ms

### Requirement: Default interoception config and disabled-by-default
The repository SHALL ship a `[interoception]` section in `config/kaine.toml`
with default values for `read_interval_s`, per-metric thresholds, and
per-metric weights, and SHALL keep `[modules].interoception = false` so first
boot does not auto-register the interoception module without an operator opt-in.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator reads `config/kaine.toml`
- **THEN** they find a `[interoception]` section with `read_interval_s`,
  thresholds, and weights, and `[modules].interoception == false`

### Requirement: Interoception accepts an injected forward model
The interoception module's constructor SHALL accept an optional `forward_model` object. When it is `None`, the interoception module SHALL build its default `SubstrateForwardModel` with the configured `forward_model_units`, as before. When it is provided, the interoception module SHALL use it in place of the default and SHALL call only the interface the interoception module already uses on its forward model (`step`, `prediction_error_to_salience`, `suspended`, `adaptation_steps`, `state_dict`, `load_state_dict`).

#### Scenario: Default unchanged
- **WHEN** the interoception module is constructed without `forward_model`
- **THEN** it builds a `SubstrateForwardModel` exactly as it does today

#### Scenario: Injected model used
- **WHEN** the interoception module is constructed with `forward_model=model`
- **THEN** each interoceptive tick calls `model.step` and no `SubstrateForwardModel` is built

### Requirement: Interoception's reservoir survives preservation and needs no torch
The interoception module's CfC reservoir SHALL be generated from a seed drawn once when the interoception module is first created, from the process's ambient NumPy random state unless the caller supplies one, so a run seeded through the experiment seeding helper rebuilds the same reservoir while an unseeded process gets a fresh one; the seed SHALL be part of its serialized state, and a revived interoception module SHALL rebuild the identical reservoir from it before restoring its readout. A snapshot without a seed SHALL start a new reservoir and say so in the log. The interoception module SHALL offer a NumPy CfC backend, the default, that needs no torch and matches the torch backend to 1e-5 given the same weights.

#### Scenario: A seeded experiment reproduces
- **WHEN** two interoception module instances are created after the same `set_global_seed` call and given no reservoir seed
- **THEN** they draw the same reservoir seed and produce the same outputs

#### Scenario: Revive keeps the reservoir
- **WHEN** the interoception module is preserved and revived in a new process
- **THEN** its reservoir weights are identical to the preserved ones, and the same inputs give the same hidden states and predictions

#### Scenario: A host without torch
- **WHEN** the interoception module runs on the NumPy backend where torch cannot be imported
- **THEN** it starts and runs, and the extras check does not require the `core` extra for it

### Requirement: A module's live consumer starts at the stream tail
A module's live consumer of another module's stream SHALL start reading at the stream's tail at start, through one shared helper, so past events are not replayed as new. In particular the interoception module SHALL NOT reset fatigue or regulation for a `sleep.sleep.completed` published before it started, and SHALL NOT enter the asleep state for a `sleep.sleep.started` published before it started.

#### Scenario: A module's live consumer starts at the stream tail
- **WHEN** sleep.out holds earlier started and completed events and the interoception module restores fatigue 40 and starts
- **THEN** fatigue stays 40 and the module is awake

### Requirement: Awake fatigue builds with the housekeeping pressure
While awake, the fatigue accumulator SHALL build at `e (1 + P^hk)`, where `e` is its existing input and `P^hk` the housekeeping pressure (paper A.5); the pressure SHALL have no ceiling. Asleep, or when the pressure is 0, unreadable or not a finite number at least 0, the accumulator SHALL behave exactly as before.

#### Scenario: A resource at twice its budget
- **WHEN** the pressure is 1.0 and the entity is awake
- **THEN** fatigue builds twice as fast as with no pressure

#### Scenario: Asleep
- **WHEN** the pressure is 1.0 and the entity sleeps
- **THEN** fatigue changes exactly as it would with no pressure
