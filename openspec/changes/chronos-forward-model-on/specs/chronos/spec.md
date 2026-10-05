## MODIFIED Requirements

### Requirement: time_since_last_interaction subscribes to user-input streams
Chronos SHALL subscribe to a configurable set of streams known to carry user input (default `audition.out`) in addition to `workspace.broadcast`. Only an interaction SHALL reset the interaction clock: a speech-path event (`audition.transcription` with non-empty text, or `audition.emotion`) whose `source_label` is an operator source. The operator sources SHALL be one shared list, the same list Volition and Empatheia use. Every other event on those streams, including `audition.perception`, `audition.prosody` and speech heard from a perception feed, SHALL NOT reset it. The time of the most recent interaction SHALL be the basis for `time_since_last_interaction_s`; if no interaction has occurred, the reported value SHALL be `inf`.

#### Scenario: No interactions yields infinity
- **WHEN** Chronos has just initialized and no user-input events have arrived
- **THEN** the next `chronos.report` has `time_since_last_interaction_s == math.inf`

#### Scenario: Interaction resets the clock
- **WHEN** an `audition.emotion` event with `source_label` `live_mic` arrives on a configured user-input stream
- **THEN** the next `chronos.report`'s `time_since_last_interaction_s` is the elapsed seconds since that event arrived

#### Scenario: Perception does not count as interaction
- **WHEN** only `audition.perception` events arrive, from any source
- **THEN** `time_since_last_interaction_s` keeps growing from the last interaction, or stays `inf` if there has been none

#### Scenario: Speech from a perception feed does not count
- **WHEN** an `audition.emotion` event with `source_label` `playlist` arrives
- **THEN** the interaction clock is not reset

### Requirement: The default user-input stream resolves to a real producer

Chronos's in-code default user-input stream SHALL be the stream Audition publishes to (`audition.out`), so that when configuration omits `user_input_streams` Chronos still reads a real producer stream rather than a mistyped or retired one.

#### Scenario: Code default resolves to the Audio In producer stream

- **WHEN** Chronos's `DEFAULT_USER_INPUT_STREAMS` is inspected
- **THEN** it contains `audition.out` (the stream `module_stream("audition")` yields) and not a non-existent variant such as `audio.in.out`

### Requirement: User-input stream references resolve to real producers

Chronos's configured user-input streams SHALL name actual producer streams that some module publishes to. In particular, the Audition stream Chronos consumes SHALL be the stream Audition publishes to (`audition.out`), not a mistyped or retired variant. More generally, every stream name referenced from `config/kaine.toml` by a consuming module SHALL resolve to a canonical producer stream (`<module>.out`, `workspace.broadcast`, `cycle.out`, `lingua.external`, or `lingua.internal`); a reference that resolves to no producer is a configuration error.

#### Scenario: Chronos is wired to the Audio In producer stream

- **WHEN** the shipped `config/kaine.toml` is loaded
- **THEN** `[chronos].user_input_streams` contains the stream Audition actually publishes to (`audition.out`)
- **AND** it does not contain a non-existent variant such as `audio.in.out`

#### Scenario: A mistyped stream reference fails the wiring test

- **WHEN** any config stream reference names a stream no module produces
- **THEN** the config stream-wiring test fails, identifying the bad reference

## ADDED Requirements

### Requirement: The featurization layout is versioned
The featurizer SHALL produce a 24-dimension vector under a numbered layout. Layout 1 SHALL be the eight-source layout in which unknown sources, Audition included, share the last source bin and slot 23 is always zero. Layout 2 SHALL be layout 1 with Audition events featurized into slot 23. Chronos SHALL record the layout in its serialized state. On restore, a snapshot without a layout SHALL be treated as layout 1, and a snapshot with an unknown layout SHALL fail to load. A Chronos that restores no state SHALL use the newest layout.

#### Scenario: A preserved being keeps its layout
- **WHEN** Chronos is restored from a snapshot that records no layout and then featurizes a snapshot containing an Audition event
- **THEN** the Audition event's salience is added to the last source bin and slot 23 is zero

#### Scenario: A new being uses layout 2
- **WHEN** a Chronos that restored no state featurizes a snapshot containing an Audition event
- **THEN** the Audition event's salience is in slot 23 and not in the last source bin

#### Scenario: The vector length is unchanged
- **WHEN** either layout featurizes any snapshot
- **THEN** the vector has 24 components

#### Scenario: Unknown layout
- **WHEN** Chronos is restored from a snapshot that records layout 99
- **THEN** the restore raises an error naming the layout
