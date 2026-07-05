# soma Specification

## Purpose
TBD - created by archiving change soma. Update Purpose after archive.
## Requirements
### Requirement: Soma publishes interoception reports at a configurable interval
Soma SHALL publish a `soma.report` event to its `soma.out` stream every
`read_interval_s` seconds (default 1.0) carrying three fields: `metrics`
(a flat dict of measured values), `wellness` (a float in `[0.0, 1.0]`),
and `alerts` (a list of metric keys whose values exceeded their
configured thresholds, possibly empty). The event's salience SHALL be
elevated (default 0.7) when `alerts` is non-empty and SHALL remain low
(default 0.1) when alerts is empty, so Syneidesis treats anomalies as
salient by default.

#### Scenario: Baseline report published with low salience
- **WHEN** Soma reads metrics under threshold and publishes
- **THEN** the published `soma.report` event has empty `alerts` and
  salience equal to the configured baseline

#### Scenario: Threshold breach raises salience
- **WHEN** metrics include `cpu_percent=95` and the configured CPU
  threshold is 90
- **THEN** the published `soma.report` event has `alerts` containing
  `"cpu_percent"` and salience equal to the configured alert level

### Requirement: Soma consumes cycle.out latency events
Soma SHALL subscribe to the `cycle.out` stream and maintain a rolling
window of recent `cycle.tick` event `wall_duration_ms` payloads. The
mean of the window SHALL be exposed in subsequent metrics dicts as
`cycle_latency_avg_ms`. The window size SHALL be configurable.

#### Scenario: Latency average updates with new tick events
- **WHEN** the cycle publishes `cycle.tick` events with
  `wall_duration_ms` values 100, 200, and 300 to `cycle.out`
- **THEN** the next `metrics` dict Soma reads contains
  `cycle_latency_avg_ms == 200.0`

#### Scenario: Window respects configured size
- **WHEN** the window size is 4 and five `cycle.tick` events with
  `wall_duration_ms` 1, 2, 3, 4, 5 have been published
- **THEN** the metrics dict reports `cycle_latency_avg_ms == 3.5`

### Requirement: Graceful degradation when pynvml is unavailable
The default `SystemMetricsReader` SHALL attempt to initialize NVML once
when Soma initializes. If initialization fails for any reason, Soma
SHALL log a single warning and continue producing reports without any
`gpu_*` metric keys.

#### Scenario: NVML init failure does not stop Soma
- **WHEN** `pynvml.nvmlInit()` raises an exception during
  `Soma.initialize`
- **THEN** `Soma.initialize` completes successfully and subsequent
  `soma.report` events contain no `gpu_*` keys but still contain
  `cpu_percent`, `ram_percent`, and other CPU-side metrics

### Requirement: Wellness score is in [0,1] and weighted across present metrics
Soma SHALL compute a `wellness` score that:
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
Soma SHALL accept an `AnomalyDetector` collaborator implementing
`evaluate(metrics) -> AlertResult`. The default
`ThresholdAnomalyDetector` SHALL apply per-metric `>` comparisons
against configured thresholds; missing metrics SHALL NOT trigger an
alert.

#### Scenario: Custom detector replaces the default
- **WHEN** Soma is constructed with a custom detector that always
  returns one alert key `"forced"`
- **THEN** every published `soma.report` event has `alerts == ["forced"]`
  and the elevated alert salience

#### Scenario: Threshold not exceeded yields empty alerts
- **WHEN** `cpu_percent=80` and the configured CPU threshold is 90
- **THEN** the detector returns no alert for cpu_percent

### Requirement: Metrics reading does not block the event loop
The `SystemMetricsReader` SHALL execute its synchronous psutil and
pynvml calls off the asyncio event loop (via `asyncio.to_thread` or
equivalent) so that other modules' coroutines and the cognitive cycle
are not stalled while Soma reads metrics.

#### Scenario: Metrics read does not block cycle ticks
- **WHEN** Soma's read takes 50 ms wall time
- **THEN** other coroutines scheduled during that window still receive
  CPU time and the cycle's tick latency is not inflated by 50 ms

### Requirement: Default soma config and disabled-by-default
The repository SHALL ship a `[soma]` section in `config/kaine.toml`
with default values for `read_interval_s`, per-metric thresholds, and
per-metric weights, and SHALL keep `[modules].soma = false` so first
boot does not auto-register Soma without an operator opt-in.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator reads `config/kaine.toml`
- **THEN** they find a `[soma]` section with `read_interval_s`,
  thresholds, and weights, and `[modules].soma == false`

