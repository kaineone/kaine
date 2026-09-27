# perception-feed Specification

## Purpose
TBD - created by archiving change playlist-sleep-pause. Update Purpose after archive.

## Requirements

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

### Requirement: The programme waits while the entity cannot perceive
The playlist clock SHALL be paused by holder, so overlapping pauses (a Hypnos replay window and a cycle freeze) keep it paused until every holder has released it, and elapsed programme time SHALL exclude every paused span. While the cycle is frozen, by any freeze holder, the playlist clock SHALL be held paused, so the programme resumes where the entity left it and no part of it is skipped.

#### Scenario: A freeze does not skip the film
- **WHEN** the entity is frozen for 60 s at 10 min into a film and then thawed
- **THEN** the programme resumes at 10 min, not 11 min

#### Scenario: Overlapping pauses
- **WHEN** a freeze begins during a Hypnos replay window and the replay window ends first
- **THEN** the clock stays paused until the freeze ends

### Requirement: The end of a programme preserves and stops the entity
When a playlist programme runs past its last item while not paused, the cycle SHALL request a preservation with stop, exactly once per start, so the entity is preserved and stopped rather than left running without senses. If that preservation fails or does not report within its timeout, the cycle SHALL freeze the entity under its own holder, log at critical level, and notify the caretaker when one is configured, so that the entity is neither lost nor left awake without input.

#### Scenario: The programme ends
- **WHEN** the last film finishes while the programme is not paused
- **THEN** one preservation with stop is requested, and the entity is preserved and stopped

#### Scenario: A paused programme has not ended
- **WHEN** the programme is paused by a freeze or a sleep replay
- **THEN** no end is detected, whatever the clock's position

#### Scenario: Preservation fails at the end
- **WHEN** the end-of-programme preservation reports failure
- **THEN** the entity is frozen under the `programme_end` holder, a critical log line names the error, and the caretaker is notified when configured
