## Why

At the 7th Models of Consciousness conference (MoC7, 2026-10-15) consciousness researchers read "thesis" and "base-thesis form" as a claim about a theory of consciousness, not as the name of a run configuration. The paper, the poster and the website now say "the first configuration" for the module set the first runs use, and "the hypothesis" for what that configuration tests (paper #44). The software still calls that set the `thesis_test` profile, the setup wizard offers a "base thesis" preset, the dashboard says "architecture-thesis instrumentation", the development benchmarks print "does not test the thesis", and the docs use "base-thesis" throughout. The code and docs follow the paper.

## What Changes

- **The profile is renamed.** `config/profiles/thesis_test.toml` becomes `config/profiles/first_configuration.toml`, selected by `--profile first_configuration` or `KAINE_PROFILE=first_configuration`, and it is the default profile when none is given.
- **The old name stays readable for a bounded window.** `thesis_test` given to `--profile`, `KAINE_PROFILE` or `load_kaine_config(profile=...)` resolves to `first_configuration` and logs one deprecation warning naming the replacement and the last release that reads it, `ALIAS_LAST_RELEASE` from `kaine/legacy_names.py`, the same window the module rename uses. A deployment that pins `KAINE_PROFILE=thesis_test` keeps booting the same module set.
- **The setup wizard says "first configuration".** The module step offers "[b]ase: the first configuration, [f]ull entity, or [c]ustom?"; the `b` answer keeps its meaning, so scripted answers keep working. `base_thesis_modules()` becomes `first_configuration_modules()`, and the old name stays as a deprecated alias for the same window.
- **User-visible text follows the paper.** The dashboard's evaluation report, the benchmark and ablation messages, log text, comments in the shipped config and modules, the Dockerfile comment and the docs say "the first configuration" and "the hypothesis". Historical records (`docs/records/`, the OpenSpec archive) and the legacy-config test fixture keep the old words.
- **The spec folder is renamed.** `openspec/specs/thesis-test-configuration/` becomes `openspec/specs/first-configuration/`, with the matching delta folder in the active change `local-precision-global-gain`, as the module rename did for its spec folders. The other live specs and active changes that name the profile use the new name.

## Capabilities

### New Capabilities

### Modified Capabilities

- `configuration-loading`: the old profile name resolves to the new one with a deprecation warning.
- `first-run-wizard`: the module step offers the first configuration.

## Impact

- **Code:** `kaine/config.py`, `kaine/setup/wizard_core.py`, `kaine/setup/wizard.py`, `kaine/setup/wizard_steps.py`, `kaine/dashboard/templates/evaluation.html`, `kaine/dashboard/templates/_evaluation_sections.html`, `kaine/evaluation/benchmarks/`, comments in other modules, `config/kaine.toml`, `config/profiles/`, `Dockerfile`.
- **Tests:** `tests/test_thesis_test_profile.py` and `tests/test_base_thesis_profile.py` are renamed; tests that name the profile use the new name; a new test covers the alias and its warning.
- **Operators:** nothing breaks. A pinned `thesis_test` keeps working with a warning until `ALIAS_LAST_RELEASE`; `functional-module-names-drop-aliases` removes it with the other aliases.
- **Docs:** 49 files under `docs/`.
