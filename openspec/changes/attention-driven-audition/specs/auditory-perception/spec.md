# auditory-perception

## ADDED Requirements

### Requirement: General acoustic representation of any sound

Audition SHALL encode each captured audio window into a general acoustic embedding
with a frozen self-supervised audio encoder that represents speech, music, and
environmental sound in one space — not only speech. The embedding SHALL be held in
process memory only and SHALL NOT be written to disk.

#### Scenario: A non-speech sound is represented

- **WHEN** a captured window contains a non-speech sound (an alarm, breaking glass,
  music, footsteps)
- **THEN** it is encoded into an acoustic embedding and perceived, rather than
  discarded or reduced to empty transcription

#### Scenario: Embedding is memory-only

- **WHEN** an acoustic embedding is computed
- **THEN** no raw audio or embedding is written to disk

### Requirement: Acoustic salience from change and prediction error

Audition SHALL compute the salience of what it hears from the change and the
forward-model prediction error over the acoustic embedding, so that a novel,
sudden, or surprising sound reaches the workspace regardless of whether it is
speech.

#### Scenario: A novel non-speech sound is salient

- **WHEN** a sound unlike the recent acoustic context occurs (a sudden loud onset
  in a quiet scene)
- **THEN** its published salience is higher than that of the steady background,
  independent of any speech content

### Requirement: Arousal-modulated auditory attention

Audition SHALL select a single attended sound stream by salience and SHALL derive
the breadth of the auditory attentional window from Thymos arousal — a distinct
affective→perceptual coupling, not the Syneidesis salience-selection window. The
sign and exact mapping of the arousal→window relation are tuning parameters, not
asserted results.

#### Scenario: Arousal sets the auditory window

- **WHEN** Thymos arousal differs between two ticks
- **THEN** the auditory attentional window changes monotonically with arousal (a
  distinct visual/auditory coupling; default sign tunable)

#### Scenario: Attention follows salience

- **WHEN** one stream is markedly more salient than the rest
- **THEN** it becomes the attended stream

### Requirement: Content-free attended-stream publication

Audition SHALL publish the attended-stream descriptor and its salience as
content-free values (which stream and how salient, in normalized terms) and SHALL
NOT include any raw audio with them.

#### Scenario: Attended-stream descriptor carries no audio

- **WHEN** the attended-stream descriptor is published
- **THEN** it contains only normalized numeric values and no audio buffer

### Requirement: Speech is a triggered specialization

When the attended stimulus is detected as speech, Audition SHALL run the
speech-to-text and vocal-emotion path on that stream and publish its transcription
and emotion on the `audition.out` stream; when the attended stimulus is not speech,
Audition SHALL still perceive it through the general acoustic path. Speech
processing SHALL be a specialization off the general path, not a precondition for
hearing.

#### Scenario: Non-speech is heard without transcription

- **WHEN** the attended sound is not speech
- **THEN** it is perceived and scored for salience, and no transcription is required
  for it to reach the workspace

#### Scenario: Speech still transcribed

- **WHEN** the attended sound is speech
- **THEN** the transcription and vocal-emotion events are produced as before

### Requirement: General auditory perception is off by default with a speech fallback

General auditory perception SHALL be disabled by default, and when disabled
Audition SHALL run the existing speech pipeline (transcription + vocal emotion)
unchanged.

#### Scenario: Default install is unchanged

- **WHEN** the shipped configuration is used without enabling general auditory
  perception
- **THEN** Audition behaves exactly as the existing speech pipeline

### Requirement: The acoustic encoder is selectable
Audition SHALL select its acoustic encoder from `[audition].acoustic_encoder`, with `spectral` as the default. An unknown encoder name, or an encoder whose pinned weights are not provisioned on the host, SHALL raise a configuration error at boot and SHALL NOT fall back to another encoder. A plugin MAY supply the encoder through the `audition.acoustic_encoder` seam; a filled seam together with a non-default `acoustic_encoder` value SHALL be a configuration error.

#### Scenario: Default encoder
- **WHEN** general audition is on and `acoustic_encoder` is not set
- **THEN** Audition encodes with the spectral encoder and `audition.perception` carries its `encoder_model_id`

#### Scenario: Unknown encoder
- **WHEN** `acoustic_encoder` names an encoder the registry does not know
- **THEN** building Audition raises a configuration error naming the value

#### Scenario: Plugin encoder
- **WHEN** an enabled plugin fills `audition.acoustic_encoder` and `acoustic_encoder` is unset
- **THEN** Audition encodes with the plugin's encoder

### Requirement: Self-supervised encoders load offline from pinned, vendored code
A self-supervised acoustic encoder SHALL load from code vendored under `external/` with an `UPSTREAM` file naming its source, pinned revision and licence, and from weights fetched at setup time at that pinned revision. Loading SHALL use local files only, with the Hugging Face hub offline, and SHALL NOT execute remote code. Its rolling sample window SHALL exist in memory only.

#### Scenario: No network at load
- **WHEN** a self-supervised encoder is constructed with the hub offline and its weights provisioned
- **THEN** it loads without any network access and without remote code

#### Scenario: Window never persists
- **WHEN** Audition is serialized while a self-supervised encoder holds a rolling window
- **THEN** the serialized state contains no samples and no embeddings from that window

### Requirement: Loudness is a separate channel
`audition.perception` SHALL carry `energy_dbfs`, the RMS level of the perceived window in dBFS, computed independently of the acoustic encoder, so that salience can use loudness whichever encoder is selected.

#### Scenario: Loudness survives a loudness-normalising encoder
- **WHEN** two windows differ only in gain and are perceived through an encoder that normalises loudness
- **THEN** their `energy_dbfs` values differ by the gain difference
