## ADDED Requirements

### Requirement: User-input stream references resolve to real producers

Chronos's configured user-input streams SHALL name actual producer streams that
some module publishes to. In particular, the Audio In transcription stream
Chronos consumes SHALL be the stream Audio In publishes to (`audio_in.out`), not
a mistyped variant. More generally, every stream name referenced from
`config/kaine.toml` by a consuming module SHALL resolve to a canonical producer
stream (`<module>.out`, `workspace.broadcast`, `cycle.out`, `lingua.external`,
or `lingua.internal`); a reference that resolves to no producer is a
configuration error.

#### Scenario: Chronos is wired to the Audio In producer stream

- **WHEN** the shipped `config/kaine.toml` is loaded
- **THEN** `[chronos].user_input_streams` contains the stream Audio In actually
  publishes to (`audio_in.out`)
- **AND** it does not contain a non-existent variant such as `audio.in.out`

#### Scenario: A mistyped stream reference fails the wiring test

- **WHEN** any config stream reference names a stream no module produces
- **THEN** the config stream-wiring test fails, identifying the bad reference
