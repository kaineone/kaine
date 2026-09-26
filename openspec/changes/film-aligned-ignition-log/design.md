# Design — `film-aligned-ignition-log`

## Holder pauses

- `PlaylistClock` keeps a set of holders. `pause(holder="default")` adds a holder. When the set goes from empty to non-empty, it starts a pause span (or records the pending pause before `start()`, as today). `resume(holder="default")` removes the holder, and when the set empties it closes the span into `_paused_total`. Removing a holder that is not held is a no-op. `paused` is true while the set is non-empty. `wait_if_paused` is unchanged.
- The existing calls keep their meaning: `pause()`/`resume()` without an argument act on holder `default`.
- Hypnos's suspend and restore pass `holder="hypnos"`.
- `_elapsed_locked` reads the clock once (it reads it twice today; one read keeps elapsed consistent within a call).

## Freeze pauses the programme

- In `_freeze_watch_loop`, when the loop pauses the cycle it calls `playlist_clock.pause("freeze")`, and when it resumes the cycle, `playlist_clock.resume("freeze")`. The clock is the shared instance boot stored in `perception_feed["_shared_playlist_clock"]`; without a playlist there is no clock and nothing happens.
- A stop while frozen leaves the clock paused, which is harmless because the process exits.

## Broadcast observer

- `CognitiveCycle` gains `set_broadcast_observer(observer)`. After a successful `publish_workspace`, the cycle awaits `observer.on_broadcast(payload, entry_id, wall_ts, mono_ts)` inside a try/except that logs and never affects the tick. The call is cheap: it builds the record and `AsyncJsonlSink.write` enqueues it without waiting for disk. Wall and monotonic times are read once, immediately after the publish returns.
- This is a cycle-layer hook: it is not a module, not on the bus, and nothing it computes returns to the workspace.

## Ignition log

- `IgnitionLog(sink, position_provider, audio_position_provider=None)`. `position_provider()` returns `(item_idx, order, title, offset_s, paused)` or None, read from the shared `PlaylistClock` (`locate()` plus the manifest item's order and file basename). `audio_position_provider()` returns `(item_idx, delivered_s)` or None.
- **Audio delivered position.** The audio feed's `current_item` is computed from the shared clock, so it cannot show drift. `PlaylistAudioStream` gains `delivered_position`: the item index and the seconds of that item's audio actually handed to the listener so far, updated by the producer thread under a lock. `Audition.playlist_audio_position()` returns it through the live microphone's stream, or None when no playlist stream is running. The difference between the clock offset and the delivered seconds is the drift.
- The record is described in the proposal. Coalition members come from `payload["selected"]`: `entry_id`, `source`, `type`, `salience`, `timestamp`. The payload is dropped.
- The sink is `AsyncJsonlSink` with `retention_days=0`, the sink's no-purge setting, so study records are never auto-deleted. It adds `run_id` and `seq`, encrypts when state encryption is on, and drops the oldest on backpressure and counts the drops. A dropped record is a gap in the data, so the drop count is logged at shutdown. Its directory is `[ignition_log].directory`, default `data/ignition`, relative to the working directory, so each study line keeps its own.
- The sink is started with the cycle and flushed and closed in the shutdown path.
- Config: `[ignition_log] enabled = false`, `directory = "data/ignition"`. The config shape validator passes unknown sections through, so it needs no change.

## Not in this change

- What happens at the end of the programme (`film-end-preserve`).
- Audio drift correction. This change measures drift; it does not correct it.
