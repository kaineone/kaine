# audition

## MODIFIED Requirements

### Requirement: Audition module identity

The hearing organ SHALL be the module named `audition`, implemented by the
`Audition` class, publishing to the `audition.out` stream. When general auditory
perception is enabled, its primary behavior SHALL be to represent all captured
sound as a general acoustic embedding and to score its salience over that
embedding; speech-to-text and vocal-emotion classification SHALL run as a
specialization on segments detected as speech. When general auditory perception is
disabled, its behavior (speech-to-text, vocal-emotion classification, and the
existing capture path) SHALL be the shipped speech pipeline unchanged. The
self-hearing gate SHALL remain in force in both modes.

#### Scenario: Module reports its name

- **WHEN** the `Audition` module is constructed
- **THEN** its `name` attribute equals `"audition"`

#### Scenario: Output stream follows the name

- **WHEN** Audition publishes any event
- **THEN** it is written to the `audition.out` stream

#### Scenario: Self-heard capture is dropped in both modes

- **WHEN** the entity is speaking (the shared speaking gate is open)
- **THEN** captured audio is dropped and neither the general acoustic path nor the
  speech path perceives it as external input
