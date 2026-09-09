## ADDED Requirements

### Requirement: Thesis-test module set

The system SHALL provide an opt-in run configuration that enables exactly the
diverse predictive processors the base thesis needs — Soma, Chronos, Topos,
Audition — plus the always-on Syneidesis and Volition, and Lingua as the output-
only voice. Every other module (Mnemos, Eidolon, Thymos, Phantasia, Empatheia,
Nous, Vox, Hypnos, Praxis, Perception, Mundus) SHALL remain built and disabled.
The configuration SHALL NOT remove or delete any module.

#### Scenario: Only the thesis processors activate

- **WHEN** the thesis-test configuration is selected at boot
- **THEN** exactly Soma, Chronos, Topos, Audition, and Lingua are registered,
  Syneidesis and Volition run as scaffolding, and every other module is disabled
  but present

### Requirement: Raw audio-visual perception, no transcript

The thesis-test configuration SHALL feed Topos and Audition from a raw audio-
visual source (a live screen/monitor capture or a deterministic seeded/playlist
feed), with Topos foveation enabled (precision-weighted attention) and Audition
transcription disabled. Perception SHALL enter the workspace only as prediction
error, never as transcribed text.

#### Scenario: Audio enters as prediction error only

- **WHEN** the thesis-test configuration is active and audio is present
- **THEN** Audition publishes `audition.perception` (and affect signals) but not
  `audition.transcription`

#### Scenario: Vision is foveated

- **WHEN** the thesis-test configuration is active
- **THEN** Topos runs with its arousal-sized foveation enabled

### Requirement: Self-initiated voice, no chatbot trigger

The thesis-test configuration SHALL select the self-initiated report policy for
Volition and SHALL NOT enable any user-utterance / transcription speak trigger, so
the entity speaks only from its own state.

#### Scenario: Volition uses the report gate

- **WHEN** the thesis-test configuration is active
- **THEN** Volition's policy is the self-initiated report policy, and no
  user-utterance speak trigger is wired
