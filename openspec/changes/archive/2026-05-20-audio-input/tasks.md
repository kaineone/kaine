## 1. Package

- [ ] 1.1 Add `kaine.modules.audio_in` to setuptools packages
- [ ] 1.2 Add `[project.optional-dependencies]` `audio = ["funasr>=1.0,<2"]` to `pyproject.toml`

## 2. STT client

- [ ] 2.1 Implement `kaine/modules/audio_in/stt_client.py` with `STTClient` protocol, `TranscriptionResult` dataclass, `SpeachesClient` (httpx multipart POST), `FakeSTTClient`
- [ ] 2.2 Tests covering protocol satisfaction, fake behavior, request shape

## 3. Emotion classifier

- [ ] 3.1 Implement `kaine/modules/audio_in/emotion.py` with `EmotionClassifier` protocol, `EmotionResult` dataclass, the seven CATEGORIES enum, `Emotion2vecClassifier` (lazy funasr import + graceful fallback), `FakeEmotionClassifier`
- [ ] 3.2 Tests: protocol; fake returns scripted; emotion2vec missing-funasr fallback returns neutral

## 4. Module

- [ ] 4.1 Implement `kaine/modules/audio_in/module.py` with `AudioInput(BaseModule)` exposing process_audio() that runs both clients in parallel via asyncio.gather; publishes audio.in.transcription + audio.in.emotion regardless of partial failures
- [ ] 4.2 Update `kaine/modules/__init__.py` exports

## 5. Config

- [ ] 5.1 Add `[audio_in]` block to `config/kaine.toml`
- [ ] 5.2 Add `audio_in = false` under `[modules]`

## 6. Module tests

- [ ] 6.1 `tests/test_audio_in_module.py`: two-events-per-call, payload shapes, STT-failure-degradation, ser/de, opt-in `KAINE_AUDIO_IN_RUN_REAL=1` test against Speaches

## 7. Verification + Phase 5 tag

- [ ] 7.1 Full unit suite passes
- [ ] 7.2 `openspec validate audio-input --strict` clean
- [ ] 7.3 Commit, merge, archive change, drop branch
- [ ] 7.4 Tag `v0.5-action` (closes Phase 5: audio in, Lingua, audio out, faithful renderer, Praxis all done)
