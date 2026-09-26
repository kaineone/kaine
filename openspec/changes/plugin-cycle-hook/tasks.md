## 1. Core

- [ ] 1.1 `LoadedPlugins.dispatch_cycle_tick(payload)`: copy the payload, call each plugin's `on_cycle_tick`, rate-limited WARNING on exceptions; `observes_cycle` in `manifest_entry()`.
- [ ] 1.2 `CognitiveCycle`: optional `tick_observer: Callable[[Mapping[str, Any]], None]` constructor argument, called after the `cycle.tick` publish with the same payload; never raises into the cycle.
- [ ] 1.3 `cycle/__main__.py`: pass `plugins.dispatch_cycle_tick` when plugins are loaded.

## 2. Tests

- [ ] 2.1 Three ticks call the hook three times with increasing `tick_index`.
- [ ] 2.2 Plugin without the hook: no call, no error; no plugins: identical behaviour.
- [ ] 2.3 A raising hook: all ticks complete, one WARNING in five failures.
- [ ] 2.4 Mutating the argument changes neither the cycle nor the published event.
- [ ] 2.5 Manifest `observes_cycle`.

## 3. Docs

- [ ] 3.1 `docs/plugins.md`: the hook, its fields, "keep it short", and the failure rule.
