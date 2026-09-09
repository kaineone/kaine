## Why

PR #80 gave video and audio one shared wall-clock (`PlaylistClock`), so picture and sound cross item boundaries together. But the clock is blind to sleep: when Hypnos suspends perception, `PlaylistClock` keeps advancing on `time.monotonic()`, so on wake the playlist has skipped minutes of content. The operator wants stimulus playback to behave like pausing a movie — freeze at sleep onset, resume at the exact pause point on wake.

Two adjacent defects make sleep actively harmful today:

1. **Locus restore bug.** `Hypnos._restore_perception()` hardcodes locus `"physical"` on wake. Playlist/seeded runs select the VIRTUAL locus at boot (`select_virtual_feed()`); after the first sleep the entity is flipped to physical camera/mic and the playlist feed goes permanently dark.
2. **Wasted decode during sleep.** The audio producer thread keeps decoding/pacing blocks (and the video source keeps advancing) while the entity sleeps, burning CPU/RAM that Hypnos consolidation work needs.

## What Changes

- `PlaylistClock` gains `pause()` / `resume()` implemented as an accumulated-pause offset against the monotonic origin, so `locate()` freezes while paused and resumes exactly where playback stopped. Thread-safe (the clock is read from multiple threads).
- Hypnos drives pause/resume from inside its existing `_suspend_perception()` / `_restore_perception()` seam (which the sleep pipeline already pairs in a `finally`), using the same shared clock instance boot already builds — no new wiring channel, and the invariant "clock paused ⇔ perception suspended" holds even when a replay crashes.
- `Hypnos._suspend_perception()` records the currently active desired locus before writing `"off"`; `_restore_perception()` restores that recorded value instead of hardcoding `"physical"`. Only the locus flag is persisted (zero raw-sense-data persistence preserved).
- The audio producer's pacing loop parks on a pause flag/event (no busy-wait, no dropped or duplicated blocks) and the video source stops advancing while the clock is paused; decoders idle during sleep.
- Failure modes handled honestly: idempotent double pause/resume, pause before playback origin is fixed, and wake after a feed thread died.

## Impact

- **Code:** `kaine/modules/topos/feed.py` (`PlaylistClock`, `PlaylistSource.read`), `kaine/modules/audition/feed.py` (producer loop), `kaine/modules/hypnos/module.py` (suspend/restore locus), `kaine/boot.py` (no structural change — the already-injected shared clock is reused; possibly clock injection into Hypnos).
- **Docs:** `docs/` references to sleep behavior and perception locus restore updated (present tense).
- **State:** `desired.json` may carry a remembered-locus field — flags only, never sensory content.
- **Non-goals:** deterministic frame-for-frame playback; pausing for reasons other than Hypnos sleep; changing `LOCI` semantics or the Nexus operator lock; any change to the virtual/physical privacy mutual-exclusion guarantee.
