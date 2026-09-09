## 1. PlaylistClock pause/resume

- [x] 1.1 Add `pause()` to `PlaylistClock`: under `self._lock`, handle both started (record `_pause_started = clock()`) and unstarted (pending-pause flag + `_pause_started` sentinel) cases; idempotent while paused; set an internal `threading.Event` flipped in `pause()`/`resume()`
- [x] 1.2 Add `resume()` to `PlaylistClock`: under `self._lock`, accumulate `clock() - _pause_started` (or a resume-time clock read for the born-paused case) into `_paused_total`; clear pause state; idempotent when not paused
- [x] 1.3 Update `_elapsed_locked()` to subtract `_paused_total` plus the in-progress pause delta; verify `locate()` freezes exactly while paused
- [x] 1.4 Expose `started` and `paused` properties (locking); add a `wait_if_paused(stop_check)` helper that waits on the internal event WITHOUT holding `self._lock` and returns promptly when the stop check passes
- [x] 1.5 Confirm `start()` remains idempotent and unchanged; verify first-writer duration registration is unaffected by pauses

## 2. Audio producer parking

- [x] 2.1 In `PlaylistAudioStream._emit`, wait via `clock.wait_if_paused(stop_check=self._stopped.is_set)` before computing `sleep_for`; while paused do not advance `next_deadline`
- [x] 2.2 On resume within `_emit`, re-anchor `next_deadline = time.monotonic()` so no burst of back-to-back blocks is emitted
- [x] 2.3 Add a per-frame pause check in the container decode loop (between frames, including before the first block of each item) via the same `wait_if_paused` helper so decoders truly idle
- [x] 2.4 Verify stop still wins: stopping the stream while parked exits the producer promptly; verify the crash path is untouched (no faked audio after a crash)

## 3. Video source behavior under pause

- [x] 3.1 Confirm (and add a guard if needed) that `PlaylistSource.read()` re-presents the held frame via the existing HOLD branch while `locate()` is frozen — no decoder cursor advance, no item advance
- [x] 3.2 Confirm `_advance_item()` cannot fire while paused (target index cannot move while elapsed is frozen)

## 4. Hypnos locus fix

- [x] 4.1 In `_suspend_perception()`, read the current desired locus (via `perception_state.read_desired_locus`/equivalent, coercing unknown values with `_coerce_locus`) and store it in memory on the module as `self._pre_sleep_locus` before writing `"off"`
- [x] 4.2 In `_restore_perception()`, write `self._pre_sleep_locus` instead of hardcoded `"physical"`, falling back to `"physical"` when nothing was remembered; clear the remembered value after restore
- [x] 4.3 Audit both paths: only locus flags are written — no sensory content, zero raw-sense-data persistence preserved

## 5. Boot wiring

- [x] 5.1 Pass the existing `perception_feed["_shared_playlist_clock"]` instance (when present) into the Hypnos module factory alongside `perception_desired_path`; no new bus/event channel
- [x] 5.2 Call `clock.pause()` inside `_suspend_perception()` (after writing locus `off`) and `clock.resume()` inside `_restore_perception()` — co-located so the pipeline's existing `finally` restore covers both; defensive try/except + log so missing clocks in non-playlist modes are honest no-ops
- [x] 5.3 Verify non-playlist modes (physical, seeded without shared clock) are unchanged
- [x] 5.4 Exception-safety test: replay raises mid-window → clock resumed AND locus restored together via the existing `finally` (spec scenario "Replay crash still restores clock and locus")

## 6. Tests

- [x] 6.1 `PlaylistClock` pause/resume unit tests with the `_FakeClock` pattern: freeze during pause across a manual clock advance; resume continuation from the exact pause point; pause at an item boundary; idempotent double pause and double resume
- [x] 6.2 Born-paused test: pause before `start()`, resume before first read, then first read fixes origin at position 0 with no negative elapsed
- [x] 6.3 Audio producer parking test with a fake clock: no blocks emitted during pause, no dropped/duplicated blocks across the pause boundary, no burst on resume, stop wins while parked
- [x] 6.4 Video source test: `read()` re-presents the held frame and does not advance the item or decoder cursor while paused
- [x] 6.5 Locus tests: pre-sleep `virtual` restored on wake; pre-sleep `physical` restored; fallback to `physical` when nothing was remembered; state files contain flags only
- [x] 6.6 Integration-style test: Hypnos sleep start → clock paused + locus `off`; sleep complete → clock resumed at pause point + locus restored; a run without an injected clock is a no-op, not a crash

## 7. Documentation

- [x] 7.1 Update `PlaylistClock` docstring to describe pause/resume, the accumulated-pause offset, and the `wait_if_paused` helper (present tense)
- [x] 7.2 Update `docs/` sleep-behavior and perception-locus-restore references: playback pauses at sleep onset and resumes at the pause point; locus restored to pre-sleep value (present tense)
- [x] 7.3 Note in the docs that remembered locus lives in memory only and dies with the process (honest: desired.json reads `off` after a mid-sleep crash)
