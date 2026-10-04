# Speech-model verification belongs to the runtime, not setup

## Why

The complexity audit of 2026-10-03 (W6) asked for the runtime's indirect imports of `kaine.setup` to be moved out. Setup is install-time tooling. The import contract that keeps the core runtime clear of edge features had to allow indirect imports because of these chains:
- The sherpa-onnx speech modules, which boot builds, import `kaine.setup.speech_models` only to verify a model directory before loading it.
- The Nexus health probes and health config import it for the default model ids and the manifest.

`kaine/setup/speech_models.py` also defined `_sha256_file` twice; the second definition silently replaced the first.

## What changes

- **A new stdlib-only module, `kaine/speech_manifest.py`.** It holds the speech-model manifest (`SpeechModel`, `MANIFEST`) and the integrity checks the runtime runs before loading a model: `verify_model_dir`, `is_installed`, `validate_tokens_file` and the verified-marker reader. Each definition moves verbatim, except that `is_installed` names `speech_model_dir` directly instead of setup's `model_dir` alias.
- **`kaine.setup.speech_models` keeps install and fetch.** It re-exports the moved names, so callers and the CLI are unchanged. It keeps one `_sha256_file`, imported from the new module.
- **Runtime callers stop importing setup.** The sherpa STT and TTS modules import `kaine.speech_manifest`. The Nexus health probes and health config read the defaults from `kaine.model_paths` and the manifest from `kaine.speech_manifest`.
- **Contract.** `kaine.speech_manifest` joins `kaine.model_paths` in the boundary-neutral import contract.

## Remaining indirect chains (follow-up)

These remain, and all of them go through the organ's setup modules:
- `kaine.boot` → `kaine.modules.hypnos.organ_window` → `kaine.setup.model_server`;
- `kaine.cycle.input_check` → `kaine.preboot` → `kaine.setup.device_map`;
- `kaine.nexus.health.blocks` → `kaine.setup.organ`.

The organ window drives the model server's process lifecycle, which setup shares on purpose. Removing these chains means moving `model_server`, `organ` and `device_map` out of `kaine.setup` together, which is a change of its own.

## Impact

- **Behaviour:** none. Every check and message is unchanged.
- **Research:** none. No study is running.
