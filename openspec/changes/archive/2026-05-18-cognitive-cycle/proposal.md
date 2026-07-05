## Why

The cognitive cycle is the structural answer to "where does the mind live?"
in KAINE — not in any single module, but in the continuous loop that
collects each module's outputs, hands them to Syneidesis for salience
selection, broadcasts the resulting workspace snapshot, and gives Soma the
timing data it needs to perceive the system's own state
(`docs/kaine-paper.md` §2.2). Without it, modules publish into the bus but
nothing organizes their outputs into a coherent moment of awareness — there
is no "now" for the system.

This change introduces the loop separately from Syneidesis (the salience
function) because the loop's responsibilities — pacing, graceful module
absence, decoupled processing-and-experiential rates — are independent of
how salience is computed. Keeping them separate makes it possible to swap
Syneidesis v1 for v2 (gradient boosting) and v3 (GNN/VAE) without touching
the cycle itself.

## What Changes

- Introduce `kaine.cycle.engine.CognitiveCycle`, an async runner that on
  each tick (a) drains every active module's `events_out` stream, (b)
  hands the collected events to Syneidesis, (c) publishes a workspace
  snapshot to `workspace.broadcast`, and (d) records cycle latency into
  the bus for Soma to consume.
- Two independently-configurable rates per `docs/kaine-paper.md` §2.2:
  `processing_rate_hz` (how fast the hardware ticks; default 3.33 Hz for
  the 300 ms standard cycle) and `experiential_rate_hz` (how often a tick
  is promoted to a Mnemos-recordable broadcast; defaults to matching
  processing rate). Decoupling allows fast processing with slow
  experience or vice versa.
- Graceful module absence: a module that fails to respond or has no
  events in its stream is skipped silently in the same tick — the cycle
  never blocks on any one module. Modules that crash are flagged via the
  bus but the cycle continues.
- Runtime knobs exposed via the cycle's API: pause, resume, change rates,
  query current rate, query average latency. None of these wake or
  initialize modules.
- The cycle exits cleanly on shutdown by draining outstanding tasks and
  flushing the latency log.

## Capabilities

### New Capabilities

- `cognitive-cycle`: the main loop and its pacing controls. Owns event
  collection, Syneidesis invocation, broadcast emission, and Soma timing.
  Stateless across restarts beyond its config — module state lives in
  each module.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus` (publish/subscribe primitives), and a stub
  `Syneidesis` interface from `module-pattern` (real Syneidesis lands in
  the next change).
- **Repo:** adds `kaine/cycle/engine.py`, `kaine/cycle/rates.py`, and
  `tests/test_cycle.py` with fake-clock tests for rate decoupling.
- **No runtime impact** — the cycle class is instantiable but its
  `run_forever()` is never called by any committed code in this change.
  The first boot script (Phase 9.4) is what actually starts it.
