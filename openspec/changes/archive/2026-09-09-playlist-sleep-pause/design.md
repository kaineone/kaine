# Design: playlist-sleep-pause

## Context

`PlaylistClock` is the single position authority for both playlist feeds. It computes elapsed time as `clock() - origin`. Sleep must freeze that elapsed value without disturbing A/V sync after wake.

## PlaylistClock pause/resume

Add to `PlaylistClock`:

- `pause()`: under `self._lock`, if `self._origin is not None` and not already paused, record `self._pause_started = self._clock()`. If not started, record a pending pause flag so the clock is *born paused* (origin is set but frozen — see failure modes). Idempotent: a second `pause()` while paused is a no-op.
- `resume()`: under `self._lock`, if paused, add `self._clock() - self._pause_started` to `self._paused_total` and clear `_pause_started`. Idempotent no-op when not paused.
- `_elapsed_locked()` becomes `max(0.0, clock() - origin - paused_total - current_pause_delta)` where `current_pause_delta` is `clock() - _pause_started` while paused, else 0.

This accumulated-offset approach means `locate()` freezes exactly while paused (elapsed is constant during a pause), and on resume elapsed continues from the pre-pause value with sub-millisecond error (one clock read). No re-origin, no content skipping.

`started`/`paused` exposed as properties for callers and tests.

### Failure modes

- **Pause before origin fixed:** with no origin, `elapsed()` is already 0. Pause sets the paused flag with `_pause_started = None`; nothing accumulates because there is no origin to measure against. The precise born-paused rule: **when `start()` fixes the origin while the clock is paused, it also sets `_pause_started = origin`** — then `elapsed = clock - origin - paused_total - (clock - _pause_started) = 0` exactly, for as long as the pause holds. `resume()` with `_pause_started = None` (origin still unset) just clears the flag. No negative elapsed, no content skipped; `start()` stays idempotent.
- **Pause exactly at an item boundary:** no special case. `locate()` returns the same `(idx, offset)` it returned at pause time; both feeds re-present their last frame/block boundary. The video source's HOLD branch (`target_media_frame <= _last_media_frame`) naturally re-presents the current frame while paused; no frame advance occurs because elapsed is frozen.
- **Wake after a feed died:** the clock resumes regardless. The surviving feed keeps its position; the dead feed's absence is unchanged pre-existing behavior (the shared clock never resurrected feeds). No pretend success: if the audio thread already exited via `log.exception("playlist audio producer crashed")`, resume does not fake audio; the crash path is untouched.
- **Double pause / double resume:** both idempotent no-ops (guarded by `_pause_started is not None`).

## Who calls pause/resume

Hypnos is the sole sleep authority, and it already owns the exact right seam: `_suspend_perception()` / `_restore_perception()`. The clock pause lives INSIDE those two methods — pause after writing locus `"off"`, resume before/with the locus restore. This buys two properties for free:

1. **Exception safety.** `phases.deep_consolidation` invokes `suspend_perception` and calls `restore_perception` from a `finally` ("Always restore perception (even on error)"). Co-locating the clock calls means a replay crash can never leave the clock frozen after perception returns.
2. **The invariant "clock paused ⇔ perception suspended".** The stimulus can never advance while the entity cannot perceive it, and can never stay frozen while perception is live. If the suspension window later widens (e.g. whole-pipeline sleep), the pause follows automatically.

The clock reaches Hypnos the same way it reaches the feeds: boot builds it once and stashes it in `perception_feed["_shared_playlist_clock"]`; boot passes it into the Hypnos module factory alongside the existing `perception_desired_path`. Rationale: no new bus/event channel for a single consumer; the injected-clock pattern is already the project's established mechanism (same as test injectability with `_FakeClock`).

Hypnos wraps the calls defensively (try/except + log) so a missing clock in non-playlist modes is a no-op, not a crash. Sleep pause applies only when a shared clock exists.

## Locus restore fix

`_suspend_perception()`: before writing `"off"`, read the current desired locus via `perception_state.read_desired_locus(path=...)` (or `read_desired` — whichever the module already has access to). If the read fails or yields an unknown value, coerce via the existing `_coerce_locus` default (`physical`). Store the remembered locus **in memory on the Hypnos module** (`self._pre_sleep_locus`), not on disk — the value must survive only across one sleep window within one process, and keeping it off disk avoids inventing a new state file. If the process dies mid-sleep, the operator's desired.json still reads `"off"`, which is honest (perception was suspended).

`_restore_perception()` writes the remembered value, falling back to `"physical"` only if nothing was remembered (e.g., suspend never ran — preserving old behavior defensively). Only the locus string is ever persisted; zero raw-sense-data preservation is untouched.

Note: the desired locus may legitimately change during sleep (operator toggle). On restore, if the remembered locus is stale we still write it — the perception tasks poll desired.json and the operator can re-command. This is the honest minimal fix; conflict policy between Hypnos restore and operator commands is out of scope (see non-goals).

## Audio producer parking

The producer loop's `_emit` pacing and the decode loop already gate on `self._stopped`. Add a `self._paused` `threading.Event` (clear = paused) held by `PlaylistAudioStream`:

- In `_emit`, before computing `sleep_for`, wait on `not self._paused` with a bounded loop that also checks `_stopped` (so stop still wins and shutdown never hangs). While paused, do not advance `next_deadline`; on resume, re-anchor `next_deadline = time.monotonic()` so pacing continues cleanly without a burst of back-to-back blocks.
- In the frame-decode loop, check `self._paused` between frames (per-frame, not per-block, is enough — decode granularity is coarse) and wait similarly. This is what actually idles the decoder: no PyAV frame iteration while asleep, freeing CPU/RAM for Hypnos consolidation.

The pause event is set/cleared by the same Hypnos path that calls clock pause/resume (or the stream derives it from the clock's `paused` property — **decision: pass the clock's pause state explicitly via a small `wait_if_paused()` helper on `PlaylistClock`** so there is one pause authority; the audio stream already holds the shared clock and can call `clock.wait_if_paused(stop_check)` in its loops). This avoids a second flag that could disagree with the clock. The wait is event-based inside the clock (an internal `threading.Event` flipped in `pause()`/`resume()`), so there is no busy-wait.

Video side needs no change beyond the clock: `PlaylistSource.read()` derives position from `locate()`, which is frozen while paused, so it re-presents the held frame and never advances the decoder cursor.

## Thread-safety

- All `PlaylistClock` mutations happen under `self._lock`; `paused` is read by feeds on every read/emit, so the property also locks.
- The internal pause Event is set/cleared while holding the lock; `Event.wait` is called *without* the lock (never wait on a lock you might need).
- `_emit` callbacks run on the producer thread only; `_paused`/clock checks on that thread are consistent.

## Non-goals

- Deterministic frame-for-frame resume; the playlist tier stays reproducible-by-sha256+seed only.
- Pausing playback for anything other than Hypnos sleep (operator pause is a separate future change).
- Re-architecting locus authority or resolving operator-vs-Hypnos locus command races.
- Frame-accurate A/V resume: residual sub-second skew at resume matches the existing live-tier tolerance.
- Persisting remembered locus to disk.

## Testing approach (detail for tasks)

Use the existing `_FakeClock` pattern from `tests/test_topos_feed.py` — an injectable monotonic fake advanced manually. Pause/resume unit tests advance the fake clock inside a pause and assert `locate()` is frozen; resume and assert continuation from the pause point. Locus tests stub `perception_state` paths. No real sleep, no real time in tests.
