# CI hygiene and unified-config repair

- [x] 1.1 Add `__version__` to `kaine/__init__.py` resolved from package metadata (`importlib.metadata.version("kaine")`), with a safe fallback.
- [x] 1.2 Add the SPDX license header to the 14 files missing it: `kaine/__init__.py`, `kaine/audio.py`, `kaine/cli.py`, `kaine/preboot/__main__.py` (removed in 3.1), `kaine/questionnaire.py`, `kaine/setup/configure.py`, `scripts/check_config_reference.py`, `scripts/check_reference_explanations.py`, `scripts/generate_reference_config.py`, `tests/test_checkpoint_config.py`, `tests/test_config_defaults.py`, `tests/test_config_reference_drift.py`, `tests/test_config_validation.py`, `tests/test_wizard_basic_coverage.py`.
- [x] 1.3 Add `maternal_voice_data/sources/*` (`.txt`, `.licence.md`) to the `kaine.modules.audition` package-data glob in `pyproject.toml`.
- [x] 1.4 Classify `audio`, `cli`, `questionnaire` in `tests/test_import_contract_coverage.py` (add to the appropriate contract source_modules or an honest EXEMPT entry with a reason).
- [x] 2.1 Promote `[storage]` (data_root, min_free_gb) and `vocal.qwen3_device`/`vocal.qwen3_dtype` to uncommented defaults in `config/kaine.toml` so `list_all_defaults()` covers every runtime-resolvable key.
- [x] 2.2 Verify `tests/test_config_defaults.py` passes after 2.1 (no code change expected; confirms the fix).
- [x] 3.1 Remove the `kaine/preboot/__main__.py` stub and append a `ConfigValid` check to `kaine/preboot.py` that calls `validate_config_shape` on the merged config; append only, preserve all existing checks.
- [x] 3.2 Add a test that the preboot ConfigValid row runs and reports PASS on a valid merged config.
- [x] 4.1 Rewrite `scripts/generate_reference_config.py` to consume the dict from `list_all_defaults()` and emit valid TOML keyed by section, with inline `# tier: ...  bounds: ...` placeholders.
- [x] 4.2 Add a `tier_for_key(key) -> str` helper in `kaine/config.py` backed by a `TIER_BY_KEY` map (default `standard`), covering at least the `basic`-tier keys the wizard must ask.
- [x] 4.3 Update `kaine/setup/configure.py` to consult `tier_for_key` so `--full` covers all tiers and the default covers only `basic`.
- [x] 4.4 Regenerate `config/kaine.reference.toml` via the fixed generator; ensure `check_config_reference.py` and `check_reference_explanations.py` pass.
- [x] 4.5 Hand-write inline explanations (replacing placeholder text) for every key in `config/kaine.reference.toml`; no `TODO` tokens.
- [x] 5.1 Run the targeted offline test suite (config, preboot, license, import-contract, manifest) and confirm green.
- [x] 5.2 Update `docs/appendix-d-roadmap.md` unified-config progress to reflect repaired state.
- [x] 5.3 Update `.dark-factory-triage.md` to clear the two blocked failures once verified.
