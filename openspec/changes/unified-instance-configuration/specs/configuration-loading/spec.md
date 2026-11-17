# Spec Delta

## Purpose

Load and merge the shipped configuration, operator overrides, secrets, and environment
variables into a single resolved config used by every KAINE component.

## ADDED Requirements

### Requirement: All defaults discoverable
`load_kaine_config()` SHALL expose a `list_all_defaults()` function (or equivalent)
that returns every recognized key with its default value and section. This is the
single source of truth for the reference file generator and the validation command.

#### Scenario: A module adds a config key without registering a default
- **WHEN** a module reads a config key at runtime that `list_all_defaults()` does not know about
- **THEN** a test fails naming the unregistered key

### Requirement: Bounds metadata
Each config key SHALL be able to declare an optional bounds tuple `(min, max)` or an enum of valid
values. The validation command uses these bounds. Keys without declared bounds accept
any value of the correct type.

#### Scenario: Bounds declared for processing rate
- **WHEN** `[cycle].processing_rate_hz` declares bounds `(0.1, 100.0)`
- **THEN** the validation command rejects values outside that range
