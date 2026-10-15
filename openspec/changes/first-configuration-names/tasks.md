## 1. Profile and loader

- [ ] 1.1 Rename `config/profiles/thesis_test.toml` to `config/profiles/first_configuration.toml` and reword its header.
- [ ] 1.2 `kaine/config.py`: default profile `first_configuration`; `thesis_test` resolves to it with one deprecation warning naming `ALIAS_LAST_RELEASE`, through `resolve_profile_name` and `load_kaine_config(profile=...)`.
- [ ] 1.3 Tests: the alias resolves, warns once, and yields the same merged config; the default applies `first_configuration`.

## 2. Wizard

- [ ] 2.1 `first_configuration_modules()` replaces `base_thesis_modules()`, which stays as a deprecated alias; the module step's prompt and labels say "first configuration"; `b` keeps its meaning.

## 3. Text

- [ ] 3.1 Dashboard evaluation templates, benchmark and ablation messages, log text and comments in `kaine/`, `config/kaine.toml` and the `Dockerfile` say "first configuration" or "hypothesis".
- [ ] 3.2 Docs under `docs/` (not `docs/records/`) say "first configuration" and "hypothesis"; field guide, no em dashes.
- [ ] 3.3 Rename `openspec/specs/thesis-test-configuration/` to `openspec/specs/first-configuration/` and the delta folder in `local-precision-global-gain`; live specs and active changes use the new profile name.
- [ ] 3.4 Rename `tests/test_thesis_test_profile.py` and `tests/test_base_thesis_profile.py`; update tests that name the profile.

## 4. Check

- [ ] 4.1 `openspec validate first-configuration-names --strict`; the full test suite.
