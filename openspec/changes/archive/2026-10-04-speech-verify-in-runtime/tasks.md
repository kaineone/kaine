## 1. Move
- [x] 1.1 `kaine/speech_manifest.py` holds the manifest and the verification checks, moved verbatim (one `_sha256_file`).
- [x] 1.2 `kaine.setup.speech_models` keeps install and fetch, and imports what it uses from the runtime module.
- [x] 1.3 The sherpa STT and TTS modules, the Nexus health probes and the Nexus health config import runtime modules only.
- [x] 1.4 `kaine.speech_manifest` joins the boundary-neutral contract.

## 2. Tests
- [x] 2.1 No import chain from the sherpa modules or the Nexus health probes to `kaine.setup`.
- [x] 2.2 setup's manifest and `is_installed` are the same objects as the manifest module's.
- [x] 2.3 `kaine/setup/speech_models.py` defines no `_sha256_file`.
- [x] 2.4 The speech-health test patches the defaults where the probes now read them.

## 3. Follow-up
- [x] 3.1 Record the remaining organ-related indirect chains in the proposal.
