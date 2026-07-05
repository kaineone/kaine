## Context

KAINE Phase 1.2. The event-bus capability is in place: modules can publish
to `<module>.out` streams and Syneidesis owns `workspace.broadcast`. What
is missing is the loop that ties it together — the thing that decides when
"now" is and what every module experiences as a single moment of awareness.

The cycle is intentionally minimal: pacing, event collection, Syneidesis
hand-off, broadcast, Soma timing. Anything heavier (salience computation,
goal evaluation, drive states) lives in its own module behind its own bus
stream. Keeping the cycle thin is what makes module-shedding (paper §4.4)
and variable-speed cognition (§4.1) tractable — both operate on the cycle
itself, not on every module.

Constraints:
- Asyncio throughout. Modules will be async; the bus is async; mixing
  sync work into the cycle defeats the bus's non-blocking semantics.
- Soma must see real wall-clock timings; the cycle records latency in
  the same time base it paces by.
- Module absence is the norm, not an exception. The cycle starts before
  modules register and continues running when a module crashes.
- Variable-speed cognition (§4.1, §2.2): processing rate and
  experiential broadcast rate are independent parameters.

Stakeholders: every module (consumes broadcast), Syneidesis (selects per
cycle), Soma (consumes latency), Hypnos (pauses and resumes cycle).

## Goals / Non-Goals

**Goals:**
- A `CognitiveCycle` async runner with `run_forever()`, `tick()`,
  `pause()`, `resume()`, `set_processing_rate()`,
  `set_experiential_rate()`, `shutdown()`.
- Per-tick flow: collect from each registered module's `<name>.out`
  stream, hand collected events plus context to Syneidesis, optionally
  broadcast the snapshot (gated by the experiential rate), record
  latency.
- Variable speed: processing rate (Hz) and experiential rate (Hz) are
  independent. Experience promotion is a counter: every
  `processing_rate / experiential_rate` ticks, the snapshot is
  broadcast as a Mnemos-recordable experience.
- Graceful module absence: a module with no events this tick is
  skipped; a module returning an error increments a counter and is
  reported on the next tick but does not stop the cycle.
- Deterministic shutdown: `shutdown()` drains pending tasks, flushes
  Soma latency, closes the bus connection.

**Non-Goals:**
- Real Syneidesis logic. The cycle takes a `Syneidesis`-shaped
  collaborator and calls `select(...)`. The real impl lands in the
  Phase 1.3 change.
- Real module registry. The cycle accepts a `ModuleRegistry`-shaped
  collaborator that lists active modules and their stream names. The
  real registry lands in the Phase 1.4 change. Phase 1.2 ships a
  minimal `InMemoryModuleRegistry` for tests.
- Multi-process or distributed cycle. KAINE is single-host single-cycle.

## Decisions

**Async runner, not a thread.** Asyncio matches the bus and avoids GIL
contention for I/O-bound work. The cycle awaits `asyncio.sleep` between
ticks. Future module work that is CPU-bound (e.g. Topos forward pass)
runs in a `loop.run_in_executor` from inside that module, never inside
the cycle.

**Rate as a target, not a guarantee.** Each tick computes the actual
duration and `asyncio.sleep`s the remainder of the budget. If the tick
overran, the next sleep is zero and a slip event is published to
`soma.in` for Soma to react to. The cycle never drops events to catch
up — it lets slippage propagate to Soma's wellness score.

**Experiential rate is a divisor of processing rate, computed as a
floating ratio.** Internal state holds a `_experience_accumulator`
that ticks up by `experiential_rate / processing_rate` each cycle;
when it crosses 1.0, the snapshot is promoted to a Mnemos-recordable
broadcast (a flag in the snapshot) and the accumulator drops by 1.0.
Result: arbitrary ratios work, not just integer divisors.

**Collect from streams in parallel.** `asyncio.gather` over per-module
`bus.read(stream, last_id=<per-module cursor>)`. Cursor tracking lets
the cycle pick up where it left off across pauses and crashes. Cursors
are kept in memory; the cycle does not persist them — that is owned by
each module if it needs durable consumer-group semantics.

**Latency log publishes to `cycle.out` following the `<module>.out`
convention.** The cycle is treated as a module for bus addressing
purposes (source `cycle`) even though it does not go through the
BaseModule lifecycle. Soma subscribes to `cycle.out` like any other
consumer. Earlier draft considered a dedicated `soma.in` stream;
rejected because it breaks convention and Soma already filters by
source.

**A `CycleHooks` protocol exposes the lifecycle.** Modules can request
notifications on `on_pause`, `on_resume`, `on_shutdown`. Phase 1 ships
the protocol and Hypnos (Phase 6) uses it to pause the cycle for sleep.

## Risks / Trade-offs

- **Cycle blocking on a slow module's `bus.read`.** → Mitigation:
  reads are bounded by `block_ms=0` (non-blocking) by default; the
  cycle never waits for data. Modules that need to wait can do their
  own blocking reads in their own task.
- **Rate drift under sustained overrun.** → Mitigation: Soma sees the
  slip events and lowers wellness; Hypnos can schedule earlier rest;
  variable-speed-cognition explicitly lets the operator lower rates.
- **Asyncio scheduler fairness under heavy module count.** → Mitigation:
  Phase 7 fork/merge stress tests will exercise the cycle with module
  shedding; if fairness becomes a problem we add an `asyncio.shield`
  per module-collect coroutine.
- **Experiential accumulator drift across long uptimes.** → Mitigation:
  ratio is recomputed each tick from the current configured rates, so
  rate changes take effect immediately and the accumulator is never
  more than 1.0 off.

## Migration Plan

First implementation; no migration. Hypnos and the first boot script
are the only callers; both ship later.

## Open Questions

- Whether to publish a "tick" event to a `cycle.heartbeat` stream for
  Nexus diagnostics or whether the existing Soma latency events are
  enough. Defer until Phase 8.
