## RENAMED Requirements
- FROM: `### Requirement: AudioOutput subscribes to lingua.external`
- TO: `### Requirement: Vox subscribes to lingua.external`
- FROM: `### Requirement: Default AudioOutput config and disabled-by-default`
- TO: `### Requirement: Default Vox config and disabled-by-default`

## MODIFIED Requirements

### Requirement: TTSClient protocol with Chatterbox default
Vox SHALL accept a `TTSClient` collaborator implementing
`async synthesize(request) -> SynthesisResult`. The default
`ChatterboxClient` SHALL POST to
`http://127.0.0.1:8883/tts` with the Chatterbox `/tts` endpoint's
request shape (`text`, `voice_mode`, `predefined_voice_id`,
`temperature`, `exaggeration`, `cfg_weight`, `speed_factor`,
`output_format`). The default backend SHALL be `"chatterbox"`. The
alternative backend `"sherpa_onnx"` (Kokoro, `kokoro-en`) SHALL be
opt-in and, when selected, SHALL apply only `speed_factor` from the
affect mapping.

#### Scenario: Default client targets local Chatterbox
- **WHEN** `ChatterboxClient()` is constructed with no overrides
- **THEN** its `base_url` property equals `"http://127.0.0.1:8883"`

#### Scenario: Custom client substitutes cleanly
- **WHEN** Vox is constructed with a custom `TTSClient` that
  returns canned audio bytes
- **THEN** every synthesis call returns those bytes

### Requirement: Vox subscribes to lingua.external
Vox SHALL subscribe to the `lingua.external` stream and, for each
`lingua.external` event observed while not in a muted or dormant state,
SHALL invoke the TTS client to synthesize audio for the event's `text`
field. The synthesis SHALL use parameters derived from the most-recent
`thymos.state` observed on the `thymos.out` stream (or configured
baseline if none seen yet). When `[vox.mirroring].enabled` is true,
Vox SHALL also subscribe to `audition.out` and use `audition.prosody`
events for prosodic mirroring.

#### Scenario: lingua.external event triggers one synthesis
- **WHEN** Lingua publishes one event on `lingua.external` while
  Vox is running
- **THEN** the TTS client receives exactly one `synthesize` call
  whose request `text` equals the event's `text`

#### Scenario: Most-recent thymos.state used for parameters
- **WHEN** two `thymos.state` events with different arousals are
  observed (latest arousal=0.8) and then a `lingua.external` event
  arrives
- **THEN** the TTS request's `exaggeration` is the value
  `affect_to_chatterbox` produces for arousal=0.8

#### Scenario: A dormant Vox stays silent
- **WHEN** Vox is dormant (the entity is in the womb)
- **AND** a `lingua.external` event arrives
- **THEN** no TTS request is made
- **AND** no `vox.synthesized` event is published

#### Scenario: A muted Vox reports that it cannot speak
- **WHEN** Vox is muted because its text-to-speech backend is unavailable
- **AND** `lingua.external` events arrive
- **THEN** no TTS request is made
- **AND** at most one `vox.synthesized` event per 60 seconds is published, with `success` false and an `error` naming the unavailable backend

#### Scenario: Prosody mirroring is off by default
- **WHEN** `[vox.mirroring].enabled` is false (shipped default)
- **THEN** Vox does not subscribe to `audition.out` for prosody

### Requirement: Audio bytes never appear on the bus
The published `vox.synthesized` event payload SHALL contain
`text_length`, `bytes_produced`, `output_format`, `voice`,
`exaggeration`, `cfg_weight`, `temperature`, `latency_ms`,
`speed_factor`, `success`, `backend`, `prosody_applied`, and may include
`error` and `origin`. It SHALL NEVER contain the audio bytes
themselves or the raw spoken text. The synthesized audio is played
through the host output device as the primary output; it is written to
the configured sink directory only when the off-by-default file sink is
enabled. The audio is never placed on the bus.

#### Scenario: Bus event excludes audio bytes
- **WHEN** any synthesis succeeds
- **THEN** the published `vox.synthesized` event has no field
  whose value is a `bytes` object

#### Scenario: Audio is written to the sink only when the sink is enabled
- **WHEN** synthesis succeeds with output format `wav`,
  `sink_enabled` is true and `retain_count` is at least 1
- **THEN** a `.wav` file appears in the configured sink directory
  whose size equals `bytes_produced`

#### Scenario: No file is written when the sink is disabled
- **WHEN** synthesis succeeds while `sink_enabled` is false
  (the shipped default)
- **THEN** no audio file is written to the sink directory

### Requirement: Default Vox config and disabled-by-default
The repository SHALL ship a `[vox]` block in
`config/kaine.toml` with default values for `chatterbox_url`,
`voice_mode`, `output_format`, `sink_path`,
`baseline_temperature`, `baseline_exaggeration`, `baseline_cfg_weight`,
`request_timeout_s`, `baseline_salience`, `alert_salience`, `lingua_external_stream`,
`thymos_state_stream`, `backend`, and `sherpa_*`. `predefined_voice_id`
is accepted at runtime but is not present in the shipped file.
`[modules].vox = false` SHALL keep first boot from auto-registering
Vox. Vox also accepts `playback_enabled` (default true),
`sink_enabled` (default false), `retain_count` (default 0), and
`suppress_self_hearing` (default true).

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[vox]` section with the documented
  keys and `[modules].vox == false`

### Requirement: Synthesized speech is played through an output device

Vox SHALL play synthesized audio through the host's default or a
configured output device as its primary action. Playback SHALL be the
default behavior (`playback_enabled` default true). Playback SHALL be
serialized by a lock so that multiple utterances play in order, and
SHALL run off the event loop without blocking the cognitive cycle.

If no output device is available or the audio playback extra is not
installed, Vox SHALL log a single warning and continue: synthesis and
the `vox.synthesized` event SHALL still occur. Absence of playback
SHALL NOT raise or stop the module.

#### Scenario: A produced utterance is played

- **WHEN** `lingua.external` emits text and Vox synthesizes it
- **THEN** the synthesized clip is played through the output device
- **AND** the `vox.synthesized` event is still published

#### Scenario: No device degrades gracefully

- **WHEN** no output device / playback extra is available
- **THEN** Vox logs one warning and continues
- **AND** synthesis and the `vox.synthesized` event still happen
- **AND** no exception propagates

### Requirement: Rendered audio is not persisted without bound

Vox SHALL NOT persist synthesized audio indefinitely. By default
(`sink_enabled` false) no audio file is written — the clip is played
from memory and released. When the file sink is enabled, retention
SHALL be bounded: after each write the sink directory SHALL be pruned to
at most `retain_count` newest clips, deleting oldest first.
`retain_count` defaults to 0, so an enabled sink keeps nothing after
pruning unless `retain_count` is set. There SHALL be no configuration in
which synthesized clips accumulate without bound.

#### Scenario: Default discards after playing

- **WHEN** `sink_enabled` is false and an utterance is synthesized and played
- **THEN** no file is written to the sink directory

#### Scenario: Bounded retention prunes oldest

- **WHEN** `sink_enabled` is true with `retain_count = N`
- **AND** more than N clips have been synthesized
- **THEN** the sink directory retains only the N newest clips

### Requirement: Entity does not ingest its own spoken output when suppression is enabled

Vox and Audition SHALL support self-hearing suppression, gated by a
`suppress_self_hearing` configuration flag that SHALL default to true.
When enabled, Vox SHALL hold a shared `SpeakingGate` for the duration
of each synthesized clip plus `mic_mute_hangover_ms` (default 600).
Audition SHALL check the gate when a finished capture reaches
`process_audio`; if the gate is held, the whole capture SHALL be
dropped and no `audition.transcription`, `audition.emotion`, or
`audition.perception` event SHALL be published for it. When disabled,
Vox never holds the gate and Audition ingestion is unaffected,
leaving the entity full-duplex.

#### Scenario: Self-voice during playback is dropped when suppression is enabled

- **WHEN** `suppress_self_hearing` is true
- **AND** a finished capture reaches Audition while the clip is playing
  or within `mic_mute_hangover_ms` after it ends
- **THEN** that capture does not produce an
  `audition.transcription`, `audition.emotion`, or
  `audition.perception` event attributed to the user

#### Scenario: Speech after the hangover is heard normally

- **WHEN** `suppress_self_hearing` is true
- **AND** a finished capture reaches Audition after playback plus
  hangover has elapsed
- **THEN** it is processed normally, and transcribed when transcription
  is enabled

#### Scenario: Isolated-input setups stay full-duplex

- **WHEN** `suppress_self_hearing` is false
- **AND** a clip is playing aloud while the mic captures a user utterance
- **THEN** the capture is processed normally and is not dropped on
  account of playback
