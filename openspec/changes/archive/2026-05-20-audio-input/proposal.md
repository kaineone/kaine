## Why

`docs/kaine-paper.md` §3.1 lays out audio input as three parallel
paths: STT (Speaches/Whisper), speech emotion recognition
(emotion2vec+), and speaker diarization (already substituted to NeMo
TitaNet per operator preference in an earlier feedback memory). Build
prompt §5.1 names the first two — STT and emotion2vec+ — as the
Phase 5.1 deliverables. Diarization lands in a follow-up change.

The emotion classifier is load-bearing: Thymos already subscribes to
the audio-input emotion stream (see Thymos's `chronos_stream` /
`mnemos_stream` peer consumer; the social-affect signal is documented
in Thymos's spec) and will receive emotional contagion from the
speaker's voice.

## What Changes

- Introduce `kaine.modules.audio_in` package split four files:
  - `stt_client.py` — `STTClient` protocol + `SpeachesClient` default
    (httpx multipart POST to `http://127.0.0.1:8000/v1/audio/transcriptions`)
    + `FakeSTTClient` for tests.
  - `emotion.py` — `EmotionClassifier` protocol + `Funasr Emotion2vecClassifier`
    (lazy-imports `funasr`, loads `emotion2vec/emotion2vec_plus_base`,
    CPU-only) + `FakeEmotionClassifier` deterministic stand-in. The
    funasr classifier degrades to neutral with a one-time warning if
    funasr isn't installed (it's listed as an optional `[audio]`
    extra).
  - `module.py` — `AudioInput(BaseModule)`. Exposes
    `async process_audio(audio_bytes, sample_rate, *, source_label)`
    that runs STT and emotion classification in parallel
    (asyncio.gather) and publishes two events per call:
    `audio.in.transcription` and `audio.in.emotion`. The publish
    stream is `audio.in.out`.
- Add `funasr` to a new `[project.optional-dependencies] audio` extra
  in `pyproject.toml`. The default install does not pull funasr; the
  module's emotion classifier degrades gracefully when funasr isn't
  available.
- `[audio_in]` block in `config/kaine.toml`: Speaches URL, STT model
  name, emotion2vec model id, sample rate, baseline salience.
  `modules.audio_in = false`.
- Tests use `FakeSTTClient` + `FakeEmotionClassifier`. Opt-in test
  (`KAINE_AUDIO_IN_RUN_REAL=1`) actually exercises Speaches.

## Capabilities

### New Capabilities

- `audio-input`: STT + speech emotion recognition. Owns the Speaches
  HTTP client, the emotion2vec+ classifier wrapper, and the
  `audio.in.out` publish path.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `module-pattern`. Optional integration
  with Thymos (which already subscribes to audio.in.out for the
  emotional contagion signal).
- **Repo:** adds `kaine/modules/audio_in/*.py`, `tests/test_audio_in_*`,
  updates `pyproject.toml` (packages list + `[audio]` extra),
  `config/kaine.toml`.
- **Operator action:** the Speaches STT server (already installed at
  `~/.local/share/elite-tools/src/speaches/`) must be running for STT
  to actually return text. Without it the STT path fails per-call but
  the module continues. The emotion classifier silently degrades if
  funasr is not installed.
- **Optional install:** `pip install -e .[audio]` adds funasr (~heavy
  dep). The default `pip install -e .[test]` install stays small.
- **No runtime impact** on the cycle. AudioInput is registered in code
  paths but not auto-added to ModuleRegistry; first boot decides.
