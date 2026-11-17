# Proposal

Status: PARKED (roadmap item, not active work)

## Why

Configuring a new KAINE instance requires editing or understanding several separate
files (`config/kaine.toml`, `config/kaine.operator.toml`, `config/secrets.toml`,
`compose/*.yml`, tier profiles, study files) and knowing which knobs each module
exposes. The first-run wizard handles the initial operator override, but there is no
single reference that shows every configurable value, what it does, and what a
reasonable default looks like. An operator who wants to adjust one setting has to
search the shipped TOML, the docs, and sometimes the source to find the right key.

This matters now because the project is approaching its first entity boot. More
operators will touch the config. A scattered setup increases the chance of
misconfiguration and makes it harder to reproduce an environment across machines.

## What Changes

- A documented configuration reference that lists every configurable value across all
  modules, grouped by function rather than by internal module name, with a plain
  explanation of each value, its default, and when you would change it.
- A `config/kaine.reference.toml` file, shipped but never loaded, containing every
  key with its default and a brief inline comment. Operators copy sections into their
  `kaine.operator.toml` as needed. The reference file is generated from the same
  source of truth that `load_kaine_config()` uses for defaults.
- A configuration validation command (`python -m kaine.setup.validate_config`) that
  checks an operator override against the reference, warns on unknown keys, and
  reports values that fall outside documented bounds.
- Integration with the first-run wizard: the wizard already writes
  `kaine.operator.toml`; this change makes sure the wizard covers every section of
  the reference, and that the reference stays in sync with the wizard's questions.
- A future CLI questionnaire mode (beyond the wizard) that walks an operator through
  the full reference in sections, with progressive disclosure: basic setup first,
  advanced tuning behind an "advanced" flag. UI-based setup is a later goal and not
  part of this change.

## Capabilities

### New Capabilities

- `instance-configuration`: Collect, document, and validate all configurable values
  for a KAINE instance. Covers the reference file, the validation command, and the
  contract that every module's config keys appear in the reference with defaults and
  bounds.

### Modified Capabilities

- `first-run-wizard`: Extend the wizard to cover all sections of the configuration
  reference, so no configurable value is left out of the first-run flow.
- `configuration-loading`: Add a purpose section and requirements for the reference
  file and the validation command.

## Impact

- `config/kaine.toml` and `config/kaine.operator.toml`: unchanged in structure, but
  every key must also appear in the new reference file.
- `config/kaine.reference.toml`: new file, shipped, gittracked, never loaded at
  runtime. Generated or manually maintained.
- `kaine/setup/validate_config.py`: new module.
- `kaine/setup/wizard.py`: updated to cover all reference sections.
- `kaine/config.py` (or equivalent `load_kaine_config`): may gain a
  `list_all_defaults()` helper used by the reference generator and the validator.
- No runtime behavior changes. No breaking changes. This is tooling and documentation.
