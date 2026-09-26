## 1. Implementation

- [x] 1.1 `PlaylistClock` holder pauses; Hypnos uses holder `hypnos`; `_elapsed_locked` reads the clock once.
- [x] 1.2 The freeze-watch loop holds the programme clock under `freeze` while the cycle is paused.
- [x] 1.3 `CognitiveCycle.set_broadcast_observer` and the in-process call after a successful broadcast.
- [x] 1.4 `PlaylistAudioStream.delivered_position` and `Audition.playlist_audio_position()`; `kaine/cycle/ignition_log.py`, `[ignition_log]` config (shipped disabled), wiring in the cycle entrypoint with sink start and close.
- [x] 1.5 `docs/operations.md`: the ignition log, what it holds and what it never holds.

## 2. Verification

- [x] 2.1 Tests: overlapping holders (freeze during a Hypnos pause and the reverse) keep the clock paused until both release; elapsed excludes every paused span; no-argument calls still work; a freeze pauses the clock and a thaw resumes it; the observer is called once per successful broadcast and never on a failed one, and an observer error does not break the tick; a record carries position, audio position, member ids and timestamps, and no payload; the log is off by default; nothing the observer writes reaches the bus.
- [x] 2.2 Offline suite green; `openspec validate film-aligned-ignition-log --strict`.
