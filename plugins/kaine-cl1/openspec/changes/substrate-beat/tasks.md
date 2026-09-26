## 1. Broker

- [ ] 1.1 Beat mode: `beat()` closes one window; latest observation per territory; pending stim delivered at the next window start; latest-request-wins per territory.
- [ ] 1.2 Accelerated runner: synchronous window per beat, one processing period long (`1 / processing_rate_hz`).
- [ ] 1.3 Real-time runner: background loop thread; `beat()` marks the boundary and swaps under a lock; clean shutdown on close.
- [ ] 1.4 Standalone fallback until the first beat; log the switch.

## 2. Plugin and backends

- [ ] 2.1 `Cl1Plugin.on_cycle_tick(tick)`; relax the accelerated-time requirement when real-time beat mode is available.
- [ ] 2.2 Chronos, Soma and oscillator backends: queue for next, read latest (beat mode); per-step behaviour unchanged in standalone mode.

## 3. Tests

- [ ] 3.1 Three consumers, one beat: exactly one window; each reads its own territory.
- [ ] 3.2 One-cycle latency: evoked response visible after the following beat.
- [ ] 3.3 Real time: `on_cycle_tick` and steps return promptly while the loop runs (simulator real-time mode).
- [ ] 3.4 Standalone fallback and the logged switch.
- [ ] 3.5 Boot through KAINE with the hook: windows advance once per tick.

## 4. Docs

- [ ] 4.1 `docs/cl1.md`: replace the per-step clock note with the beat semantics and the one-cycle latency.
