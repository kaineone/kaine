# vox Specification

## Purpose
TBD - created by archiving change rename-audition-vox. Update Purpose after archive.
## Requirements
### Requirement: Vox module identity
The voice organ SHALL be the module named `vox` (renamed from `audio_out`),
implemented by the `Vox` class, publishing to the `vox.out` stream. Its behavior
(Chatterbox TTS with Thymos-affect-driven parameters, sink writing, self-hearing
suppression) SHALL be unchanged by the rename.

#### Scenario: Module reports its name
- **WHEN** the `Vox` module is constructed
- **THEN** its `name` attribute equals `"vox"`

#### Scenario: Output stream follows the name
- **WHEN** Vox publishes any event
- **THEN** it is written to the `vox.out` stream

### Requirement: Vox event-type name and sink
Vox SHALL publish synthesis-result events with type `vox.synthesized` and write
audio to the `state/vox/` sink directory. No event with type `audio.out.*` SHALL
be published after this change.

#### Scenario: Synthesis event type
- **WHEN** Vox synthesizes speech
- **THEN** the published event's `type` equals `"vox.synthesized"`

#### Scenario: Sink directory follows the name
- **WHEN** Vox writes synthesized audio to its sink
- **THEN** the file is written under `state/vox/`

