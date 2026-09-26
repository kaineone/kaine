## Why

A plugin that replaces a model with an external, stateful substrate needs to know when KAINE's cognitive cycle ticks. The CL1 substrate plugin in `plugins/kaine-cl1` is the first case. Today each consumer of its substrate advances the substrate by its own window, so substrate time runs faster than cognitive time and several consumers cannot share one timeline (review finding on kaine #197). On a real-time substrate this also serialises consumers on one loop. The fix is one substrate window per cognitive cycle, and for that the plugin needs the cycle's beat. The cycle publishes `cycle.tick` on the bus, but plugins receive no bus handle, and giving them one would widen their access far beyond what they need.

## What Changes

- **An optional plugin hook.** A plugin object may implement `on_cycle_tick(tick: Mapping[str, Any]) -> None`. After each cycle tick, KAINE calls it once per loaded plugin that implements it, with the same fields the cycle publishes on `cycle.tick`: `tick_index`, `wall_duration_ms`, `target_duration_ms`, `slip_ms`, `is_experiential`, `processing_rate_hz`, `experiential_rate_hz` (effective for that tick) and `access_drive`.
- **Observation only.** The hook receives a read-only copy of those fields and returns nothing that KAINE uses. It cannot change the cycle, the workspace or any module.
- **It never stops the cycle.** An exception from the hook is logged at WARNING (the first failure, then every 100th, naming the plugin) and the cycle continues. The hook runs synchronously inside the tick on the cycle's event loop, so it must return quickly and do heavy work elsewhere (a background thread, for example). KAINE times every call and logs a rate-limited WARNING naming the plugin when a call exceeds 10% of the target tick period (10 ms at 10 Hz).
- **No hook, no change.** Plugins without `on_cycle_tick`, and runs with no plugins, behave exactly as today: with no observer the call site is a no-op, so deterministic runs stay byte-identical. Ticks that do not run (a frozen entity) do not call the hook.
- **Recorded.** The manifest's plugin entry gains `observes_cycle: true|false` so a run's record shows which plugins followed the cycle.

## Impact

- Code: `kaine/plugins.py` (`LoadedPlugins.dispatch_cycle_tick`, manifest field); `kaine/cycle/engine.py` (one optional tick-observer callable, called after the `cycle.tick` publish); `kaine/cycle/__main__.py` (passes the loaded plugins' dispatcher in); `docs/plugins.md`.
- Import boundaries unchanged: the engine receives a plain callable and never imports `kaine.plugins`.
