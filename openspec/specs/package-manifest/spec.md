# package-manifest Specification

## Purpose
This capability makes a built wheel carry every `kaine` package and the data files the runtime needs, so an installed KAINE runs the same as a source checkout.

## Requirements

### Requirement: A built wheel carries the whole runtime
A wheel built from the source tree SHALL contain every Python package under `kaine/` and every runtime data file there (everything except developer documentation). Packages SHALL be discovered rather than listed, so that a new package ships without a manifest edit.

#### Scenario: A new package is added
- **WHEN** a contributor adds a package under `kaine/` with an `__init__.py`
- **THEN** the next wheel contains it without any change to `pyproject.toml`

#### Scenario: Nexus is installed from a wheel
- **WHEN** KAINE is installed from a wheel rather than in editable mode
- **THEN** Nexus's templates, fonts and vendored scripts are present
