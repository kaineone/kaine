## ADDED Requirements

### Requirement: A viewing after birth opens with the womb-to-world transition
When `[perception_feed].transition_seconds` is above zero, the mode is `playlist`, and the being's stage is embodied with a recorded `womb_t_at_birth`, the feed SHALL open with a crossfade lasting `transition_seconds`:
- video: from the womb's bloom-peak field rendered at `womb_t_at_birth` to the programme's first frame, held still;
- audio: the programme's sound fades in from silence.

The crossfade SHALL be a deterministic function of the womb seed, the womb parameters, `womb_t_at_birth` and the fade curve. No transition frame or sample SHALL be written to storage. The playlist clock SHALL start paused under the holder `transition` and be released when the crossfade ends, so programme time zero is the end of the transition.

#### Scenario: Two runs from one seed see the same transition
- **WHEN** two viewings revive the same seed with the same transition settings
- **THEN** their transition frames and samples are identical

#### Scenario: Film time begins after the fade
- **WHEN** a viewing's transition has run for its full length
- **THEN** the programme's first frame starts playing
- **AND** the ignition log's film position for it is zero

#### Scenario: No recorded birth state
- **WHEN** a playlist viewing starts for a being without `womb_t_at_birth`
- **THEN** no transition is rendered, the programme starts as before, and the boot log says why
