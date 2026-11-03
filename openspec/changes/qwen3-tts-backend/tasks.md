## Tasks

- [x] 1. `qwen3_tts.py`: Qwen3TTS client class implementing TTSClient protocol, with unload/ensure_loaded.
- [x] 2. `mapping.py`: `affect_to_instruct` — map valence/arousal/dominance to Qwen3-TTS instruct string.
- [x] 3. `vocal.py` factory: register `"qwen3_tts"` backend, config keys, validation.
- [x] 4. `kaine.toml`: add qwen3 config keys (commented out).
- [x] 5. `episodic_own_content.py`: add `"qwen3_tts"` to VOCAL_BACKENDS, `"instruct"` and `"language"` to VOCAL_PROSODY.
- [x] 6. `health/config.py`: qwen3_tts backend health probe.
- [x] 7. `extras.py`: require `qwen-tts` when backend is `qwen3_tts`; `pyproject.toml` extra `speech-qwen3`.
- [x] 8. Tests: 17 unit tests for Qwen3TTS + 9 affect_to_instruct mapping tests + episodic own-content union assertion.
- [x] 9. Worker review (beam:cloud) + Claude adversarial review. Findings fixed: double ticket.release(), speed_factor removed from APPLIED_PROSODY, missing pyproject.toml extra, bare else in factory.
- [ ] 10. Merge.
