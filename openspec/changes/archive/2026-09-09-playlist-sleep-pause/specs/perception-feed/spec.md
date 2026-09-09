## ADDED Requirements

### Requirement: Playlist clock pause during sleep

The shared playlist clock (`PlaylistClock`) SHALL support pausing and resuming elapsed-time accounting so that playback position freezes at sleep onset and resumes at the exact pause point on wake. Pause and resume SHALL be idempotent and thread-safe.

#### Scenario: Pause at sleep start freezes position

- **GIVEN** playlist playback is running with the shared clock started and positioned at item 2, offset 12.5s
- **WHEN** Hypnos sleep starts and calls `clock.pause()`
- **THEN** subsequent `locate()` calls return `(2, 12.5)` regardless of wall-clock advancing, and `paused` reports `True`

#### Scenario: Position frozen while asleep

- **GIVEN** the clock is paused at item 0, offset 30.0s
- **WHEN** 45 minutes of monotonic time pass while paused
- **THEN** `elapsed()` still equals 30.0s and `locate()` returns the pause-time `(item, offset)`

#### Scenario: Resume at exact pause point on wake

- **GIVEN** the clock is paused at item 1, offset 8.0s
- **WHEN** Hypnos sleep completes and calls `clock.resume()`, then 2s of monotonic time pass
- **THEN** `elapsed()` equals 10.0s and `locate()` returns item 1 at offset 10.0s — playback continues from the pause point with no content skipped

#### Scenario: Idempotent double pause

- **GIVEN** the clock is paused
- **WHEN** `pause()` is called again
- **THEN** the call is a no-op: the frozen position is unchanged, and a subsequent single `resume()` clears the pause

#### Scenario: Idempotent double resume

- **GIVEN** the clock is not paused
- **WHEN** `resume()` is called
- **THEN** the call is a no-op and elapsed time continues accumulating normally

#### Scenario: Sleep starts before playback origin is fixed

- **GIVEN** the shared clock exists but no feed has called `start()` (origin is unset)
- **WHEN** `pause()` then `resume()` are called before the first feed read
- **THEN** the clock does not crash; when the first feed read fixes the origin, playback begins at position 0 (no content skipped, no negative elapsed)

#### Scenario: Wake after a feed thread died

- **GIVEN** the clock is paused and the audio producer thread has already exited via its crash path
- **WHEN** `resume()` is called
- **THEN** the clock resumes honestly (the surviving video feed keeps its position); no audio is faked — the existing dead-feed behavior is unchanged

### Requirement: Sleep-driven decoder idling

While the shared playlist clock is paused, the audio producer thread SHALL park on the clock's pause state instead of decoding or pacing blocks, and the video source SHALL NOT advance its decoder cursor. Parking SHALL be event-based (no busy-wait) and stop/shutdown SHALL still win over the pause wait.

#### Scenario: Audio producer parks while paused

- **GIVEN** the audio producer thread is mid-item, pacing blocks
- **WHEN** the shared clock pauses
- **THEN** the producer stops decoding frames and stops emitting blocks, waiting without busy-waiting, and no blocks are dropped or emitted while paused

#### Scenario: Producer resumes cleanly without a burst

- **GIVEN** the producer is parked while paused
- **WHEN** the clock resumes
- **THEN** the producer resumes decode/pace at the pause-point position, re-anchoring its pacing deadline so no back-to-back burst of blocks is emitted

#### Scenario: Stop wins over pause wait

- **GIVEN** the producer thread is parked waiting for the pause to clear
- **WHEN** the stream is stopped (`_stopped` set)
- **THEN** the producer exits promptly instead of hanging on the pause wait

#### Scenario: Video source holds frame while paused

- **GIVEN** the video source is presenting frames from item 3
- **WHEN** the shared clock pauses and `read()` is called repeatedly
- **THEN** the source re-presents the same held frame and never advances the item index or decoder cursor while paused

## ADDED Requirements

### Requirement: Perception locus restore after sleep

Hypnos sleep SHALL restore the entity's desired locus to the value that was active immediately before sleep, not a hardcoded value. Only locus flags are persisted — never any sensory content.

#### Scenario: Restore returns to pre-sleep locus

- **GIVEN** the desired locus is `virtual` (selected at boot via `select_virtual_feed()`)
- **WHEN** Hypnos sleep starts (locus written `off`) and later sleep completes
- **THEN** the desired locus is restored to `virtual`, and the playlist/virtual feed continues rather than going permanently dark

#### Scenario: Restore after pre-sleep physical locus

- **GIVEN** the desired locus is `physical` before sleep
- **WHEN** sleep completes
- **THEN** the desired locus is restored to `physical`

#### Scenario: Restore with no remembered locus

- **GIVEN** sleep completes without `_suspend_perception()` having recorded a pre-sleep locus (e.g., suspend never ran)
- **WHEN** `_restore_perception()` executes
- **THEN** the locus is restored to `physical` (honest defensive fallback matching pre-existing behavior)

#### Scenario: Replay crash still restores clock and locus

- **GIVEN** the clock is paused and locus is `off` because a sleep replay window is open
- **WHEN** the replay raises an exception mid-window
- **THEN** the pipeline's existing `finally` path restores perception AND resumes the clock together — perception and playback can never come back separately

#### Scenario: No sensory content persisted

- **GIVEN** a full sleep cycle (suspend and restore) in playlist mode
- **WHEN** the perception state files are inspected
- **THEN** they contain only locus flags and operational metadata — no frames, audio bytes, or transcribed text
