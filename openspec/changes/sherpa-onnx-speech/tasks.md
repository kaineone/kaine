## 1. Models and consent

- [x] 1.1 `kaine/setup/speech_models.py`: pinned manifest (URL, sha256, size, licence), consent prompt, verified download, safe extraction, idempotence; the provisioning plan lists the archives when a sherpa backend is selected.
- [x] 1.2 Fetch the archives once on the development host and pin their digests (done in design; installing `sherpa-onnx` into the venv for the live tests needs the operator's consent).

## 2. Engines

- [x] 2.1 `SherpaMoonshineSTT` behind `STTClient`: WAV decode, single-thread executor, clear construction errors.
- [x] 2.2 `SherpaKokoroTTS` behind `TTSClient`: speed-only prosody, 16-bit WAV at the native rate, clear construction errors.

## 3. Wiring and disclosure

- [x] 3.1 `[audition].backend` / `[vox].backend` through `BackendRegistry` in boot; the new keys; failure disables the module with a surfaced reason.
- [x] 3.2 `backend` on `audition.transcription` and `vox.synthesized`; `prosody_applied` on `vox.synthesized`.
- [x] 3.3 Extras (`speech-edge`), health probes, pre-boot and first-run checks, install planner, Tier 1 profile, `.gitignore`.

## 4. Verification and docs

- [ ] 4.1 Unit tests with injected fakes (no sherpa needed); live tests that load the real models and transcribe a synthesised utterance (Kokoro → WAV → Moonshine round trip). Live tests are skipped only when the package or models are absent, and the PR records a run where they executed.
- [ ] 4.2 Docs: Audition, Vox, configuration, deployment tiers (including the staged-seam correction).
- [ ] 4.3 Offline suite green; `openspec validate sherpa-onnx-speech --strict`.
- [ ] 4.4 On-device: install on the Pixel 6a under Termux and run the live round trip there (operator step; record the result or leave this unchecked with the reason).
