## ADDED Requirements

### Requirement: A viewing after birth opens with the womb-to-world transition
When `[perception_feed].transition_seconds` is above zero, the mode is `playlist`, the being's stage is embodied with `womb_t_at_birth`, the womb seed and the womb parameter digest recorded, and the configured womb parameters have the recorded digest, the feed SHALL open with a crossfade lasting `transition_seconds`:
- video: from the womb's bloom-peak field rendered at `womb_t_at_birth` to the programme's first frame, held still;
- audio: silence for the whole crossfade, as the bloom ended in silence; once programme time starts, the programme's sound fades in linearly over `[perception_feed].transition_audio_fade_seconds` (0 means no fade).

The crossfade SHALL be a deterministic function of the womb seed, the womb parameters, `womb_t_at_birth`, the being's lived time and the fade curve. No transition frame or sample SHALL be written to storage. The playlist clock SHALL be paused under the holder `transition` before either surface reads it, and the holder SHALL be released exactly once when the crossfade ends, even when only one surface is reading, so programme time zero is the end of the transition. The run manifest SHALL record `transition_seconds`, `transition_audio_fade_seconds` and whether the transition is active.

#### Scenario: Two runs from one seed see the same transition
- **WHEN** two viewings revive the same seed with the same transition settings
- **THEN** their transition frames at the same point of the crossfade are identical
- **AND** their programme sound fades in with the same gain at each sample

#### Scenario: Film time begins after the fade
- **WHEN** a viewing's transition has run for its full length
- **THEN** the programme's first frame starts playing
- **AND** the ignition log's film position for it is zero

#### Scenario: The programme's sound fades in after the crossfade
- **WHEN** a viewing's transition is running
- **THEN** no programme sound is heard
- **AND** when programme time starts, the sound rises from silence to full level over `transition_audio_fade_seconds`

#### Scenario: No recorded birth state
- **WHEN** a playlist viewing starts for a being without `womb_t_at_birth`, or whose womb parameters no longer match the recorded digest
- **THEN** no transition is rendered, the programme starts as before, and the boot log says why
