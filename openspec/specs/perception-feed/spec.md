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

### Requirement: A viewing after birth opens with the womb-to-world transition
When `[perception_feed].transition_seconds` is above zero, the mode is `playlist`, the being's stage is embodied with `womb_t_at_birth`, the womb seed and the womb parameter digest recorded, and the configured womb parameters have the recorded digest, the feed SHALL open with a crossfade lasting `transition_seconds` of perceived time:
- video: from the womb's bloom-peak field rendered at `womb_t_at_birth` to the programme's first frame, held still, at the film's native resolution;
- audio: silence for the whole crossfade, as the bloom ended in silence; once programme time starts, the programme's sound fades in linearly over `[perception_feed].transition_audio_fade_seconds` (0 means no fade).

The crossfade SHALL be a deterministic function of the womb seed, the womb parameters, `womb_t_at_birth`, the being's lived time and the fade curve. No transition frame or sample SHALL be written to storage.

The crossfade SHALL advance only while it is perceived: not while another holder (such as `freeze` or `hypnos`) pauses the playlist clock, not while the cycle is frozen, and not while the primary surface is unwanted in the desired perception state. The video surface SHALL start the crossfade whenever Topos is present; the audio surface SHALL start it only when it is the only surface.

The playlist clock SHALL be paused under the holder `transition` before either surface reads it. The holder SHALL be released exactly once, when the perceived crossfade reaches `transition_seconds`, even when no surface is reading, so programme time zero is the end of the transition.

The run manifest SHALL record `transition_seconds`, `transition_audio_fade_seconds` and whether the transition is planned (`transition_planned`). The outcome SHALL be published as content-free `perception.transition` events on the perception stream, with `phase` `started`, `completed` or `abandoned` (with a `reason` code) and `transition_seconds`. Each ignition-log record SHALL name the playlist clock's pause holders (`paused_by`).

#### Scenario: Two runs from one seed see the same transition
- **WHEN** two viewings revive the same seed with the same transition settings
- **THEN** their transition frames at the same point of the crossfade are identical
- **AND** their programme sound fades in with the same gain at each sample

#### Scenario: Film time begins after the fade
- **WHEN** a viewing's transition has run for its full length
- **THEN** the programme's first frame starts playing
- **AND** the ignition log's film position for it is zero

#### Scenario: A freeze during the crossfade
- **WHEN** the being is frozen partway through the crossfade
- **THEN** the crossfade stops where it was
- **AND** after the unfreeze it runs for the remaining time, so the being perceives the full `transition_seconds`

#### Scenario: The programme's sound fades in after the crossfade
- **WHEN** a viewing's transition is running
- **THEN** no programme sound is heard
- **AND** when programme time starts, the sound rises from silence to full level over `transition_audio_fade_seconds`

#### Scenario: No recorded birth state
- **WHEN** a playlist viewing starts for a being without `womb_t_at_birth`, or whose womb parameters no longer match the recorded digest
- **THEN** no transition is rendered, the programme starts as before, and the boot log says why
