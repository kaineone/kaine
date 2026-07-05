## Why

`docs/kaine-paper.md` §3.1 places interoception ahead of every other
perception: "without interoceptive grounding the affect system has no body
to be embodied in." Soma is that grounding. It is also the simplest module
in the architecture (CPU-only, no model load), which makes it the right
first real module to ship — it establishes that the BaseModule contract
and ModuleRegistry from Phase 1 actually compose with a non-test module
and proves the cycle's latency log feeds back into a perceiving consumer.

The build prompt §2.1 names Soma as the first Phase 2 piece for the same
reason: simplest, lowest-risk, establishes the pattern.

## What Changes

- Introduce `kaine.modules.soma` package containing:
  - `MetricsReader` protocol and `SystemMetricsReader` default that
    pulls CPU/RAM/disk via `psutil`, GPU temps and VRAM via `pynvml`,
    cycle latency via the recent `cycle.out` events Soma has seen, and
    uptime via `psutil.boot_time()`. Failures (no NVIDIA hardware, no
    disk I/O counters in container) degrade gracefully.
  - `AnomalyDetector` protocol and `ThresholdAnomalyDetector` default
    that flags out-of-band metrics against configurable thresholds.
    The protocol is the seam for a future gradient-boosted detector
    per build prompt §2.1's "hook for gradient boosting anomaly
    detector later."
  - `WellnessCalculator` pure-function module: normalizes each metric
    into `[0, 1]` (1 = healthy) and weighted-averages into a single
    score per build prompt §2.1's "publish normalized wellness score."
  - `Soma` BaseModule subclass that runs two background tasks on top
    of the BaseModule workspace consumer: a producer reading metrics
    every `read_interval_s` and publishing a `soma.report` event, and
    a `cycle.out` subscriber feeding latency samples back into the
    metrics reader.
- Add `pynvml>=11.5,<13` and `psutil>=5.9,<7` to `pyproject.toml`. Both
  are pure-Python wheels (psutil with platform-specific C bits) and
  load entirely locally — no network at runtime.
- Add `[soma]` section to `config/kaine.toml` (read interval,
  per-metric thresholds, per-metric wellness weights) and a
  `modules.soma = false` flag so the first-boot script can opt Soma in
  explicitly. Soma is NOT enabled by default — first boot is
  operator-supervised, per build prompt's "DO NOT BOOT THE ENTITY."
- Tests use an injected `MetricsReader` so the suite runs on machines
  with no NVIDIA hardware. A separate suite verifies the
  `SystemMetricsReader` against real psutil; the pynvml read paths are
  exercised only via injected fakes so CI stays portable.

## Capabilities

### New Capabilities

- `soma`: interoception. Owns metrics reading (CPU, RAM, disk I/O, GPU
  temps/VRAM, cycle latency, uptime), normalized wellness score, and
  threshold-based anomaly alerts, with strategy seams for the future
  gradient-boosted detector and any alternate metrics backend.

### Modified Capabilities

None — Soma is purely additive on the Phase 1 substrate.

## Impact

- **Depends on:** `event-bus` (publish, read), `module-pattern`
  (BaseModule lifecycle and workspace consumer), `cognitive-cycle`
  (publishes the latency events Soma consumes). All shipped.
- **Repo:** adds `kaine/modules/soma/__init__.py`, `kaine/modules/soma/reader.py`, `kaine/modules/soma/detector.py`, `kaine/modules/soma/wellness.py`, `kaine/modules/soma/module.py`, `tests/test_soma_wellness.py`, `tests/test_soma_detector.py`, `tests/test_soma_module.py`, `tests/test_soma_system_reader.py`, updates to `pyproject.toml` (packages, deps), `config/kaine.toml` (`[soma]`).
- **Hardware-dependent behavior:** GPU metrics appear when pynvml can
  initialize NVML on the host. On machines without NVIDIA drivers
  (CI, dev laptops), Soma logs a one-time warning and proceeds with
  CPU/RAM/disk/latency only. The wellness score adjusts its weight
  basis to the metrics actually available.
- **No runtime impact** — Soma is registered in code paths but the
  cycle is still never started. First boot remains operator-supervised.
