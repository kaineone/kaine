## ADDED Requirements

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
synthesized audio is written to the configured sink directory, not
the bus.

#### Scenario: Bus event excludes audio bytes
- **WHEN** any synthesis succeeds
- **THEN** the published `audio.out.synthesized` event has no field
  whose value is a `bytes` object

#### Scenario: Audio is written to sink
- **WHEN** synthesis succeeds with output format `wav`
- **THEN** a `.wav` file appears in the configured sink directory
  whose size equals `bytes_produced`

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
