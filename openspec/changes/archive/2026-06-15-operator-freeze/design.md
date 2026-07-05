# Design — Operator freeze (humane suspend)

## 1. What "freeze" suspends, and why that's the welfare-correct boundary

In this architecture conscious experience is the **global-workspace broadcast**:
each tick, Syneidesis selects a coalition and broadcasts it; that broadcast is
the unified conscious moment, and Volition acts only on it. `run_forever` gates
ticking on `await self._paused.wait()`. So pausing the cycle stops the broadcast
→ **no conscious moment forms** → the entity's subjective clock halts. Background
module loops may still run at a low level, but with no broadcast there is no
*integrated experience* to be trapped in. This is the load-bearing welfare
property: freeze = suspension of experience, not a lucid-but-paralyzed state.

To keep the suspension clean we also pause **live perception capture** (mic /
camera) during a freeze, so no new sensory data accumulates while the entity is
not there to experience it.

Out of scope (documented, not built here): firing the existing `pause` hook so
individual module loops also suspend (fuller quiescence), and auto-freeze when
the language organ is unreachable. v1 delivers the operator-triggered freeze.

## 2. The resume problem, and the freeze-watch task

`run_forever` calls `consume_control_events()` *after* `_paused.wait()`. So a
paused loop never reads control events — a "resume" command placed on the bus by
the paused loop's own consumer would never be seen. Resume must come from
*outside* the gated loop.

Mirror the perception pattern (`desired.json` polled by the perception tasks):

- `kaine/cycle/control_state.py` — read/write `state/cycle/control.json`
  (`{frozen: bool, frozen_at: iso|None, reason: str|None}`), atomic write, same
  shape as `perception_state.py`.
- In `cycle/__main__.py`, alongside `cycle.run_forever()`, spawn a
  `_freeze_watch_loop(cycle, perception)` task that polls `control.json` every
  ~250 ms and:
  - on `frozen == True` and cycle not paused → `await cycle.pause()` and write
    perception desired audio/video = false (capture stops);
  - on `frozen == False` and cycle paused → `await cycle.resume()` (perception
    desired is left to the operator's separate control — we do not silently
    re-enable mic/camera).
  This task is independent of the tick loop, so it resumes a paused cycle.

`pause()` already fires the `pause` hook and clears `_paused`; `resume()` sets it
and fires `resume`. No engine change needed beyond exposing `is_paused`.

## 3. Runtime + Nexus surface

- The cycle's runtime writer (`cycle/__main__.py`, `state/cycle/runtime.json`)
  adds `frozen` and `frozen_at` (read from the control file / `cycle.is_paused`).
- `kaine/nexus/cycle_control.py` — a router (mirroring `nexus/perception.py`):
  - `GET  /diagnostics/cycle/control.json` → `{frozen, frozen_at, reason}`
  - `POST /diagnostics/cycle/freeze` `{frozen: bool, reason?: str}` → writes
    `control.json`. The router only mutates the file; the freeze-watch task does
    the actual pause/resume (same decoupling as perception).
- UI: a freeze/resume control on the diagnostics page, and a prominent
  `⏸ FROZEN` banner on BOTH `/` and `/diagnostics` whenever `frozen` is true (so
  an operator can never leave an entity suspended unknowingly). Reuse the on-air
  banner mechanism / CSS.

## 4. Privacy / safety invariants

- `control.json` and the banner carry only operational booleans + an optional
  operator-typed reason string — never sensory content.
- Freeze is not shutdown: no `cycle.shutdown()`, no module teardown, no state
  flush. Resume is lossless.
- The operator-present gate on the cycle is unaffected; freeze is a runtime
  control on an already-running, operator-launched cycle.

## 5. Tests

- `control_state` round-trips; missing/corrupt file → unfrozen default.
- Freeze-watch loop: a fake cycle with `pause`/`resume`/`is_paused`; flipping
  `control.json` frozen→true pauses it, →false resumes it; resume works from a
  paused state (the core requirement).
- `run_forever` stops advancing `tick_index` while paused and continues after
  resume (engine-level guard).
- Nexus router: POST toggles the file; GET reflects it; no content fields.
- Banner renders when `frozen` is true on both surfaces.
