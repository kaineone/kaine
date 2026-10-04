## 1. Neutral homes
- [x] 1.1 `kaine/model_paths.py` gains `DEFAULT_STT`, `DEFAULT_TTS` and `speech_model_dir(model_id, root=None)`; `kaine/setup/speech_models.py` re-exports them (keeping `model_dir` as its name there).
- [x] 1.2 New `kaine/organ_probe.py` holds `OrganContentResult`, `CONTENT_PROBE_TIMEOUT_S`, `verify_organ_generates`, `ORGAN_REVISION_STATE_PATH` and `read_revision_state`, moved verbatim; `kaine/setup/organ.py` re-exports them.

## 2. Callers
- [x] 2.1 `kaine/boot.py` and `kaine/cycle/__main__.py` import from the neutral homes.

## 3. Contract
- [x] 3.1 `pyproject.toml`: a forbidden contract "Core runtime stays clear of edge features", with the single ignore `kaine.cycle.__main__ -> kaine.remote.bridge` (until W5).
- [x] 3.2 `lint-imports` passes; the related tests pass.
