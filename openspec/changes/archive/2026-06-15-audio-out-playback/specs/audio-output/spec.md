## MODIFIED Requirements

### Requirement: Audio bytes never appear on the bus
The published `audio.out.synthesized` event payload SHALL contain
`text_length`, `bytes_produced`, `output_format`, `voice`,
`exaggeration`, `cfg_weight`, `temperature`, `latency_ms` — and SHALL
NEVER contain the audio bytes themselves or the raw spoken text. The
synthesized audio is played through the host output device as the primary
output (see *Synthesized speech is played through an output device*); it is
written to the configured sink directory only when the off-by-default file
sink is enabled (see *Rendered audio is not persisted without bound*). The
audio is never placed on the bus.

#### Scenario: Bus event excludes audio bytes
- **WHEN** any synthesis succeeds
- **THEN** the published `audio.out.synthesized` event has no field
  whose value is a `bytes` object

#### Scenario: Audio is written to the sink only when the sink is enabled
- **WHEN** synthesis succeeds with output format `wav` and the file sink is enabled
- **THEN** a `.wav` file appears in the configured sink directory
  whose size equals `bytes_produced`

#### Scenario: No file is written when the sink is disabled
- **WHEN** synthesis succeeds while the file sink is disabled (the shipped default)
- **THEN** no audio file is written to the sink directory

## ADDED Requirements

### Requirement: Synthesized speech is played through an output device

`audio_out` SHALL play synthesized audio through the host's default or a
configured output device as its primary action. Playback SHALL be the default
behavior (`playback_enabled` default true). Playback SHALL be serialized so that
multiple utterances play in order, and SHALL run without blocking the cognitive
cycle.

If no output device is available or the audio playback extra is not installed,
`audio_out` SHALL log a single warning and continue: synthesis and the
`audio.out.synthesized` event SHALL still occur. Absence of playback SHALL NOT
raise or stop the module.

#### Scenario: A produced utterance is played

- **WHEN** `lingua.external` emits text and `audio_out` synthesizes it
- **THEN** the synthesized clip is played through the output device
- **AND** the `audio.out.synthesized` event is still published

#### Scenario: No device degrades gracefully

- **WHEN** no output device / playback extra is available
- **THEN** `audio_out` logs one warning and continues
- **AND** synthesis and the `audio.out.synthesized` event still happen
- **AND** no exception propagates

### Requirement: Rendered audio is not persisted without bound

`audio_out` SHALL NOT persist synthesized audio indefinitely. By default
(`sink_enabled` false) no audio file is written — the clip is played from memory
and released. When the file sink is enabled, retention SHALL be bounded: after
each write the sink directory SHALL be pruned to at most `retain_count` newest
clips (or a configured byte ceiling), deleting oldest first. There SHALL be no
configuration in which synthesized clips accumulate without bound.

#### Scenario: Default discards after playing

- **WHEN** `sink_enabled` is false and an utterance is synthesized and played
- **THEN** no file is written to the sink directory

#### Scenario: Bounded retention prunes oldest

- **WHEN** `sink_enabled` is true with `retain_count = N`
- **AND** more than N clips have been synthesized
- **THEN** the sink directory retains only the N newest clips

### Requirement: Entity does not ingest its own spoken output when suppression is enabled

`audio_out` and `audio_in` SHALL support self-hearing suppression, gated by a
`suppress_self_hearing` configuration flag that SHALL default to true. When
enabled, the two SHALL coordinate so that, while a synthesized clip is playing
aloud and the live microphone is capturing, the entity does not transcribe its
own voice as a user utterance: captured utterances that begin within the playback
window plus a configured hangover SHALL be dropped before becoming a user-
communication event. When disabled (appropriate for an acoustically isolated
input such as a headset mic), audio-in ingestion SHALL be unaffected by playback,
leaving the entity full-duplex.

#### Scenario: Self-voice during playback is dropped when suppression is enabled

- **WHEN** `suppress_self_hearing` is true
- **AND** a clip is playing and the mic captures audio that starts within the
  playback window plus hangover
- **THEN** that captured audio does not produce an `audio.in.transcription`
  attributed to the user

#### Scenario: Speech after the hangover is heard normally

- **WHEN** `suppress_self_hearing` is true
- **AND** the mic captures an utterance that starts after playback plus hangover
  has elapsed
- **THEN** it is transcribed and treated as a normal user utterance

#### Scenario: Isolated-input setups stay full-duplex

- **WHEN** `suppress_self_hearing` is false
- **AND** a clip is playing aloud while the mic captures a user utterance
- **THEN** the utterance is transcribed normally and is not dropped on account of
  playback
