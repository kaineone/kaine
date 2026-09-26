## 1. Broker

- [x] 1.1 Beat mode: `beat()` closes one window; latest observation per territory; pending stim delivered at the next window start; latest-request-wins per territory.
- [x] 1.2 Accelerated runner on the background thread: one window per signal, one processing period long (`1 / processing_rate_hz`).
- [x] 1.3 Real-time runner: background loop thread; `beat()` marks the boundary and swaps under a lock; clean shutdown on close.
- [x] 1.4 Standalone fallback until the first beat; log the switch.

## 2. Plugin and backends

- [x] 2.1 `Cl1Plugin.on_cycle_tick(tick)`; relax the accelerated-time requirement when real-time beat mode is available.
- [x] 2.2 Chronos, Soma and oscillator backends: queue for next, read latest (beat mode); per-step behaviour unchanged in standalone mode.

## 3. Tests

- [x] 3.1 Three consumers, one beat: exactly one window; each reads its own territory.
- [x] 3.2 One-cycle latency: evoked response visible after the following beat.
- [x] 3.3 `on_cycle_tick` returns in well under 10% of the tick period in both runners; steps never wait (simulator real-time and accelerated modes).
- [x] 3.4 Standalone fallback and the logged switch.
- [x] 3.5 Boot through KAINE with the hook: windows advance once per tick.

## 4. Docs

- [x] 4.1 `docs/cl1.md`: replace the per-step clock note with the beat semantics and the one-cycle latency.
