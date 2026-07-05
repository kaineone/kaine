# audio-output Specification

## Purpose
TBD - created by archiving change audio-output. Update Purpose after archive.
## Requirements
### Requirement: TTSClient protocol with Chatterbox default
AudioOutput SHALL accept a `TTSClient` collaborator implementing
`async synthesize(request) -> SynthesisResult`. The default
`ChatterboxClient` SHALL POST to
`http://127.0.0.1:8883/tts` with the Chatterbox `/tts` endpoint's
request shape (text, voice_mode, predefined_voice_id, temperature,
exaggeration, cfg_weight, speed_factor, output_format).

#### Scenario: Default client targets local Chatterbox
- **WHEN** `ChatterboxClient()` is constructed with no overrides
- **THEN** its `base_url` property equals `"http://127.0.0.1:8883"`

#### Scenario: Custom client substitutes cleanly
- **WHEN** AudioOutput is constructed with a custom `TTSClient` that
  returns canned audio bytes
- **THEN** every synthesis call returns those bytes

### Requirement: Thymos state maps to Chatterbox expressivity
The `affect_to_chatterbox(state)` pure function SHALL map a
`DimensionalState` to a `ChatterboxParams` instance carrying
`temperature`, `exaggeration`, `cfg_weight`, `speed_factor`, each in
a documented band. Higher arousal SHALL produce strictly larger
`exaggeration`. Stronger valence magnitude SHALL produce strictly
larger `cfg_weight` (more committed delivery).

#### Scenario: Higher arousal strictly increases exaggeration
- **WHEN** `affect_to_chatterbox(state_with_arousal=0.2)` and
  `affect_to_chatterbox(state_with_arousal=0.8)` are computed for
  otherwise-identical states
- **THEN** the second result's `exaggeration` is strictly greater
  than the first's

#### Scenario: Stronger valence increases cfg_weight
- **WHEN** `affect_to_chatterbox(state_with_valence=0.1)` and
  `affect_to_chatterbox(state_with_valence=-0.9)` are computed for
  otherwise-identical states
- **THEN** the second result's `cfg_weight` is strictly greater than
  the first's

### Requirement: AudioOutput subscribes to lingua.external
AudioOutput SHALL subscribe to the `lingua.external` stream and, for
each `lingua.external` event observed, SHALL invoke the TTS client to
synthesize audio for the event's `text` field. The synthesis SHALL
use parameters derived from the most-recent `thymos.state` observed
on the `thymos.out` stream (or configured baseline if none seen yet).

#### Scenario: lingua.external event triggers one synthesis
- **WHEN** Lingua publishes one event on `lingua.external` while
  AudioOutput is running
- **THEN** the TTS client receives exactly one `synthesize` call
  whose request `text` equals the event's `text`

#### Scenario: Most-recent thymos.state used for parameters
- **WHEN** two `thymos.state` events with different arousals are
  observed (latest arousal=0.8) and then a `lingua.external` event
  arrives
- **THEN** the TTS request's `exaggeration` is the value
  `affect_to_chatterbox` produces for arousal=0.8

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

### Requirement: Default AudioOutput config and disabled-by-default
The repository SHALL ship an `[audio_out]` block in
`config/kaine.toml` with default values for `chatterbox_url`,
`voice_mode`, `predefined_voice_id`, `output_format`, `sink_path`,
`baseline_temperature`, `baseline_exaggeration`, `baseline_cfg_weight`,
`request_timeout_s`, `baseline_salience`. `[modules].audio_out = false`
SHALL keep first boot from auto-registering AudioOutput.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find an `[audio_out]` section with the documented
  keys and `[modules].audio_out == false`

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

