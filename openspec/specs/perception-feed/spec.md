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
