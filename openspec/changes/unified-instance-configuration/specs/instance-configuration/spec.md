# Spec Delta

## Purpose

Collect, document, and validate every configurable value for a KAINE instance so that
an operator can set up a new entity from a single reference, with clear explanations
and sensible defaults.

## ADDED Requirements

### Requirement: Configuration reference file
The project SHALL ship a `config/kaine.reference.toml` that contains every
configurable key recognized by `load_kaine_config()`, grouped by section, with its
default value and a brief inline comment explaining what the key controls and when an
operator would change it. The reference file SHALL NOT be loaded at runtime. It is
documentation, not config.

#### Scenario: A new config key added without a reference entry
- **WHEN** a module adds a new configuration key to its defaults
- **THEN** a test fails naming the key and the section it belongs to

### Requirement: Reference stays in sync with defaults
The reference file SHALL be generated from or validated against the actual defaults in
`load_kaine_config()`. A CI check SHALL fail if the reference file and the runtime
defaults disagree on any key or default value.

#### Scenario: Reference drifts from runtime defaults
- **WHEN** `load_kaine_config()` returns a default value for a key that differs from the reference
- **THEN** the sync check fails and names the key

### Requirement: Configuration validation command
The system SHALL provide a `python -m kaine.setup.validate_config` command that reads
an operator override file and reports: unknown keys not in the reference, values
outside any documented bounds, and missing keys that have no default and must be set.
The command SHALL exit 0 when everything is valid and nonzero otherwise.

#### Scenario: Unknown key in operator override
- **WHEN** `kaine.operator.toml` contains a key not present in the reference
- **THEN** the validation command warns about the unknown key

#### Scenario: Value outside documented bounds
- **WHEN** `kaine.operator.toml` sets `[cycle].processing_rate_hz = 500`
- **THEN** the validation command reports the value exceeds the documented upper bound

### Requirement: Progressive disclosure in documentation
The reference file SHALL mark each key with a tier: `basic` (asked during first-run
setup), `standard` (common adjustments), or `advanced` (rarely changed, requires
understanding of internals). The inline comments SHALL avoid jargon and explain the
practical effect of each value in plain terms.

#### Scenario: An operator looks up a basic key
- **WHEN** an operator opens the reference and searches for how to enable a module
- **THEN** the key is marked `# tier: basic` and the comment explains the effect without referencing internal code

### Requirement: Questionnaire mode
The system SHALL provide a `python -m kaine.setup.configure` command that walks the
operator through the reference file section by section, showing the current value,
the default, and the explanation for each key. By default it asks only `basic`-tier
keys. With `--full` it covers all tiers. Answers are written to
`kaine.operator.toml`.

#### Scenario: Basic questionnaire
- **WHEN** an operator runs `python -m kaine.setup.configure`
- **THEN** only `basic`-tier keys are presented, and the resulting `kaine.operator.toml` contains only the keys the operator changed from their defaults
