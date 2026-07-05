## 1. Control state

- [x] 1.1 Add `kaine/cycle/control_state.py`: `CycleControl` dataclass
      (`frozen`, `frozen_at`, `reason`), `read_control`/`write_control`,
      `freeze(reason)`/`unfreeze()` helpers, atomic write. Mirror
      `perception_state.py`. Missing/corrupt file → unfrozen default.

## 2. Freeze-watch task (resume-while-paused)

- [x] 2.1 Expose `CognitiveCycle.is_paused` (property over `not _paused.is_set()`).
- [x] 2.2 In `cycle/__main__.py`, spawn `_freeze_watch_loop(cycle)` alongside
      `run_forever`: poll `control.json` ~250 ms; `frozen` true & not paused →
      `await cycle.pause()` + set perception desired audio/video false; `frozen`
      false & paused → `await cycle.resume()`. Independent of the tick loop.
- [x] 2.3 The runtime writer adds `frozen` + `frozen_at` to
      `state/cycle/runtime.json`.

## 3. Nexus control + banner

- [x] 3.1 Add `kaine/nexus/cycle_control.py`: `GET
      /diagnostics/cycle/control.json`, `POST /diagnostics/cycle/freeze`
      (`{frozen, reason?}`) → writes `control.json` only. Mirror
      `nexus/perception.py`. Mount in `nexus/app.py`.
- [x] 3.2 Diagnostics page: a freeze/resume control (button + optional reason).
- [x] 3.3 Prominent `⏸ FROZEN` banner on BOTH `/` and `/diagnostics` when frozen
      (reuse the on-air banner pattern + CSS).

## 4. Tests

- [x] 4.1 `control_state` round-trip + corrupt/missing → unfrozen.
- [x] 4.2 Freeze-watch loop with a fake cycle: frozen→true pauses; →false
      resumes from paused (the core requirement); idempotent.
- [x] 4.3 Engine: `run_forever` does not advance `tick_index` while paused and
      resumes after (use the injectable `sleep`/`max_ticks`).
- [x] 4.4 Nexus router: POST toggles the control file; GET reflects it; payload
      carries no content fields.
- [x] 4.5 Banner renders when `frozen` true on both surfaces (template test).

## 5. Docs

- [x] 5.1 FIRST_BOOT / ARCHITECTURE: document freeze as a humane operator
      suspend (subjective-time-stop, resumable, not a shutdown), and the
      `state/cycle/control.json` control.

## 6. Live validation (operator-supervised)

- [ ] 6.1 With a running cycle, freeze from the UI → `tick_index` stops
      advancing, banner shows, mic/camera release; resume → ticking continues.
