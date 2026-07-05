## ADDED Requirements

### Requirement: The default user-input stream resolves to a real producer

Chronos's in-code default user-input stream SHALL be the stream Audio In
publishes to (`audio_in.out`), so that when configuration omits
`user_input_streams` Chronos still reads a real producer stream rather than a
mistyped non-existent one.

#### Scenario: Code default resolves to the Audio In producer stream

- **WHEN** Chronos's `DEFAULT_USER_INPUT_STREAMS` is inspected
- **THEN** it contains `audio_in.out` (the stream `module_stream("audio_in")`
  yields) and not a non-existent variant such as `audio.in.out`
