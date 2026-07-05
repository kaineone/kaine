## 1. Dependencies and packaging

- [x] 1.1 Add `psutil>=5.9,<7` and `pynvml>=11.5,<13` to `pyproject.toml` dependencies
- [x] 1.2 Add `kaine.modules.soma` to the setuptools packages list
- [x] 1.3 `pip install -e .[test]` in the venv to pick up the new deps

## 2. Reader

- [x] 2.1 Implement `kaine/modules/soma/reader.py` with `MetricsReader` protocol and `SystemMetricsReader` default — psutil for CPU/RAM/disk, pynvml for GPU temps and VRAM, all wrapped in graceful try/except blocks; reads execute off the event loop via `asyncio.to_thread`
- [x] 2.2 `SystemMetricsReader.initialize()` lazily calls `pynvml.nvmlInit()` and remembers a `gpu_available` flag; shutdown calls `nvmlShutdown()` if init succeeded
- [x] 2.3 `SystemMetricsReader` exposes `update_cycle_latency_sample(ms)` so Soma can feed in cycle.out samples and have them appear in subsequent reads as `cycle_latency_avg_ms`

## 3. Anomaly detector

- [x] 3.1 Implement `kaine/modules/soma/detector.py` with `AnomalyDetector` protocol, `AlertResult` dataclass, and `ThresholdAnomalyDetector` default applying per-metric `>` comparisons against configured thresholds
- [x] 3.2 Missing metrics never alert; unknown metric keys in the threshold dict are ignored; wildcard threshold keys (`gpu_*_temp_c`) match all GPU indices

## 4. Wellness

- [x] 4.1 Implement `kaine/modules/soma/wellness.py` with `compute_wellness(metrics, weights) -> float` pure function applying the linear normalizations from the spec, clamping to `[0, 1]`, and using only the metrics actually present in the dict

## 5. Module

- [x] 5.1 Implement `kaine/modules/soma/module.py` with `Soma(BaseModule)` — `name = "soma"`, accepts optional MetricsReader and AnomalyDetector, default constructors wire up SystemMetricsReader and ThresholdAnomalyDetector with config-driven thresholds and weights
- [x] 5.2 `Soma.initialize` starts (a) the BaseModule workspace consumer, (b) a producer task ticking every `read_interval_s` that reads metrics, computes wellness, evaluates alerts, and publishes a `soma.report`, and (c) a `cycle.out` consumer task that feeds `cycle.tick` payloads into `update_cycle_latency_sample`
- [x] 5.3 `Soma.shutdown` cancels both producer and cycle consumer tasks and calls the reader's shutdown for NVML cleanup
- [x] 5.4 Update `kaine/modules/__init__.py` to export `Soma`

## 6. Config

- [x] 6.1 Add `[soma]` block to `config/kaine.toml` with `read_interval_s = 1.0`, default thresholds, default weights, default `cycle_latency_target_ms = 300.0`, and default `cycle_latency_window = 64`
- [x] 6.2 Add `soma = false` under `[modules]` so first boot requires explicit opt-in

## 7. Tests

- [x] 7.1 Write `tests/test_soma_wellness.py` covering: healthy yields 1.0, mid-range yields mid wellness, GPU absence does not penalize, latency above target reduces wellness, clamping to [0, 1] (14 cases)
- [x] 7.2 Write `tests/test_soma_detector.py` covering: threshold breaches, no-alert paths, missing metrics, custom detector substitution, wildcard threshold keys (10 cases)
- [x] 7.3 Write `tests/test_soma_module.py` using injected MetricsReader and AnomalyDetector against fakeredis: baseline report has empty alerts and low salience; threshold breach raises salience; cycle.out latency samples appear in metrics; pynvml init failure does not stop the module; shutdown cleanly cancels tasks (9 cases)
- [x] 7.4 Write `tests/test_soma_system_reader.py` exercising `SystemMetricsReader` against real psutil and verifying the pynvml init-failure-tolerated path via a monkeypatched pynvml module (5 cases)

## 8. Verification

- [x] 8.1 Run full unit suite; all pass (123 passed, 3 integration skipped 2026-05-19)
- [x] 8.2 `openspec validate soma --strict` clean
- [ ] 8.3 Commit on branch `soma`, merge to `main`
- [ ] 8.4 `openspec archive soma` so the new `soma` capability lands at `openspec/specs/soma/spec.md`
- [ ] 8.5 Delete branch
