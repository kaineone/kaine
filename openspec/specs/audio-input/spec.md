# audio-input Specification

## Purpose
TBD - created by archiving change audio-input. Update Purpose after archive.
## Requirements
### Requirement: STT and emotion classifiers are replaceable
AudioInput SHALL accept an `STTClient` collaborator and an
`EmotionClassifier` collaborator. Defaults SHALL be `SpeachesClient`
(httpx multipart POST to
`http://127.0.0.1:8000/v1/audio/transcriptions`) and
`Emotion2vecClassifier` (lazy-import `funasr`, load
`emotion2vec/emotion2vec_plus_base`).

#### Scenario: Default STT client targets Speaches
- **WHEN** `SpeachesClient()` is constructed with no overrides
- **THEN** its `base_url` property equals `"http://127.0.0.1:8000"`

#### Scenario: Custom collaborators substitute cleanly
- **WHEN** AudioInput is constructed with `FakeSTTClient` and
  `FakeEmotionClassifier`
- **THEN** every `process_audio` call uses those fakes rather than
  the defaults

### Requirement: process_audio runs STT and emotion in parallel
AudioInput SHALL expose `async process_audio(audio_bytes, sample_rate,
*, source_label="microphone")`. The call SHALL run STT and the emotion
classifier concurrently via `asyncio.gather` so total latency is
`max(stt_latency, emotion_latency)`. Both SHALL publish their results
as separate events on the `audio.in.out` stream.

#### Scenario: One call publishes two events
- **WHEN** `process_audio(...)` is awaited once
- **THEN** exactly two events appear on `audio.in.out` with types
  `audio.in.transcription` and `audio.in.emotion`

### Requirement: Transcription event carries text + metadata
The `audio.in.transcription` event payload SHALL contain `text`,
`source_label`, `model`, `sample_rate`, `audio_bytes_length`, and
`latency_ms`.

#### Scenario: Transcription payload shape
- **WHEN** `process_audio(b"...", 16000, source_label="mic1")` is awaited
- **THEN** the transcription event's payload contains all the
  documented keys, with `source_label == "mic1"` and
  `sample_rate == 16000`

### Requirement: Emotion event carries category + confidence
The `audio.in.emotion` event payload SHALL contain `category` (one of
`neutral`, `happy`, `sad`, `angry`, `surprised`, `fearful`,
`disgusted`), `confidence` (float in `[0, 1]`), `scores` (dict mapping
each category to its score), `model`, `source_label`, and
`latency_ms`. The categories SHALL match those documented in build
prompt §5.1.

#### Scenario: Category in the documented set
- **WHEN** `process_audio` returns
- **THEN** the published `audio.in.emotion` event's `category` is one
  of the seven documented categories

### Requirement: Emotion classifier degrades gracefully when funasr is absent
The default `Emotion2vecClassifier` SHALL attempt to import `funasr`
on first use. If import fails, the classifier SHALL log a one-time
warning naming the missing dependency and SHALL return a `neutral`
classification with confidence 0.0 for every subsequent call. The
module SHALL continue to function (STT still runs, transcription
events still publish).

#### Scenario: Missing funasr does not break audio input
- **WHEN** funasr cannot be imported
- **THEN** `Emotion2vecClassifier.classify(...)` returns
  `EmotionResult(category="neutral", confidence=0.0)` without raising

### Requirement: STT failure does not block emotion publish
If the STT client raises during `process_audio`, AudioInput SHALL
publish an `audio.in.transcription` event with `error` set, an empty
`text`, and a high alert salience — and SHALL STILL publish the
`audio.in.emotion` event from the emotion classifier (which ran in
parallel and may have succeeded).

#### Scenario: STT failure publishes transcription with error and emotion separately
- **WHEN** the STT client raises
- **THEN** both events are still published; the transcription event
  has `error` in its payload and an empty `text`; the emotion event
  is unaffected

### Requirement: Default AudioInput config and disabled-by-default
The repository SHALL ship an `[audio_in]` block in
`config/kaine.toml` with default values for `speaches_url`,
`stt_model`, `emotion_model_id`, `request_timeout_s`,
`baseline_salience`, `alert_salience`. `[modules].audio_in = false`
SHALL keep first boot from auto-registering AudioInput.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find an `[audio_in]` section with the documented keys
  and `[modules].audio_in == false`

