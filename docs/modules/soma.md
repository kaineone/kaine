# Soma

KAINE's interoceptive organ: predictive substrate monitoring, fatigue accumulation, and homeostatic regulation.

---

## Status

Implemented. Ships **disabled** — `[modules].soma = false` in `config/kaine.toml`.

- No optional extras required for the base module. GPU metrics need `pynvml` (nvidia GPU hosts only); gracefully degrades if unavailable.
- The `SubstrateForwardModel` requires `torch` and `ncps`; these are standard KAINE dependencies.
- Forward-model adaptation is automatically suspended during Hypnos offline cycles.

---

## Responsibility

In the PP+GWT framing, Soma is the entity's **interoceptive channel**: it reports the health of its computational substrate (CPU, RAM, GPU temperature/VRAM, cognitive-cycle latency) to Syneidesis so that bodily state can be integrated into the global workspace alongside other affective and perceptual streams.

Beyond passive reporting, Soma implements two predictive-processing additions:

1. **Predictive interoception** — A CPU-only closed-form continuous-time network (`SubstrateForwardModel`, a CfC via `ncps`) predicts the next substrate feature vector from the current one and its own recurrent hidden state. Prediction error (the magnitude of expected-minus-actual) drives salience: substrate surprises propagate to Syneidesis with appropriately elevated salience, while a steady, predictable substrate stays near-invisible.

2. **Homeostatic regulation** — Two tightly coupled subsystems ensure maintenance needs are surfaced rather than silently ignored:
   - **FatigueAccumulator** — integrates prediction error over waking time with continuous decay. When the accumulator crosses `fatigue_maintenance_threshold`, Soma publishes `soma.fatigue`, the emergent sleep-pressure signal that Hypnos monitors to schedule maintenance without reference to a wall-clock timer.
   - **RegulationDetector** — if prediction error remains above `regulation_threshold` for a sustained window, Soma publishes a `soma.regulation` advisory escalating through `reduce_rate` → `shed_module` → `request_maintenance`. Crucially, **Soma never actuates directly**: it publishes intents only; the cognitive cycle engine and Hypnos act on them.

---

## Inputs

| Bus stream | Event type consumed | Purpose |
|---|---|---|
| `cycle.out` | `cycle.tick` | Reads `wall_duration_ms` to maintain a rolling cycle-latency average |
| `hypnos.out` | `hypnos.sleep.started` | Sets `_in_hypnos = True`; suspends forward-model adaptation; enables faster fatigue decay |
| `hypnos.out` | `hypnos.sleep.completed` | Clears `_in_hypnos`; resets fatigue accumulator and regulation detector |

Soma also reads host metrics on its own timer loop via `SystemMetricsReader` (psutil + optional pynvml), outside the bus.

---

## Outputs

All events are published to the **`soma.out`** stream.

| Event type | Payload fields | Salience |
|---|---|---|
| `soma.report` | `metrics`, `wellness`, `alerts`, `prediction_error`, `fatigue_value`, `fatigue_threshold`, `warmup_active` | `baseline_salience` (default 0.1) when quiet; `alert_salience` (default 0.7) when alerts fire or prediction error is high |
| `soma.fatigue` | `value`, `threshold`, `crossed: true` | `alert_salience` |
| `soma.regulation` | `action`, `reason`, `severity` | `alert_salience` |
| `soma.warmup.started` | `min_samples`, `min_seconds`, `samples_seen`, `lived_seconds` | `baseline_salience` |
| `soma.warmup.completed` | `samples_seen`, `lived_seconds` | `baseline_salience` |
| `soma.regulation.withheld` | `would_be_action`, `prediction_error`, `sustain_elapsed_s`, `severity`, `reason: "warmup"` | `baseline_salience` |

`soma.report` is the primary stream. `soma.fatigue` fires once per threshold crossing (re-armed only after the fatigue value drops below threshold). `soma.regulation` escalates: `action` is one of `"reduce_rate"` (severity 1), `"shed_module"` (severity 2), `"request_maintenance"` (severity 3). `soma.warmup.started` / `soma.warmup.completed` mark the developmental warm-up boundary (see below); `soma.regulation.withheld` is a non-actuating record of a regulation advisory the warm-up gate suppressed — it is not consumed by the cognitive cycle engine, only logged for audit.

---

## Configuration

Section `[soma]` in `config/kaine.toml`. See also [../configuration.md](../configuration.md) for general conventions.

| Key | Default | Meaning |
|---|---|---|
| `read_interval_s` | `1.0` | Seconds between metric-read cycles |
| `cycle_latency_target_ms` | `300.0` | Healthy target for the cognitive cycle; deviations above this reduce wellness |
| `cycle_latency_window` | `64` | Rolling window size for cycle latency samples (note: accepted by boot but unused directly by `Soma` constructor; `SystemMetricsReader` uses its own fixed window of 64) |
| `baseline_salience` | `0.1` | Salience for routine `soma.report` events |
| `alert_salience` | `0.7` | Salience when threshold alerts, high prediction error, or fatigue fires |
| `forward_model_units` | `32` | Hidden size of the `SubstrateForwardModel` CfC reservoir |
| `prediction_error_window` | `32` | Rolling window length (ticks) for normalising prediction error into salience |
| `fatigue_decay_per_s` | `0.01` | Per-second decay rate for the fatigue accumulator; tripled during Hypnos sleep |
| `fatigue_maintenance_threshold` | `100.0` | Fatigue value at which `soma.fatigue` fires |
| `regulation_sustain_window_s` | `30.0` | Seconds of sustained high prediction error before a `soma.regulation` advisory is emitted |
| `regulation_threshold` | `0.5` | L2 prediction-error level that begins a regulation episode |
| `regulation_warmup_enabled` | `true` | Enables the developmental warm-up gate on the action path (regulation advisories + fatigue-input dampening) while the forward model learns the host's substrate baseline |
| `regulation_warmup_min_samples` | `1000` | Minimum forward-model adaptation samples before warm-up can end |
| `regulation_warmup_min_seconds` | `1200.0` | Minimum subjective seconds since boot (per the injected `EntityClock`) before warm-up can end |
| `regulation_warmup_require_error_stabilized` | `false` | Optional AND-guard: also require recent prediction-error variance to fall below `regulation_warmup_stable_variance` before warm-up ends |
| `regulation_warmup_stable_window` | `32` | Rolling window (ticks) used to compute prediction-error variance for the stabilization guard |
| `regulation_warmup_stable_variance` | `0.02` | Variance threshold below which prediction error counts as stabilized |

**`[soma.thresholds]`** — per-metric alert thresholds (default: `cpu_percent = 90.0`, `ram_percent = 90.0`, `gpu_*_temp_c = 83.0`, `gpu_*_vram_percent = 92.0`, `cycle_latency_avg_ms = 600.0`). Glob wildcards (`gpu_*_temp_c`) match all GPUs.

**`[soma.weights]`** — per-metric wellness weights (default: `cpu_percent = 1.0`, `ram_percent = 1.0`, `cycle_latency_avg_ms = 1.0`). Only metrics with defined normalization curves and positive weights contribute to the wellness score.

---

## How It Works

```mermaid
graph TD
    SysMetrics["SystemMetricsReader\n(psutil + pynvml)"] -->|read_metrics()| SomaTick["Soma.tick_once()"]
    CycleOut["cycle.out / cycle.tick\n(wall_duration_ms)"] -->|rolling avg| SysMetrics
    HypnosOut["hypnos.out"] -->|sleep.started / completed| SomaTick

    SomaTick --> WellnessCalc["compute_wellness()\nweighted avg of\nnormalised metrics"]
    SomaTick --> AnomalyDet["ThresholdAnomalyDetector\n(per-metric > threshold)"]
    SomaTick --> FwdModel["SubstrateForwardModel\nfeature → CfC reservoir (frozen) → hidden\nhidden → linear readout (online) → next_vec"]
    FwdModel -->|L2 error| FatigueAcc["FatigueAccumulator\nF += e·dt - decay·dt"]
    FwdModel -->|L2 error| RegDet["RegulationDetector\nsustained error > threshold"]
    FatigueAcc -->|threshold crossed| SomaFatigue["soma.fatigue"]
    RegDet -->|window expired| SomaReg["soma.regulation"]
    WellnessCalc --> SomaReport["soma.report\n+ salience"]
    AnomalyDet --> SomaReport
    FwdModel -->|prediction_error| SomaReport
```

### Metric collection

`SystemMetricsReader` calls `psutil.cpu_percent()`, `psutil.virtual_memory()`, disk I/O counters, and — when `pynvml` initialised successfully — per-GPU temperature and VRAM usage. All blocking calls run in a thread via `asyncio.to_thread()` so the event loop is never stalled. Failure of any individual metric silently omits that key; the wellness formula redistributes weight over the metrics that are present.

### Wellness score

`compute_wellness()` normalises each present metric to `[0, 1]` (1 = healthy) using per-key curves (e.g. `1 - cpu_percent/100`), then takes a weighted average. Result clamped to `[0, 1]`.

### SubstrateForwardModel (predictive interoception)

A closed-form continuous-time network (Hasani et al. 2022), via the `ncps` package — the same CfC pattern Chronos uses (`kaine.modules.chronos.network.CfCNetwork` / `ForwardPredictionHead`). Architecture: `feature (8-dim) → ncps.torch.CfC reservoir (frozen, units hidden) → hidden state → Linear(units → 8) readout (online)`, all CPU tensors. The reservoir's weights are randomly initialised and never trained; only the linear readout adapts, with one SGD step per tick. The feature vector is `cpu_percent/100`, `ram_percent/100`, `cycle_latency/2·target`, the hottest GPU's `gpu_*_temp_c/100` (0.0 when no GPU telemetry is available), then zero-padded. A non-finite loss/gradient guard skips weight updates, and a non-finite *input* feature additionally skips committing that tick into the CfC's recurrent state (so one bad sensor read cannot permanently corrupt the hidden state). Adaptation suspended (`suspended = True`) while `_in_hypnos`.

### FatigueAccumulator

Scalar integrator: `F(t+dt) = max(0, F(t) + e·dt - decay·dt)`. During Hypnos sleep, decay rate is multiplied by 3.0 (`faster_decay_factor`), so fatigue drops during rest. Resets to 0 on `hypnos.sleep.completed`.

### RegulationDetector

Tracks how long prediction error has been continuously above `regulation_threshold`. Each completed sustain window emits one escalating advisory. The detector resets the moment error drops below threshold.

### Developmental warm-up

A just-booted (or forked) entity's `SubstrateForwardModel` has not yet learned this host's substrate baseline, so its cold-start prediction error would otherwise trip false allostatic advisories and inflate the fatigue accumulator on noise alone. While `warmup_active` is true, Soma withholds `soma.regulation` advisories (publishing `soma.regulation.withheld` instead) and dampens the fatigue accumulator's *input* (subtracting the rolling prior-error baseline) — the prediction-error signal itself in `soma.report` and any live `[soma.thresholds]` hard-alert breach are never gated. Warm-up ends once the forward model has taken `regulation_warmup_min_samples` adaptation steps AND `regulation_warmup_min_seconds` of subjective time have elapsed (optionally ANDed with prediction-error stabilization); this mirrors the individuation boundary's "logged lived events + lived running time" shape. Warm-up state is per-boot/per-fork runtime bookkeeping and is never serialised.

---

## Key Files

| File | Role |
|---|---|
| `kaine/modules/soma/module.py` | `Soma` class — main orchestrator, three async task loops |
| `kaine/modules/soma/reader.py` | `SystemMetricsReader` — psutil/pynvml integration |
| `kaine/modules/soma/wellness.py` | `compute_wellness()` — weighted normalised metric average |
| `kaine/modules/soma/detector.py` | `ThresholdAnomalyDetector` and `AnomalyDetector` protocol |
| `kaine/modules/soma/forward.py` | `SubstrateForwardModel`, `metrics_to_feature_vector()` |
| `kaine/modules/soma/fatigue.py` | `FatigueAccumulator` |
| `kaine/modules/soma/regulation.py` | `RegulationDetector` — sustained-stress advisory ladder |

---

## Enabling & Use

Add to your local `config/kaine.toml` (do not commit):

```toml
[modules]
soma = true
```

Soma requires no external services. GPU metrics appear automatically if `pynvml` is installed (it is a standard KAINE dep on CUDA hosts). To adjust the fatigue pressure, lower `fatigue_maintenance_threshold` or raise `fatigue_decay_per_s`.

---

## Zero-Persistence Note

Soma holds **no raw metric data beyond the current tick**. Serialisation (`serialize()`) writes:
- The CfC readout's weight/bias tensors only (`forward_model.weight`, `forward_model.bias`).
- Scalar `fatigue.value` only; the accumulator time-stamp resets on deserialise.

The CfC reservoir itself is never serialised — like Chronos's `CfCNetwork`, it is a frozen, randomly-initialised projection, not learned content, so each boot starts with an independently-seeded reservoir (the readout re-equilibrates to it online within a few ticks). The reservoir's recurrent hidden state is likewise ephemeral runtime context, never persisted. Metric values themselves are never written to disk.

---

## Tests

| File | What it verifies |
|---|---|
| `tests/test_soma_module.py` | Core `Soma` publish loop, alert salience, wellness integration |
| `tests/test_soma_fatigue.py` | `FatigueAccumulator` dynamics, threshold crossing, reset |
| `tests/test_soma_forward.py` | `SubstrateForwardModel` step, non-finite guard, serialisation |
| `tests/test_soma_regulation.py` | `RegulationDetector` escalation ladder, episode reset |
| `tests/test_soma_detector.py` | `ThresholdAnomalyDetector`, glob wildcard matching |
| `tests/test_soma_wellness.py` | `compute_wellness()` weighting and normalisation curves |
| `tests/test_soma_system_reader.py` | `SystemMetricsReader` graceful pynvml degradation |
| `tests/test_soma_hypnos_flag.py` | `_in_hypnos` flag set/clear, adaptation suspension |
| `tests/systems/test_soma_subsystem.py` | Redis-backed subsystem integration |

---

## Spec & Related

- OpenSpec: [`openspec/specs/soma/spec.md`](../../openspec/specs/soma/spec.md)
- OpenSpec (predictive): [`openspec/specs/soma-predictive/spec.md`](../../openspec/specs/soma-predictive/spec.md)
- Related modules: [`hypnos.md`](hypnos.md) (fatigue consumer), [`thymos.md`](thymos.md) (affect integration)
- Cognitive cycle: [`../processes/cognitive-cycle.md`](../processes/cognitive-cycle.md)
