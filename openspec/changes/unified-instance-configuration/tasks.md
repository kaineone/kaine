Status: PARKED (roadmap item, not active work)

## 1. Defaults registry

- [x] 1.1 Add `list_all_defaults()` to `kaine/config.py` (or equivalent) that returns every recognized key, its section, default value, Python type, and optional bounds tuple.
- [x] 1.2 Test: every key that `load_kaine_config()` resolves at runtime appears in `list_all_defaults()`.
- [x] 1.3 Add tier metadata (`basic`, `standard`, `advanced`) to each key in the registry.

## 2. Reference file

- [x] 2.1 Generator script: reads `list_all_defaults()`, emits `config/kaine.reference.toml` with default values and structured comment placeholders (`# tier: ...  bounds: ...`).
- [ ] 2.2 Hand-write inline explanations for every key. Each explanation says what the key controls and when you would change it, in plain language.
- [ ] 2.3 CI check: the reference file's keys and defaults match `list_all_defaults()`. Fails on drift.
- [ ] 2.4 CI check: every reference entry has a non-placeholder explanation. Fails on `TODO` comments.

## 3. Validation command

- [ ] 3.1 `python -m kaine.setup.validate_config`: reads operator override, reports unknown keys, out-of-bounds values, and missing required keys.
- [ ] 3.2 Tests: unknown key warning, out-of-bounds error, valid config passes, missing required key error.
- [ ] 3.3 Pre-boot integration: add a `Config valid` row to `python -m kaine.preboot` that runs the validator.

## 4. Questionnaire mode

- [ ] 4.1 `python -m kaine.setup.configure`: walks through reference sections, shows current value and explanation, writes answers to `kaine.operator.toml`.
- [ ] 4.2 `--full` flag covers all tiers; default covers only `basic`.
- [ ] 4.3 Test: questionnaire presents exactly the `basic`-tier keys when run without `--full`.

## 5. Wizard sync

- [ ] 5.1 Test: every `basic`-tier key in the reference has a corresponding wizard question.
- [ ] 5.2 Update the wizard to cover any `basic`-tier keys it currently skips.

## 6. Documentation

- [ ] 6.1 Docs page explaining the config layers (shipped, operator override, secrets, env vars, tier profiles) and how to use the reference file and validation command.
- [ ] 6.2 Docs page with a walkthrough of first-time setup using the questionnaire.
