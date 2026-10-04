## RENAMED Requirements
- FROM: `### Requirement: Default AudioInput config and disabled-by-default`
- TO: `### Requirement: Default Audition config and disabled-by-default`

## MODIFIED Requirements

### Requirement: STT and emotion classifiers are replaceable
Audition SHALL accept an `STTClient` collaborator and an
`EmotionClassifier` collaborator. Defaults SHALL be `SpeachesClient`
(default URL `http://127.0.0.1:8000`) and `Emotion2vecClassifier`
(lazy-import `funasr`, load `emotion2vec/emotion2vec_plus_base`).
`emotion_model_id = ""` SHALL select `NullEmotionClassifier`, which returns
`neutral` with confidence `0.0`. The default STT backend SHALL be
`"speaches"`; the alternative backend `"sherpa_onnx"`
(`SherpaMoonshineSTT`, model `moonshine-base-en`) SHALL be opt-in.

#### Scenario: Default STT client targets Speaches
- **WHEN** `SpeachesClient()` is constructed with no overrides
- **THEN** its `base_url` property equals `"http://127.0.0.1:8000"`

#### Scenario: Custom collaborators substitute cleanly
- **WHEN** Audition is constructed with `FakeSTTClient` and
  `FakeEmotionClassifier`
- **THEN** every `process_audio` call uses those fakes rather than
  the defaults

#### Scenario: Emotion classifier can be disabled
- **WHEN** `emotion_model_id` is set to `""`
- **THEN** Audition uses `NullEmotionClassifier`
- **AND** every classification returns `category="neutral"`,
  `confidence=0.0`, and `model="disabled"`

#### Scenario: Alternative STT backend is opt-in
- **WHEN** `[audition].backend` is set to `"sherpa_onnx"`
- **THEN** the STT implementation uses `SherpaMoonshineSTT`
  with model `moonshine-base-en`

### Requirement: process_audio runs STT and emotion in parallel
Audition SHALL expose `async process_audio(audio_bytes, sample_rate,
*, source_label="microphone", item=None)`. The call SHALL run STT
(when enabled) and the emotion classifier concurrently via
`asyncio.gather` so total latency is `max(stt_latency, emotion_latency)`.
Results SHALL publish as separate events on the `audition.out` stream.

#### Scenario: One call publishes two events
- **WHEN** `process_audio(...)` is awaited once with `transcription_enabled=true`
- **THEN** exactly two events appear on `audition.out` with types
  `audition.transcription` and `audition.emotion`

#### Scenario: One call publishes only the emotion event when transcription is disabled
- **WHEN** `process_audio(...)` is awaited once with `transcription_enabled=false`
- **THEN** exactly one event appears on `audition.out` with type `audition.emotion`
- **AND** no `audition.transcription` event is published

#### Scenario: Speaking-gate-held capture is dropped
- **WHEN** a finished capture reaches `process_audio` while the shared
  `SpeakingGate` is held
- **THEN** no event is published on `audition.out`

#### Scenario: General-audition non-speech windows publish nothing
- **WHEN** `process_audio` receives a non-speech audio window while
  `general_audition` is enabled
- **THEN** no event is published on `audition.out`

### Requirement: Transcription event carries text + metadata
The `audition.transcription` event payload SHALL contain `text`,
`source_label`, `model`, `sample_rate`, `audio_bytes_length`,
`latency_ms`, `prediction_error`, and `backend`.

#### Scenario: Transcription payload shape
- **WHEN** `process_audio(b"...", 16000, source_label="mic1")` is awaited
  with `transcription_enabled=true`
- **THEN** the transcription event's payload contains all the
  documented keys, with `source_label == "mic1"` and
  `sample_rate == 16000`

### Requirement: Emotion event carries category + confidence
The `audition.emotion` event payload SHALL contain `category` (one of
`neutral`, `happy`, `sad`, `angry`, `surprised`, `fearful`,
`disgusted`), `confidence` (float in `[0, 1]`), `scores` (dict mapping
each category to its score), `model`, `source_label`, and
`latency_ms`. When `prediction_error` or `degraded` apply, they SHALL
be included in the payload.

#### Scenario: Category in the documented set
- **WHEN** `process_audio` returns
- **THEN** the published `audition.emotion` event's `category` is one
  of the seven documented categories

#### Scenario: Null emotion classifier reports disabled
- **WHEN** `emotion_model_id` is `""`
- **THEN** the `audition.emotion` event's `category` is `neutral`,
  `confidence` is `0.0`, and `model` is `"disabled"`

### Requirement: Emotion classifier degrades gracefully when funasr is absent
The default `Emotion2vecClassifier` SHALL attempt to import `funasr`
on first use. If import fails, the classifier SHALL log a one-time
warning naming the missing dependency and SHALL return a `neutral`
classification with confidence 0.0 and `degraded=true` for every
subsequent call. The module SHALL continue to function (STT still runs
when enabled, transcription events still publish when enabled).

#### Scenario: Missing funasr does not break audio input
- **WHEN** funasr cannot be imported
- **THEN** `Emotion2vecClassifier.classify(...)` returns
  `EmotionResult(category="neutral", confidence=0.0)` without raising
- **AND** the result includes `degraded=true`

### Requirement: STT failure does not block emotion publish
If the STT client raises during `process_audio` (when transcription is
enabled), Audition SHALL publish an `audition.transcription` event with
`error` set, an empty `text`, `prediction_error`, `backend`, and a high
salience equal to `alert_salience`, and SHALL STILL publish the `audition.emotion` event
from the emotion classifier (which ran in parallel and may have
succeeded).

#### Scenario: STT failure publishes transcription with error and emotion separately
- **WHEN** the STT client raises while transcription is enabled
- **THEN** both events are still published on `audition.out`; the
  transcription event has `error` in its payload and an empty `text`;
  the emotion event is unaffected

### Requirement: Default Audition config and disabled-by-default
The repository SHALL ship an `[audition]` block in
`config/kaine.toml` with default values for `speaches_url`,
`stt_model`, `emotion_model_id`, `request_timeout_s`,
`baseline_salience`, `alert_salience`, `backend`,
`transcription_enabled`, capture/VAD/prosody keys, and
`general_audition`. `[modules].audition = false` SHALL keep first boot
from auto-registering Audition.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find an `[audition]` section with the documented keys
  and `[modules].audition == false`

#### Scenario: Transcription is off by default
- **WHEN** Audition is constructed with shipped defaults
- **THEN** `transcription_enabled` is `false`
- **AND** incoming audio does not trigger STT
- **AND** no `audition.transcription` event is published

### Requirement: Heard audio carries its channel
Audio delivered through the live-microphone path SHALL carry the channel
it came from: the perception-feed mode (`playlist`, `seeded`, `womb`,
`screen`) when a feed plays, and `live_mic` for a real device. Only
speech from an operator channel SHALL be treated as a user utterance
addressed to the entity; speech from other channels SHALL still be
perceived and compete for the workspace. The operator-utterance
transcription event used by Volition SHALL have source `audition` and
type `audition.transcription`.

#### Scenario: A film character speaks
- **WHEN** a transcription from the playlist channel is broadcast with
  source `audition` and type `audition.transcription`
- **THEN** no speak intent answering it is formed

#### Scenario: The operator speaks
- **WHEN** a transcription from the live microphone is broadcast with
  source `audition` and type `audition.transcription`
- **THEN** a speak intent answering it may be formed
