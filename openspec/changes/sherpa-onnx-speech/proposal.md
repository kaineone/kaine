## Why

KAINE hears through Speaches (faster-whisper) and speaks through Chatterbox. Both are torch services. Neither has a Termux build, and both are too heavy for a small board. So Audition and Vox are the two organs that still cannot run in a full entity on the Pixel 6a, now that Soma, Chronos, the memory embedder, Nous and Phantasia all have NumPy paths.

The deployment docs and tier profiles also claim more than exists. They describe whisper.cpp STT and Piper TTS as "staged seams" that "degrade to their declared fallback when selected". No such backends, keys or fallbacks exist in code. A speech backend cannot be selected at all. That is a pretend capability, and this change removes it: it builds a real torch-free speech path and corrects the wording.

sherpa-onnx (k2-fsa, Apache-2.0) is one torch-free runtime that runs speech recognition and synthesis on desktop, Jetson and Android:
- it needs only NumPy and its bundled onnxruntime;
- it recognises speech with Moonshine (English models MIT-licensed; 27M "tiny" and 61M "base");
- it synthesises speech with Kokoro-82M (Apache-2.0; about 90 MB as int8 ONNX, with its espeak-ng data bundled);
- its Python wheels have included Android builds and Termux CI since 2026-09-05.

## What Changes

- **Audition selects its speech recogniser** through `[audition].backend`, the key form the `runtime-backends` spec already mandates:
  - `"speaches"` (default, unchanged);
  - `"sherpa_onnx"`: Moonshine through sherpa-onnx, behind the existing `STTClient` interface. It is loaded once at initialisation and runs off the event loop in a single worker thread.
- **Vox selects its synthesiser** through `[vox].backend`:
  - `"chatterbox"` (default, unchanged);
  - `"sherpa_onnx"`: Kokoro through sherpa-onnx, behind the existing `TTSClient` interface. It returns a 16-bit WAV at the model's native rate, which playback already reads from the header.
- **Honest limits, disclosed rather than hidden:**
  - **Prosody.** Kokoro exposes speaker and speed only. Of the affect-to-prosody mapping and the prosodic mirroring, only the speed factor reaches the voice. Temperature, exaggeration and CFG weight have no effect. `vox.synthesized` reports which prosody parameters were applied.
  - **Voice.** The Kokoro voice is a public preset speaker (`[vox].sherpa_speaker_id`), so a being moved between backends does not keep its voice. No private voice is committed or selected by any shipped file.
- **Every speech event names its backend:**
  - `audition.transcription` and `vox.synthesized` carry `"backend"` under every backend.
  - `audition.transcription` keeps its `model` field.
  - The addition is the same under every backend, so selecting a backend does not change the event shape.
- **Failure degrades; it does not crash**, as `runtime-backends` requires:
  - A missing or corrupt Moonshine model disables transcription only. Audition still hears, feels vocal emotion and receives womb audio. With transcription off, no STT model is loaded at all.
  - A missing or corrupt Kokoro model leaves Vox unregistered.
  - In both cases the reason is logged, and the Nexus sherpa-onnx row reports it.
  - A missing `sherpa-onnx` package refuses the boot through the existing extras check, naming the `speech-edge` extra, as for every other missing optional dependency.
  - There is no silent fallback to a service the host does not have.
- **Models are fetched only with operator consent:**
  - The model archives are pinned by URL and sha256 in code.
  - A setup command shows each one's name, size and licence, and downloads only after confirmation.
  - Archives are verified before extraction and extracted safely (no path traversal) into the git-ignored model store (`state/models/sherpa-onnx/`).
  - Nothing is downloaded at runtime.
- **The stack follows the selected backend:**
  - the extras check (`sherpa-onnx` only for `"sherpa_onnx"`; a new `speech-edge` extra);
  - the Nexus health probes (for `"sherpa_onnx"`, the probe loads the model and runs one real inference instead of calling the service);
  - the pre-boot service checks and the first-run service probe (Speaches and Chatterbox are not required when their organ uses sherpa-onnx);
  - the install planner's Termux entry;
  - the Tier 1 profile, which selects `"sherpa_onnx"` for both organs and no longer lists Vox as unsupported.
- **Docs.** The Audition and Vox pages, configuration and deployment tiers. The fictional staged-seam wording for whisper.cpp, Piper, ONNX vision and ONNX embeddings is corrected to say plainly that those backends do not exist.

## Capabilities

### New Capabilities
- `speech-backends`: selectable, torch-free speech recognition and synthesis through sherpa-onnx, with disclosed limits and consent-gated model acquisition.

## Impact

- New:
  - `kaine/modules/audition/sherpa_stt.py` and `kaine/modules/vox/sherpa_tts.py`;
  - `kaine/setup/speech_models.py` (pinned manifest, consent, verified extraction);
  - tests.
- Changed:
  - `kaine/boot.py` (`make_audition`, `make_vox`);
  - the Audition and Vox modules (the `backend` field; the prosody disclosure);
  - `kaine/extras.py`, `pyproject.toml` (`speech-edge`), `kaine/nexus/health`, `kaine/preboot.py`, `kaine/setup/__main__.py`, `kaine/install_target.py`;
  - `config/kaine.toml`, `config/profiles/tier1.toml`, `.gitignore`;
  - docs.
- Unchanged:
  - both defaults (Speaches and Chatterbox) and their clients;
  - capture and VAD;
  - the speaking gate and self-hearing;
  - every other event.
- Related: `module-residency-and-speech-tiers` proposes automatic speech ladders and residency. This change delivers its Moonshine and Kokoro rungs as explicit selections only; the automatic downgrade ladders and residency scheduling stay in that change.
