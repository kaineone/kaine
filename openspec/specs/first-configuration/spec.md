# first-configuration Specification

## Purpose
The opt-in first configuration: the raw audio-visual predictive processors run with the always-on workspace and action selection module, the language module serves only as the output voice, and the voice speaks on the entity's own initiative rather than in reply to a prompt.

## Requirements

### Requirement: First-configuration module set

The system SHALL provide an opt-in run configuration that enables exactly the first-configuration module set:
- the diverse predictive processors: the interoception, sequence, vision and audition modules;
- the affect module, the affective precision core;
- the sleep module, fatigue-triggered sleep, with voice alignment off;
- the language module, the output-only voice;
- the always-on workspace and action selection module.

Every other module (the episodic memory module, the self-model module, the world model module, the social cognition module, the planning module, the vocal module, the effectors module, the perceptual locus module, the embodiment module, the recorder module) SHALL remain built and disabled. The configuration SHALL NOT remove or delete any module.

The profile `config/profiles/first_configuration.toml` SHALL be the single definition of this set. The operator overlay carries host-local values and deliberate deviations, and the first-run wizard's first-configuration preset reads the profile.

#### Scenario: Only the first-configuration processors activate

- **WHEN** the first configuration is selected at boot
- **THEN** exactly the interoception, sequence, vision, audition, affect, sleep and language modules are registered, the workspace and the action selection module run as scaffolding, and every other module is disabled but present

#### Scenario: The wizard's first-configuration preset matches the profile

- **WHEN** the first-run wizard offers the first-configuration preset
- **THEN** its module choices equal the profile's enabled set

### Requirement: Raw audio-visual perception, no transcript

The first configuration SHALL feed the vision and audition modules from a raw audio-
visual source (a live screen/monitor capture or a deterministic seeded/playlist
feed), with vision foveation enabled (precision-weighted attention) and audition
transcription disabled. Perception SHALL enter the workspace only as prediction
error, never as transcribed text.

#### Scenario: Audio enters as prediction error only

- **WHEN** the first configuration is active and audio is present
- **THEN** Audition publishes `audition.perception` (and affect signals) but not
  `audition.transcription`

#### Scenario: Vision is foveated

- **WHEN** the first configuration is active
- **THEN** the vision module runs with its arousal-sized foveation enabled

### Requirement: Self-initiated voice, no chatbot trigger

The first configuration SHALL select the self-initiated report policy for
the action selection module and SHALL NOT enable any user-utterance / transcription speak trigger, so
the entity speaks only from its own state.

#### Scenario: Action selection uses the report gate

- **WHEN** the first configuration is active
- **THEN** the action selection module's policy is the self-initiated report policy, and no
  user-utterance speak trigger is wired
