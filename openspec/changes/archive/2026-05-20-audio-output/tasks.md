## 1. Package + state

- [ ] 1.1 Add `kaine.modules.audio_out` to setuptools packages

## 2. Client

- [ ] 2.1 Implement `kaine/modules/audio_out/client.py` with `TTSClient` protocol, `TTSRequest` + `SynthesisResult` dataclasses, `ChatterboxClient` (httpx async, /tts endpoint), `FakeTTSClient` (scriptable byte responses)

## 3. Mapping

- [ ] 3.1 Implement `kaine/modules/audio_out/mapping.py` with `ChatterboxParams` dataclass + `affect_to_chatterbox(state) -> ChatterboxParams` pure function. Documented bands; strict monotonicity in arousal → exaggeration and |valence| → cfg_weight

## 4. Module

- [ ] 4.1 Implement `kaine/modules/audio_out/module.py` with `AudioOutput(BaseModule)`. Subscribes to lingua.external (synthesize trigger) and thymos.out (latest thymos.state cached for affect mapping). Publishes audio.out.synthesized with diagnostics-only payload. Writes audio to configured sink

## 5. Config

- [ ] 5.1 Add `[audio_out]` block to `config/kaine.toml`
- [ ] 5.2 Add `audio_out = false` under `[modules]`
- [ ] 5.3 Update `kaine/modules/__init__.py` to export `AudioOutput`

## 6. Tests

- [ ] 6.1 `tests/test_audio_out_mapping.py` — pure-function tests for affect_to_chatterbox monotonicity, clamping, baseline behavior
- [ ] 6.2 `tests/test_audio_out_client.py` — FakeTTSClient protocol satisfaction, request shape, error paths
- [ ] 6.3 `tests/test_audio_out_module.py` (fakeredis) — lingua.external → synthesize → sink file + bus event; thymos.state cached; bus event payload excludes audio bytes; opt-in real-Chatterbox test (`KAINE_AUDIO_OUT_RUN_REAL=1`)

## 7. Verification

- [ ] 7.1 Full unit suite passes
- [ ] 7.2 `openspec validate audio-output --strict` clean
- [ ] 7.3 Commit, merge, archive change, drop branch
