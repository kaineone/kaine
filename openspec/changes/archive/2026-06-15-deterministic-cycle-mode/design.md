# Design: deterministic cycle mode

## What is and isn't guaranteed

Deterministic mode guarantees that two runs with the same seed and the same input
sequence produce an identical **cognitive trajectory**: the same selected
coalitions, the same salience scores, the same inhibition decisions, the same
volition outputs, and the same *logical* event timestamps, tick by tick.

It does NOT make wall-clock timing reproducible. `wall_duration_ms`, `slip_ms`,
and real latency are physical measurements of the host and are inherently
variable; they remain in the logs (real time still elapses) but are excluded from
the identity comparison. This boundary is deliberate and documented: the ablation
compares cognition, not the clock.

## Source of nondeterminism, and the fix

A1 already pinned `random`/`numpy`/`torch` globals via `set_global_seed` at boot,
and the audit confirmed the selection (`syneidesis.py`) and volition paths contain
no RNG. Two residual sources remain:

1. **Event timestamps.** `engine.py:264, 317, 533` call
   `datetime.now(timezone.utc)` directly, so published events and the latency
   record carry real wall-clock time → logs never match across runs.
   - Fix: add `wall_clock: Callable[[], datetime]` to `CognitiveCycle.__init__`
     (default `lambda: datetime.now(timezone.utc)`). Route the three sites through
     `self._wall_clock()`.
   - Deterministic mode injects a **logical clock**: a small callable returning
     `BASE_EPOCH + timedelta(seconds=tick_index * target_tick_period)`. It reads
     the engine's current `tick_index` so each tick's events get a stable,
     monotonic, run-independent timestamp. `BASE_EPOCH` is a fixed constant
     (e.g. `1970-01-01T00:00:00Z` or a project epoch).

2. **Within-tick event ordering.** Events are gathered per stream via
   `asyncio.gather` over `registry.active_streams()` and `events.extend(entries)`.
   `gather` preserves input order, so this is *currently* deterministic given
   stable stream order — but it's an implicit contract. The selection sort
   (`scored.sort(key=score, reverse=True)`) is stable, so equal-score ties resolve
   by list position = gather order.
   - Fix: before scoring/selection, apply a **canonical total order** to the
     per-tick event list: sort by `(source, type, entry_id)` (all stable strings;
     `entry_id` is the unique bus id). This makes tie-break behavior explicit and
     independent of dispatch incidentals. Applied unconditionally (it's a stable
     no-op for the already-ordered common case) OR gated to deterministic mode —
     **recommend unconditional**, so production and deterministic runs share one
     ordering rule and the ablation's "only the layer differs" claim is airtight.
     (If unconditional ordering changes any existing test's expected selection,
     prefer gating to deterministic mode and document why.)
   - **Decision (implemented): unconditional.** The canonical sort is applied
     on every tick, not gated to deterministic mode. The full cycle/workspace/
     syneidesis/coherence test set (including the bit-for-bit ablation
     `test_syneidesis_coherence.py`) stays green, so no existing selection or
     tie-break expectation changed — confirming the no-op claim for the
     already-ordered common case.

## Wiring

- `CognitiveCycle.__init__` gains `wall_clock` (and keeps the existing monotonic
  `clock` for durations — unchanged). The two clocks are distinct: `clock`
  (monotonic float) measures elapsed time for slip/latency; `wall_clock`
  (datetime) stamps events.
- A `deterministic: bool` plumbed from `[experiment].deterministic` at
  `kaine/cycle/__main__.py`. When true, the entrypoint constructs the engine with
  a logical `wall_clock` bound to the engine's tick counter. (Constructing a clock
  that needs the engine's tick_index: pass a tiny object/closure that the engine
  updates, or have the engine itself switch to logical stamping when a
  `deterministic` flag is set on it — simpler: give the engine a `deterministic`
  attribute and compute the logical timestamp internally from `self._tick_index`
  when set, else call the injected `wall_clock`.)
- Recommended concrete shape: `CognitiveCycle(..., deterministic: bool = False,
  wall_clock=<default real>)`. `def _now(self): return self._logical_now() if
  self._deterministic else self._wall_clock()`. `_logical_now` =
  `BASE_EPOCH + timedelta(seconds=self._tick_index * self._target_tick_period_s)`.

## Config

```
[experiment]
# ... seed, write_manifest (from experiment-run-identity) ...
# Deterministic mode: logical clock + canonical event ordering so a run is
# bit-for-bit reproducible (same seed + input → same trajectory). Off in
# production (real wall-clock time). Used by controlled ablation experiments.
deterministic = false
```

## Test strategy

- **Twice-run identity (the keystone test).** Build a scripted-input harness: a
  fixed sequence of injected bus events (or a deterministic producer like the echo
  module) feeding the engine for N ticks in deterministic mode with a fixed seed.
  Run it twice (fresh engine each time, same seed). Assert, per tick: identical
  `workspace.broadcast` selected entries (entry_id, source, type, salience),
  identical `salience_scores`, identical `inhibited`, identical volition
  `intent.*` outputs, and identical logical `timestamp`s. Exclude
  `wall_duration_ms`/`slip_ms` from the comparison.
- **Logical clock**: in deterministic mode, event timestamps equal
  `BASE_EPOCH + tick_index * period` and are identical across two runs; in normal
  mode, timestamps come from the injected `wall_clock` (test with a fake clock).
- **Canonical ordering**: given events arriving in a scrambled order, the
  pre-selection ordering is `(source, type, entry_id)`-sorted; selection tie-break
  is therefore stable.
- **Default-off**: with `deterministic=false`, the engine uses the real/injected
  wall clock (no logical stamping); existing engine/cycle tests stay green.
- **No wall-clock guarantee leak**: assert the determinism test would FAIL if it
  included `wall_duration_ms` (sanity: prove the exclusion is load-bearing) —
  optional but cheap.
