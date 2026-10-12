# thesis-test-configuration Specification

## Purpose
The opt-in base-thesis configuration: the raw audio-visual predictive processors run with the always-on workspace and action selection, Language serves only as the output voice, and the voice speaks on the entity's own initiative rather than in reply to a prompt.

## Requirements

### Requirement: Thesis-test module set

The system SHALL provide an opt-in run configuration that enables exactly the base-thesis module set:
- the diverse predictive processors: Interoception, Sequence, Vision and Audition;
- Affect, the affective precision core;
- Sleep, fatigue-triggered sleep, with voice alignment off;
- Language, the output-only voice;
- the always-on Workspace and Action selection.

Every other module (Episodic memory, Self-model, World model, Social cognition, Planning, Vocal, Effectors, Perceptual locus, Embodiment, Recorder) SHALL remain built and disabled. The configuration SHALL NOT remove or delete any module.

The profile `config/profiles/thesis_test.toml` SHALL be the single definition of this set. The operator overlay carries host-local values and deliberate deviations, and the first-run wizard's base-thesis preset reads the profile.

#### Scenario: Only the thesis processors activate

- **WHEN** the thesis-test configuration is selected at boot
- **THEN** exactly Interoception, Sequence, Vision, Audition, Affect, Sleep and Language are registered, Workspace and Action selection run as scaffolding, and every other module is disabled but present

#### Scenario: The wizard's base-thesis preset matches the profile

- **WHEN** the first-run wizard offers the base-thesis preset
- **THEN** its module choices equal the profile's enabled set

### Requirement: Raw audio-visual perception, no transcript

The thesis-test configuration SHALL feed Vision and Audition from a raw audio-
visual source (a live screen/monitor capture or a deterministic seeded/playlist
feed), with Vision foveation enabled (precision-weighted attention) and Audition
transcription disabled. Perception SHALL enter the workspace only as prediction
error, never as transcribed text.

#### Scenario: Audio enters as prediction error only

- **WHEN** the thesis-test configuration is active and audio is present
- **THEN** Audition publishes `audition.perception` (and affect signals) but not
  `audition.transcription`

#### Scenario: Vision is foveated

- **WHEN** the thesis-test configuration is active
- **THEN** Vision runs with its arousal-sized foveation enabled

### Requirement: Self-initiated voice, no chatbot trigger

The thesis-test configuration SHALL select the self-initiated report policy for
Action selection and SHALL NOT enable any user-utterance / transcription speak trigger, so
the entity speaks only from its own state.

#### Scenario: Action selection uses the report gate

- **WHEN** the thesis-test configuration is active
- **THEN** Action selection's policy is the self-initiated report policy, and no
  user-utterance speak trigger is wired
