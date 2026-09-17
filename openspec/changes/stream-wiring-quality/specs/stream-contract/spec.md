## Purpose

Provide canonical stream names and validation so modules, Nexus, evaluation, and configuration never drift on which stream carries which signal.

## ADDED Requirements

### Requirement: Stream names are derived from a single canonical source
All consumers of module output streams SHALL derive the stream name from `kaine.bus.schema.module_stream()` or from shared constants exported by the producing module, rather than hard-coding raw string literals.

#### Scenario: Module stream derivation is used in consumers
- **WHEN** `grep -rn "lingua\.out\|thymos\.out\|mnemos\.out" kaine/ tests/ config/` is run
- **THEN** the only matches are in `kaine/bus/schema.py`, module definitions, or the canonical constants module

#### Scenario: Renaming a module updates all consumers
- **WHEN** a module's registered name changes
- **THEN** `module_stream()` returns the new stream name and all consumers follow without manual edits

### Requirement: Stream-registry drift test catches hard-coded literals
`tests/test_stream_registry_drift.py` SHALL assert that every stream constant declared in evaluation observers equals the value produced by `kaine.evaluation.stream_registry`, and SHALL fail if any observer hard-codes a stream name.

#### Scenario: Observer with hard-coded stream name fails CI
- **WHEN** an evaluation observer declares a stream literal that does not match `stream_registry`
- **THEN** `tests/test_stream_registry_drift.py` fails

#### Scenario: Canonical constants pass drift test
- **WHEN** all observers import stream names from `stream_registry` or module constants
- **THEN** the drift test passes
