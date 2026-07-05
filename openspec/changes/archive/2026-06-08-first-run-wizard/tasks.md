# Tasks

## 1. Operator config-override layer (`kaine/config.py`)
- [x] 1.1 `load_kaine_config(path="config/kaine.toml", operator_path="config/kaine.operator.toml") -> dict` — load shipped toml, deep-merge operator override on top (operator wins; recursive dict merge). Pure; missing operator file = shipped only.
- [x] 1.2 Cycle entrypoint `_load_kaine_config` uses it (then the existing qdrant-secret merge). Nexus readers (`_load_lifecycle_config`, `_load_security_state_encryption_config`, `load_health_prober` kaine.toml reads) use it too.
- [x] 1.3 `.gitignore`: add `config/kaine.operator.toml`.

## 2. Wizard (`kaine/setup/__main__.py` + helpers)
- [x] 2.1 Orientation + step framework; `input_fn`/`out` injectable; `--defaults`/non-interactive mode; never boots.
- [x] 2.2 CAL welfare acknowledgement (Article 4 obligations; typed ack required; firm/factual).
- [x] 2.3 Hardware scan via `describe_host()`; propose device assignments (primary/secondary GPU, CPU fallback) for the device keys.
- [x] 2.4 Module selection → `[modules]`.
- [x] 2.5 Model/voice/STT discovery (Ollama /api/tags, Chatterbox /get_predefined_voices, Speaches /v1/models) when reachable, else manual → `[lingua].model_id`, `[vox].predefined_voice_id`, `[audition].stt_model`.
- [x] 2.6 Optional extras offer (`pip install -e .[…]` per chosen modules; confirmed).
- [x] 2.7 Research-metrics opt-in → `[research_submission]` (+ `[transfer]` recipient) only if opted in.
- [x] 2.8 State-encryption opt-in → `[security.state_encryption]` (+ key guidance).
- [x] 2.9 Write `config/kaine.operator.toml`; print summary + next steps (env gates, service commands, launch).

## 3. Installer hand-off
- [x] 3.1 `scripts/install.sh` + `install.py`: after install, offer to launch `python -m kaine.setup`.

## 4. Docs
- [x] 4.1 `docs/getting-started.md`: install → wizard → first-boot flow (present-tense; no changelog framing). FIRST_BOOT pointer.

## 5. Headers + tests
- [x] 5.1 Run `scripts/apply_license_headers.py` (new .py carry the SPDX header).
- [x] 5.2 Tests: deep-merge precedence (operator over shipped, nested); wizard writes correct operator.toml from injected answers; CAL ack required (refuses without); device suggestions from a mocked describe_host (multi-GPU, single-GPU, CPU); metrics set only when opted in; non-interactive `--defaults`; shipped `config/kaine.toml` still all-off (guard intact).

## 6. Verify
- [x] 6.1 `.venv/bin/pytest -q -p no:cacheprovider` green (incl. license-header + boot guards).
- [x] 6.2 `python -m kaine.setup --defaults` (non-interactive) writes a valid `config/kaine.operator.toml`; `load_kaine_config()` reflects the override.
- [x] 6.3 `openspec validate first-run-wizard --strict` passes.
