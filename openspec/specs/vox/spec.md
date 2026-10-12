# vocal Specification

## Purpose
The vocal module is KAINE's voice module. This capability fixes its name and its output stream `vox.out`, keeps its speech shaped by the affect module and its self-hearing suppression, and keeps it silent while the entity is in the stimulus source.

## Requirements

### Requirement: Vocal module identity
The voice organ SHALL be the module named `vox` (renamed from `audio_out`),
implemented by the `Vox` class, publishing to the `vox.out` stream. Its behavior
(Chatterbox TTS with affect-driven parameters, sink writing, self-hearing
suppression) SHALL be unchanged by the rename.

#### Scenario: Module reports its name
- **WHEN** the `Vox` module is constructed
- **THEN** its `name` attribute equals `"vox"`

#### Scenario: Output stream follows the name
- **WHEN** the vocal module publishes any event
- **THEN** it is written to the `vox.out` stream

### Requirement: Vocal event-type name and sink
The vocal module SHALL publish synthesis-result events with type `vox.synthesized` and write
audio to the `state/vox/` sink directory. No event with type `audio.out.*` SHALL
be published after this change.

#### Scenario: Synthesis event type
- **WHEN** the vocal module synthesizes speech
- **THEN** the published event's `type` equals `"vox.synthesized"`

#### Scenario: Sink directory follows the name
- **WHEN** the vocal module writes synthesized audio to its sink
- **THEN** the file is written under `state/vox/`

### Requirement: Vocal is silent in the stimulus source
While the entity is in its developmental phase, the vocal module SHALL be held dormant and SHALL render no audible output, because the stimulus source offers no medium to speak into; it SHALL be activated at maturation. Inner speech (the language module) SHALL NOT be held.

#### Scenario: Developmental phase
- **WHEN** an entity in its developmental phase forms an utterance
- **THEN** the vocal module renders nothing audible

#### Scenario: Maturation
- **WHEN** the entity matures
- **THEN** the vocal module is active and renders utterances as before
