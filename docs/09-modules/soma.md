# Soma

Soma is KAINE's interoceptive module. It watches the host machine's compute health, predicts the next substrate state, and raises fatigue or regulation signals when the entity's body needs care. This page covers what Soma does, how to enable it, its bus events, configuration, internals, tests, and related modules. Operators deciding whether to turn it on and contributors debugging its predictions should read it.

Soma is part of the base-thesis stack; the `thesis_test` profile enables it by default, but the shipped `config/kaine.toml` disables it.

## Status

Implemented. Enabled by default in the `thesis_test` profile (`config/profiles/thesis_test.toml`). In the shipped main configuration it is disabled: `[modules].soma = false` in `config/kaine.toml`.

No optional extras are required for the base module. GPU metrics use `pynvml` on hosts with an NVIDIA GPU and degrade gracefully if it is unavailable. The `SubstrateForwardModel` uses a CfC backend chosen by `cfc_backend` in `[soma]`: `"numpy"` (default; needs no `torch` or `ncps`) or `"torch"` (needs the `core` extra). Forward-model adaptation pauses during Hypnos offline sleep cycles.

## Responsibility

In the PP+GWT framing, Soma is the interoceptive channel. It reports the health of the computational substrate—CPU, RAM, GPU temperature and VRAM, and cognitive-cycle latency—to Syneidesis so bodily state can join other affective and perceptual streams in the global workspace.

Soma adds two predictive-processing jobs:

1. **Predictive interoception** — a CPU-only closed-form continuous-time network (`SubstrateForwardModel`, CfC, backend selected by `cfc_backend`) predicts the next substrate feature vector from the current one and its own recurrent hidden state. Soma learns, per channel, the expected absolute prediction error and its spread as running averages over `expected_error_tau_s` of subjective time. The **unexpected error** is the L2 norm of each channel's error beyond `expected + expected_error_band × spread`. The raw `prediction_error` still drives salience and is reported unchanged on `soma.report`; the unexpected error feeds the fatigue accumulator and regulation detector. A steady, predictable substrate stays quiet; genuine surprise still reaches Syneidesis with elevated salience.

2. **Homeostatic regulation** — two coupled subsystems surface maintenance needs:
   - **FatigueAccumulator** integrates the unexpected prediction error over waking time with continuous decay. When it crosses `fatigue_maintenance_threshold`, Soma publishes `soma.fatigue`, the emergent sleep-pressure signal that Hypnos watches.
   - **RegulationDetector** tracks how long the unexpected prediction error stays above `regulation_threshold`. Each completed sustain window emits one escalating `soma.regulation` advisory: `reduce_rate` (severity 1), then `shed_module` (severity 2), then `request_maintenance` (severity 3). Soma never actuates directly; it publishes intents only. The cognitive cycle engine and Hypnos decide what to do.

## Inputs

| Bus stream | Event type consumed | Purpose |
|---|---|---|
| `cycle.out` | `cycle.tick` | Reads `wall_duration_ms` to maintain a rolling cycle-latency average in subjective time |
| `hypnos.out` | `hypnos.sleep.started` | Sets `_in_hypnos = true`; suspends forward-model adaptation; enables faster fatigue decay |
| `hypnos.out` | `hypnos.sleep.completed` | Clears `_in_hypnos`; resets the fatigue accumulator and regulation detector |

Soma also reads host metrics on its own timer via `SystemMetricsReader` (`kaine/modules/soma/reader.py`), using `psutil` and optional `pynvml`, outside the bus.

## Outputs

All events are published to the `soma.out` stream.

| Event type | Payload fields | Salience |
|---|---|---|
| `soma.report` | `metrics`, `wellness`, `alerts`, `prediction_error`, `unexpected_error`, `fatigue_value`, `fatigue_threshold`, `warmup_active` | `baseline_salience` (0.1) when quiet; `alert_salience` (0.7) when alerts fire or prediction error is high |
| `soma.fatigue` | `value`, `threshold`, `crossed: true` | `alert_salience` |
| `soma.regulation` | `action`, `reason`, `severity` | `alert_salience` |
| `soma.warmup.started` | `min_samples`, `min_seconds`, `samples_seen`, `lived_seconds` | `baseline_salience` |
| `soma.warmup.completed` | `samples_seen`, `lived_seconds` | `baseline_salience` |
| `soma.regulation.withheld` | `would_be_action`, `prediction_error`, `sustain_elapsed_s`, `severity`, `reason: "warmup"` | `baseline_salience` |

`soma.report` is the main stream. `soma.fatigue` fires once per threshold crossing and re-arms only when the fatigue value drops below threshold. `soma.regulation` escalates one step per completed sustain window. `soma.warmup.started` and `soma.warmup.completed` mark the developmental warm-up boundary. `soma.regulation.withheld` records a regulation advisory the warm-up gate suppressed; it is not consumed by the cognitive cycle engine, only logged.

## Configuration

Section `[soma]` is in `config/kaine.toml`. See `appendix-a-configuration/modules.md` for the complete `[soma]` reference and `appendix-a-configuration/README.md` for configuration conventions.

| Key | Default | Meaning |
|---|---|---|
| `read_interval_s` | `1.0` | Seconds between metric-read cycles |
| `cycle_latency_target_ms` | `300.0` | Healthy target for the cognitive cycle; deviations above this reduce wellness |
| `cycle_latency_window` | `64` | Rolling window size for cycle-latency samples |
| `baseline_salience` | `0.1` | Salience for routine `soma.report` events |
| `alert_salience` | `0.7` | Salience when threshold alerts, high prediction error, or fatigue fires |
| `cfc_backend` | `"numpy"` | CfC backend for `SubstrateForwardModel`: `"numpy"` needs no `torch`/`ncps`; `"torch"` uses `ncps` and needs the `core` extra |
| `forward_model_units` | `32` | Hidden size of the `SubstrateForwardModel` CfC reservoir |
| `prediction_error_window` | `32` | Rolling window length (ticks) for normalising prediction error into salience |
| `fatigue_decay_per_s` | `0.01` | Per-second decay rate for the fatigue accumulator; tripled during Hypnos sleep |
| `fatigue_maintenance_threshold` | `100.0` | Fatigue value at which `soma.fatigue` fires |
| `regulation_sustain_window_s` | `30.0` | Seconds of sustained high unexpected prediction error before a `soma.regulation` advisory is emitted |
| `regulation_threshold` | `0.5` | Unexpected prediction-error level that begins a regulation episode |
| `expected_error_tau_s` | `600.0` | Time constant, in subjective seconds, for the per-channel running average of absolute prediction error and its spread |
| `expected_error_band` | `2.0` | Spread widths above the expected absolute error that are treated as unsurprising; beyond this band, error contributes to the unexpected-error signal |
| `regulation_warmup_enabled` | `true` | Enables the developmental warm-up gate on the action path while the forward model learns the host's baseline |
| `regulation_warmup_min_samples` | `1000` | Minimum forward-model adaptation samples before warm-up can end |
| `regulation_warmup_min_seconds` | `1200.0` | Minimum subjective seconds since boot before warm-up can end |
| `regulation_warmup_require_error_stabilized` | `false` | Optional guard: also require recent prediction-error variance to fall below `regulation_warmup_stable_variance` before warm-up ends |
| `regulation_warmup_stable_window` | `32` | Rolling window (ticks) used to compute prediction-error variance for the stabilization guard |
| `regulation_warmup_stable_variance` | `0.02` | Variance threshold below which prediction error counts as stabilized |
| `self_rhythm_enabled` | `false` | Enables a self-rhythm oscillator loop; requires the `oscillator` extra |
| `self_rhythm_step_hz` | `20.0` | Frequency of the self-rhythm loop when enabled |

**`[soma.thresholds]`** — per-metric alert thresholds. Defaults: `cpu_percent = 90.0`, `ram_percent = 90.0`, `gpu_*_temp_c = 83.0`, `gpu_*_vram_percent = 92.0`, `cycle_latency_avg_ms = 600.0`. The `gpu_*` globs match all GPUs.

**`[soma.weights]`** — per-metric wellness weights. Defaults: `cpu_percent = 1.0`, `ram_percent = 1.0`, `cycle_latency_avg_ms = 1.0`. Only metrics with defined normalization curves and positive weights contribute to the wellness score.

Enabling `self_rhythm_enabled` requires the `oscillator` extra (`snnTorch`). In `womb` perception-feed mode the oscillator receives its drive from a `MaternalDriveProvider`.

## How it works

```mermaid
graph TD
    SysMetrics["SystemMetricsReader\n(psutil + pynvml)"] -->|read_metrics()| SomaTick["Soma.tick_once()"]
    CycleOut["cycle.out / cycle.tick\n(wall_duration_ms)"] -->|rolling avg| SysMetrics
    HypnosOut["hypnos.out"] -->|sleep.started / completed| SomaTick

    SomaTick --> WellnessCalc["compute_wellness()\nweighted avg of\nnormalised metrics"]
    SomaTick --> AnomalyDet["ThresholdAnomalyDetector\n(per-metric > threshold)"]
    SomaTick --> FwdModel["SubstrateForwardModel\nfeature → CfC reservoir (frozen, seeded) → hidden\nhidden → linear readout (online) → next_vec"]
    FwdModel -->|per-channel error| ExpModel["ExpectedErrorModel\nlearned expected ± band·spread"]
    ExpModel -->|unexpected error| FatigueAcc["FatigueAccumulator\nF += e·dt - decay·dt"]
    ExpModel -->|unexpected error| RegDet["RegulationDetector\nsustained unexpected error > threshold"]
    FatigueAcc -->|threshold crossed| SomaFatigue["soma.fatigue"]
    RegDet -->|window expired| SomaReg["soma.regulation"]
    WellnessCalc --> SomaReport["soma.report\n+ salience"]
    AnomalyDet --> SomaReport
    FwdModel -->|prediction_error| SomaReport
```

### Metric collection

`SystemMetricsReader` calls `psutil.cpu_percent()`, `psutil.virtual_memory()`, disk I/O counters, and, when `pynvml` initializes, per-GPU temperature and VRAM usage. Blocking calls run in a thread via `asyncio.to_thread()` so the event loop is not stalled. Failure of any individual metric omits that key; the wellness formula redistributes weight over the metrics that are present.

The cycle-latency average is kept in subjective time using the injected `EntityClock.scale`.

### Wellness score

`compute_wellness()` normalises each present metric to `[0, 1]` (1 = healthy) using per-key curves, for example `1 - cpu_percent/100`, then takes a weighted average. The result is clamped to `[0, 1]`.

### Predictive interoception

`SubstrateForwardModel` is a closed-form continuous-time network (Hasani et al. 2022) — the same CfC pattern Chronos uses (`kaine/modules/chronos/network.py`). The backend is selected by `[soma].cfc_backend`: `"numpy"` (default, implemented in `kaine/cfc_numpy.py`, needs no `torch` or `ncps`) or `"torch"` (`ncps.torch.CfC`, needs the `core` extra). Both backends compute the same step and match to `1e-5` from the same weights.

Architecture: `feature → CfC reservoir (frozen, seeded, units hidden) → hidden state → Linear(units → feature_dim) readout (online)`, all CPU. The reservoir is frozen and generated in NumPy from a reservoir seed, identically for both backends. Only the linear readout adapts online by SGD, one step per tick.

The feature vector contains `cpu_percent/100`, `ram_percent/100`, `cycle_latency/(2·target)`, and the hottest GPU's `gpu_*_temp_c/100` (0.0 when no GPU telemetry is available). When `self_rhythm_enabled` is true, slots 4–6 carry a rhythm sin/cos/amplitude computed from the self-rhythm oscillator. Remaining unused slots are zero-padded.

A non-finite loss or gradient guard skips weight updates. A non-finite input feature also skips committing that tick into the CfC's recurrent state, so one bad sensor read cannot permanently corrupt the hidden state. Adaptation is suspended while `_in_hypnos` is true. Per-channel expected absolute error and spread are learned only while Soma is awake and are serialized with the module.

A plugin can replace the forward model at the `forward_model` seam in `kaine/boot.py`.

### Self-rhythm

When `self_rhythm_enabled` is true, a fourth async loop runs the oscillator at `self_rhythm_step_hz` and feeds the rhythm features into the forward-model vector. The `oscillator` extra (`snnTorch`) is required. In `womb` perception-feed mode the oscillator is driven by `MaternalDriveProvider`.

### Fatigue accumulation

Scalar integrator:

```text
F(t+dt) = max(0, F(t) + e·dt - decay·dt)
```

`e` is the unexpected prediction error. During a live hard-threshold breach the raw prediction error feeds the input instead; warm-up input dampening still applies while warm-up is active. During Hypnos sleep, the decay rate is multiplied by `3.0`. The accumulator resets to `0` on `hypnos.sleep.completed`.

### Regulation detector

Tracks how long the unexpected prediction error has been continuously above `regulation_threshold`. Each completed sustain window emits one escalating advisory. The detector resets the moment the error drops below threshold.

## Developmental warm-up

A newly booted or forked `SubstrateForwardModel` has not yet learned the host's substrate baseline, so cold-start prediction error would otherwise trip false allostatic advisories and inflate fatigue on noise alone. While `warmup_active` is true, Soma withholds `soma.regulation` advisories (publishing `soma.regulation.withheld` instead) and dampens the fatigue accumulator's input by subtracting the rolling prior-error baseline. The raw prediction-error signal in `soma.report` and any live `[soma.thresholds]` hard-alert breach are never gated.

Warm-up ends once the forward model has taken `regulation_warmup_min_samples` adaptation steps and `regulation_warmup_min_seconds` of subjective time have elapsed. If `regulation_warmup_require_error_stabilized` is true, recent prediction-error variance must also fall below `regulation_warmup_stable_variance`. This mirrors the individuation boundary's logged-lived-events + lived-running-time shape. Warm-up state is per-boot/per-fork runtime bookkeeping and is not serialized.

## Enabling and use

Add to your local `config/kaine.toml` (do not commit):

```toml
[modules]
soma = true
```

Soma needs no external services. GPU metrics appear automatically if `pynvml` is installed (a standard KAINE dependency on CUDA hosts). To change fatigue pressure, lower `fatigue_maintenance_threshold` or raise `fatigue_decay_per_s`.

## What Soma persists

Soma holds no raw metric data beyond the current tick. `serialize()` writes:

- the CfC readout weights and biases (`forward_model.weight`, `forward_model.bias`);
- the `reservoir_seed` used to reproduce the frozen CfC reservoir;
- scalar `fatigue.value`; the accumulator timestamp resets on revive;
- `expected_error` state;
- `cycle_cursor` and `read_interval_s`;
- `self_rhythm` state when self-rhythm is enabled.

The CfC reservoir is frozen and is rebuilt identically from `reservoir_seed` on revive, so a preserved being keeps its reservoir across preservation and revival. A snapshot without a seed starts a new reservoir and logs that the reservoir is new. A readout snapshot whose shape does not match the configured network is rejected and Soma keeps a fresh readout. The recurrent hidden state is ephemeral runtime context and starts at zero on revive; it is never persisted. Metric values themselves are never written to disk.

## Key files

| File | Role |
|---|---|
| `kaine/modules/soma/module.py` | `Soma` class — main orchestrator; four async task loops when self-rhythm is enabled |
| `kaine/modules/soma/reader.py` | `SystemMetricsReader` — `psutil`/`pynvml` integration |
| `kaine/modules/soma/wellness.py` | `compute_wellness()` — weighted normalised metric average |
| `kaine/modules/soma/detector.py` | `ThresholdAnomalyDetector` and `AnomalyDetector` protocol |
| `kaine/modules/soma/forward.py` | `SubstrateForwardModel`, `metrics_to_feature_vector()` |
| `kaine/modules/soma/expected_error.py` | `ExpectedErrorModel` — learned expected error and spread |
| `kaine/modules/soma/fatigue.py` | `FatigueAccumulator` |
| `kaine/modules/soma/regulation.py` | `RegulationDetector` — sustained-stress advisory ladder |

## Tests

| File | What it verifies |
|---|---|
| `tests/test_soma_module.py` | Core `Soma` publish loop, alert salience, wellness integration |
| `tests/test_soma_fatigue.py` | `FatigueAccumulator` dynamics, threshold crossing, reset |
| `tests/test_soma_forward.py` | `SubstrateForwardModel` step, non-finite guard, serialisation |
| `tests/test_soma_expected_error.py` | `ExpectedErrorModel` learning and unexpected-error signal |
| `tests/test_soma_regulation.py` | `RegulationDetector` escalation ladder, episode reset |
| `tests/test_soma_detector.py` | `ThresholdAnomalyDetector`, glob wildcard matching |
| `tests/test_soma_wellness.py` | `compute_wellness()` weighting and normalisation curves |
| `tests/test_soma_system_reader.py` | `SystemMetricsReader` graceful pynvml degradation |
| `tests/test_soma_hypnos_flag.py` | `_in_hypnos` flag set/clear, adaptation suspension |
| `tests/test_soma_warmup.py` | Developmental cold-start warm-up gate |
| `tests/test_soma_self_rhythm.py` | Self-rhythm oscillator integration |
| `tests/test_soma_self_rhythm_boot.py` | Boot wiring for the self-rhythm loop |
| `tests/test_cycle_soma_regulation.py` | `CycleEngine.consume_soma_regulation` — advisory handling |
| `tests/systems/test_soma_subsystem.py` | Redis-backed subsystem integration |

## Spec and related

- OpenSpec: `openspec/specs/soma/spec.md`
- OpenSpec (predictive): `openspec/specs/soma-predictive/spec.md`
- Related modules: `09-modules/hypnos.md` (fatigue consumer), `09-modules/thymos.md` (affect integration)
- Cognitive cycle: `08-cognitive-cycle/README.md`
