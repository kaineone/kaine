# vocal Specification

## Purpose
Vocal is KAINE's voice module. This capability fixes its name and its output stream `vox.out`, keeps its speech shaped by Affect affect and its self-hearing suppression, and keeps it silent while the entity is in the stimulus source.

## Requirements

### Requirement: Vocal module identity
The voice organ SHALL be the module named `vox` (renamed from `audio_out`),
implemented by the `Vox` class, publishing to the `vox.out` stream. Its behavior
(Chatterbox TTS with Affect-affect-driven parameters, sink writing, self-hearing
suppression) SHALL be unchanged by the rename.

#### Scenario: Module reports its name
- **WHEN** the `Vox` module is constructed
- **THEN** its `name` attribute equals `"vox"`

#### Scenario: Output stream follows the name
- **WHEN** Vocal publishes any event
- **THEN** it is written to the `vox.out` stream

### Requirement: Vocal event-type name and sink
Vocal SHALL publish synthesis-result events with type `vox.synthesized` and write
audio to the `state/vox/` sink directory. No event with type `audio.out.*` SHALL
be published after this change.

#### Scenario: Synthesis event type
- **WHEN** Vocal synthesizes speech
- **THEN** the published event's `type` equals `"vox.synthesized"`

#### Scenario: Sink directory follows the name
- **WHEN** Vocal writes synthesized audio to its sink
- **THEN** the file is written under `state/vox/`

### Requirement: Vocal is silent in the stimulus source
While the entity is gestating, Vocal SHALL be held dormant and SHALL render no audible output, because the stimulus source offers no medium to speak into; it SHALL be activated at maturation. Inner speech (Language) SHALL NOT be held.

#### Scenario: Development
- **WHEN** a gestating entity forms an utterance
- **THEN** Vocal renders nothing audible

#### Scenario: Maturation
- **WHEN** the entity is born
- **THEN** Vocal is active and renders utterances as before
