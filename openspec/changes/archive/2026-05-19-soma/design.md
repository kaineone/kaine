## Context

KAINE Phase 2.1. Phase 1 left a working bus + cycle + Syneidesis +
module-pattern stack. Soma is the first real module to instantiate that
pattern. It is also the canonical interoception surface — the thing that
tells the rest of the system what state its hardware body is in —
which makes it the input to Thymos (Phase 4) and a primary diagnostic
producer for Nexus (Phase 8).

Constraints:
- All-local: psutil and pynvml are local-only Python deps. pynvml talks
  to the in-kernel NVML library; no network.
- Portable: pynvml may not initialize on hosts without NVIDIA drivers
  (CI, ARM dev boxes). Soma must degrade gracefully and still produce a
  useful wellness score from CPU/RAM/disk/latency alone.
- Single ownership of `soma.out`: Soma is the only publisher; consumers
  (Thymos eventually, Nexus eventually, anomaly subscribers in the
  meantime) read from it.
- Soma consumes `cycle.out` for latency events (per cognitive-cycle
  spec) but does not implement a generic stream-subscription helper in
  BaseModule. Stays local to Soma until a second module needs the same
  pattern.

Stakeholders: Thymos (Phase 4, will subscribe to soma.out for
homeostatic drift inputs), Nexus diagnostics (Phase 8, will display
wellness/latency over time), the cycle (its latency events feed Soma).

## Goals / Non-Goals

**Goals:**
- A `Soma` module that, when started, publishes a `soma.report` event
  every `read_interval_s` (default 1.0 s) carrying current metrics,
  normalized wellness, and the current anomaly state.
- Anomaly alerts elevate the published event's salience so Syneidesis
  picks them up (default salience 0.7 for alerts, 0.1 for baseline).
- Gracefully degrade when pynvml is unavailable or returns errors.
  Same posture for psutil disk I/O.
- Pure-function wellness so it is unit-testable without mocks.
- Strategy seams for both the metrics backend and the anomaly detector
  so Phase 4+ can swap in real implementations without touching Soma.

**Non-Goals:**
- A generic "subscribe to peer stream" helper in BaseModule. Soma
  manages its `cycle.out` cursor itself. Promotion to BaseModule
  happens if/when the second module needs the same pattern.
- A time-series persistence layer for metrics. Mnemos (Phase 3.2) is
  the persistence story; Soma's bounded in-memory window is enough
  for Phase 2.
- ML-based anomaly detection. The threshold detector is the v1; the
  `AnomalyDetector` protocol is the v2/v3 seam.
- A Nexus-facing aggregator. Nexus subscribes to soma.out directly
  when Phase 8 lands.

## Decisions

**Split into four files inside `kaine/modules/soma/`.** Reader, detector,
wellness, and module each have a single responsibility:
- `reader.py` — `MetricsReader` protocol and `SystemMetricsReader`
  default. Owns `psutil` + `pynvml` calls and tolerates each failure
  mode independently.
- `detector.py` — `AnomalyDetector` protocol, `AlertResult` dataclass,
  `ThresholdAnomalyDetector` default. Pure inputs → outputs; no I/O.
- `wellness.py` — `compute_wellness(metrics, weights)` pure function
  plus per-metric normalization helpers.
- `module.py` — `Soma` BaseModule subclass orchestrating the above.

Splitting matches how subsequent modules are likely to be organized
(Chronos: reader + network + module; Topos: reader + encoder + module).

**`MetricsReader.read_metrics()` returns a flat `dict[str, float]`.**
Keys follow the convention `cpu_percent`, `ram_percent`,
`disk_read_bytes`, `disk_write_bytes`, `gpu_<i>_temp_c`,
`gpu_<i>_vram_percent`, `cycle_latency_avg_ms`, `uptime_s`. Flat dicts
serialize through the bus cleanly, are trivial to assert in tests, and
map directly to Nexus time-series later.

**Cycle-latency averaging window is in-memory only.** A `deque(maxlen=N)`
in Soma. Window default 64 samples. Phase 9 maintenance can persist if
needed; Phase 2 doesn't need it.

**pynvml init is lazy and one-shot.** On `Soma.initialize`, attempt
`nvmlInit()`. On failure, log a single WARNING with the error message
and remember a `gpu_available = False` flag. Subsequent reads skip GPU
metrics. Shutdown attempts `nvmlShutdown()` if init succeeded; failures
during shutdown are warnings only.

**`SystemMetricsReader.read_metrics` is async to match the protocol but
the underlying calls are synchronous.** Run them with
`loop.run_in_executor(None, ...)` so the cycle's event loop is not
blocked when pynvml or psutil takes a few milliseconds. Defaults to
`asyncio.to_thread` (Python 3.11+).

**`ThresholdAnomalyDetector` thresholds default to:** `cpu_percent>90`,
`ram_percent>90`, `gpu_*_temp_c>83`, `gpu_*_vram_percent>92`,
`cycle_latency_avg_ms>600` (2× the 300 ms target). Each is overridable
in `config/kaine.toml`. The detector returns an `AlertResult` with the
violated keys; Soma elevates salience on any non-empty alert set.

**Wellness normalization curves are linear with clamping**:
- `cpu_percent` and `ram_percent`: `1 - x/100`.
- `gpu_<i>_temp_c`: `1 - max(x-30, 0)/50`, clamped to `[0, 1]`. 30 °C
  is healthy idle; 80 °C is full load (score 0); 30→80 is the band.
- `gpu_<i>_vram_percent`: `1 - x/100`.
- `cycle_latency_avg_ms` vs configured target: `1 - max(x-target, 0)/(2*target)`.
- Anything not normalized contributes weight 0.

Linear curves are interpretable, easy to test, and easy to replace with
a learned mapping later.

**Soma is registered manually by the first-boot script, not auto-added
to the registry.** `config/kaine.toml`'s `[modules]` section now has
`soma = false` (default). Setting it `true` is the operator's signal
that Soma should be registered on boot. Phase 9.4 wires this up.

## Risks / Trade-offs

- **psutil disk I/O on a container can be flaky.** → `SystemMetricsReader`
  catches and drops, falling back to a metrics dict without disk
  fields. Wellness adjusts weight basis automatically.
- **pynvml requires NVML library access.** → If init fails, GPU metrics
  are silently omitted; one-time warning logged. Tests do not exercise
  the GPU read path against real hardware.
- **One-second read interval may be too coarse to catch sub-second
  spikes.** → Acceptable: spikes that don't last a second don't merit
  a high-salience alert. Operators can lower the interval in
  `kaine.toml`.
- **`asyncio.to_thread` defaults to the default executor; concurrent
  modules using it could starve.** → Phase 9 measures, swaps to a
  bounded executor if needed. For Phase 2 this is fine.
- **Wellness composes weights from metrics actually present.** If pynvml
  is missing, GPU contributions are absent and the score reflects
  CPU/RAM/latency only. Documented; consumers do not assume a fixed
  weight basis.

## Migration Plan

First implementation; no migration. Soma comes online once Phase 9.4's
first-boot script registers it. Until then, Soma is instantiable and
tested but inert in the running system (because the cycle is not
running).

## Open Questions

- Whether `uptime_s` belongs in `soma.out` payloads or should be a
  separate `soma.boot_time` event published once at initialize. Leaving
  in the payload for now; revisit if Nexus prefers a separate stream.
- Whether to add Linux-specific kernel pressure metrics (PSI: `cpu`,
  `memory`, `io` from `/proc/pressure/*`). These are richer than
  raw psutil percentages but Linux-only. Deferring until Phase 9 unless
  Thymos asks for them.
