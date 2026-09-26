## 1. Core

- [x] 1.1 `LoadedPlugins.dispatch_cycle_tick(payload)`: copy the payload, call each plugin's `on_cycle_tick`, rate-limited WARNING on exceptions; `observes_cycle` in `manifest_entry()`.
- [x] 1.2 `CognitiveCycle`: optional `tick_observer: Callable[[Mapping[str, Any]], None]` constructor argument, called after the `cycle.tick` publish with the same payload and the tick's target period; never raises into the cycle; skipped when None and on ticks that do not run.
- [x] 1.3 `cycle/__main__.py`: pass `plugins.dispatch_cycle_tick` when plugins are loaded.

## 2. Tests

- [x] 2.1 Three ticks call the hook three times with increasing `tick_index`.
- [x] 2.2 Plugin without the hook: no call, no error; no plugins: identical behaviour.
- [x] 2.3 A raising hook: all ticks complete, one WARNING in five failures.
- [x] 2.4 Mutating the argument changes neither the cycle nor the published event.
- [x] 2.5 Manifest `observes_cycle`.
- [x] 2.6 Slow hook: one WARNING over three 50 ms calls against a 100 ms target; ticks complete.
- [x] 2.7 No observer: the call site is a no-op (deterministic-run event equality); frozen ticks do not call the hook.

## 3. Docs

- [x] 3.1 `docs/plugins.md`: the hook, its fields, "keep it short", and the failure rule.
