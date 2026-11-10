# Tasks

## 1. Update Qwen3-TTS client defaults

- [ ] 1.1 In `kaine/modules/vocal/qwen3_tts.py`, change the `model_id` field default from `"Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"` to `"kaineone/Qwen3-TTS-Sam-0.6B"` and change the `speaker` field default from `""` to `"sam"`. Verify: `grep -n 'kaineone/Qwen3-TTS-Sam' kaine/modules/vocal/qwen3_tts.py` shows the new model ID; `grep -n "speaker.*sam" kaine/modules/vocal/qwen3_tts.py` shows the new speaker default.

## 2. Update boot factory defaults

- [ ] 2.1 In `kaine/boot/factories/vocal.py`, change the fallback `model_id` in `_qwen3_factory()` from `"Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"` to `"kaineone/Qwen3-TTS-Sam-0.6B"` and the fallback speaker from `""` to `"sam"`. Verify: `grep -n 'kaineone/Qwen3-TTS-Sam' kaine/boot/factories/vocal.py` shows the updated default; `grep -n 'sam' kaine/boot/factories/vocal.py` shows the speaker fallback.

## 3. Update shipped config comments

- [ ] 3.1 In `config/kaine.toml`, update the commented-out `qwen3_model_id` to `"kaineone/Qwen3-TTS-Sam-0.6B"` and the commented-out `qwen3_speaker` to `"sam"`. Verify: `grep 'qwen3_model_id' config/kaine.toml` and `grep 'qwen3_speaker' config/kaine.toml` show the updated commented values.

## 4. Add Qwen3-TTS model to provisioning plan

- [ ] 4.1 In `kaine/setup/provision.py`, add a conditional block in `aux_models()` that appends an `AuxModel` for `kaineone/Qwen3-TTS-Sam-0.6B` when the vocal backend is `"qwen3_tts"`, mirroring the existing Chatterbox block. Verify: reading `provision.py` shows the new `AuxModel` entry gated on backend `"qwen3_tts"`.

## 5. Integration verification

- [ ] 5.1 Run `python -m py_compile kaine/modules/vocal/qwen3_tts.py kaine/boot/factories/vocal.py kaine/setup/provision.py` to confirm no syntax errors. Verify: exit code 0.
- [ ] 5.2 Run the project's static analysis gate (`python -m ruff check kaine/modules/vocal/qwen3_tts.py kaine/boot/factories/vocal.py kaine/setup/provision.py`) and confirm no new violations. Verify: exit code 0.
- [ ] 5.3 Confirm no reference to the old default `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` remains in any of the four changed files. Verify: `grep -r 'Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice' kaine/modules/vocal/qwen3_tts.py kaine/boot/factories/vocal.py kaine/setup/provision.py config/kaine.toml` returns no matches.

## Workflow follow-up

- Push the implementation branch as a GitHub PR.
- First-pass review by an Ollama worker model.
- Adversarial review by Claude; address any findings.
- Merge to main once the PR is clean.
- Archive the change after merge.
