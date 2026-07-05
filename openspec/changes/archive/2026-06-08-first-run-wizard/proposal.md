## Why

Getting KAINE running today means hand-editing `config/kaine.toml` (which ships with every
module disabled), discovering served model/voice/STT names by curling services, installing the right
optional extras for the chosen modules, and pinning devices per GPU — all undocumented-by-default and
error-prone. There is also no point at which a new operator is asked to recognize the CAL welfare/care
obligations they are taking on, or to make an informed, opt-in choice about research-metrics
submission. New operators need a guided front door.

This adds an interactive **first-run wizard** plus an **operator config-override layer** so the wizard
can persist choices without touching the shipped all-off `config/kaine.toml` (which a guard test pins
to all-disabled at HEAD). The existing `scripts/install.sh` (venv + multi-vendor torch wheel) becomes
the front of a complete flow that hands off to the wizard.

## What Changes

- A new shared `kaine.config.load_kaine_config()` SHALL load the shipped `config/kaine.toml` and
  deep-merge an optional, gitignored `config/kaine.operator.toml` over it (operator values win),
  before the existing secrets merge. The cycle entrypoint and the Nexus config readers SHALL use it,
  so operator overrides apply uniformly. The shipped `config/kaine.toml` remains all-off; the guard
  test (which reads HEAD) is unaffected.
- A new first-run wizard (`python -m kaine.setup`) SHALL guide the operator through, and write only to
  `config/kaine.operator.toml`:
  1. A brief orientation to KAINE and the key settings.
  2. **CAL welfare acknowledgement** — present the Article 4 care obligations and require an explicit
     typed acknowledgement before configuring an entity (firm and factual, not shaming).
  3. **Hardware scan** via `kaine.hardware.describe_host()` — detect CPU/GPUs (CUDA/ROCm/XPU/MPS) and
     VRAM, and propose device assignments (primary GPU for the LLM/training, secondary for
     vision/TTS, CPU for control paths), with graceful single-GPU/CPU fallback.
  4. **Module selection** — choose which of the modules to enable.
  5. **Model / voice / STT** — discover served options (Ollama `/api/tags`, Chatterbox
     `/get_predefined_voices`, Speaches `/v1/models`) when reachable, else accept manual entry, and
     record `[lingua].model_id`, `[vox].predefined_voice_id`, `[audition].stt_model`.
  6. **Optional extras** — offer to `pip install -e .[…]` the extras implied by the chosen modules
     (audio/vision/reasoning/training/worldmodel/oscillator), on explicit confirmation.
  7. **Research metrics** — explain the opt-in, metrics-only research submission and, only if the
     operator opts in, set `[research_submission]` (+ `[transfer]` recipient).
  8. **State encryption** — offer to enable `[security.state_encryption]` and explain the key
     requirement.
  9. **Summary + next steps** — env gates (`KAINE_*_OPERATOR_PRESENT`, approvals), service bring-up
     commands, and how to launch.
  The wizard SHALL support a non-interactive mode (injected answers / `--defaults`) for testing, and
  SHALL never enable an entity automatically (no boot; it only writes config).
- `scripts/install.sh` / `install.py` SHALL, after a successful install, offer to launch the wizard.
- New operator-facing docs SHALL cover the install→wizard→first-boot flow.

## Capabilities

### New Capabilities

- `first-run-wizard`: the operator config-override layer and the guided first-run setup wizard
  (license acknowledgement, hardware-scanned auto-config, module/model/voice/extras selection,
  opt-in metrics, persisted to `config/kaine.operator.toml`).

## Impact

- **Code (new)**: `kaine/config.py` (shared loader + deep-merge), `kaine/setup/` (the wizard +
  `__main__`).
- **Code (edit)**: `kaine/cycle/__main__.py` and `kaine/nexus/__main__.py` (use the shared loader);
  `scripts/install.sh` / `install.py` (offer the wizard); `.gitignore` (`config/kaine.operator.toml`).
- **Docs**: install/first-run flow in `docs/getting-started.md` (+ FIRST_BOOT pointer).
- **Tests**: deep-merge precedence (operator over shipped); wizard writes a correct
  `kaine.operator.toml` from injected answers; CAL acknowledgement required; hardware-scan device
  suggestions from a mocked `describe_host`; metrics opt-in only when chosen; non-interactive mode;
  the shipped `config/kaine.toml` stays all-off (guard intact).
- **Safety**: the wizard configures but never boots; the shipped config stays all-off; operator
  overrides are local and gitignored.
