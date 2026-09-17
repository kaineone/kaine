## MODIFIED Requirements

### Requirement: Sidecar boundary enforced by a structural contract
The codebase SHALL enforce the core/evaluation sidecar boundary with a structural import-contract checker (not only a string grep): no module under `kaine/` may import `kaine.evaluation` except the two composition-root entrypoints (`kaine/cycle/__main__.py`, `kaine/nexus/__main__.py`). The source list SHALL include every top-level `kaine` package/module that exists in the codebase, so a new or previously omitted module cannot silently import the sidecar. The check SHALL run fast (pre-commit and a dedicated CI step, independent of the full test suite) and SHALL report a precise contract violation naming the offending module.

#### Scenario: A forbidden import fails fast with a precise message
- **WHEN** a core module under `kaine/` (other than the two allowed entrypoints) imports `kaine.evaluation`
- **THEN** the contract checker fails in the pre-commit/dedicated-CI step with a message naming the offending module and the violated contract — without requiring the full test suite

#### Scenario: The clean baseline passes
- **WHEN** the checker runs against a codebase where only the two entrypoints import `kaine.evaluation`
- **THEN** the contract passes

#### Scenario: Omitted top-level module is covered
- **WHEN** a new top-level module is added and it accidentally imports `kaine.evaluation`
- **THEN** the contract checker reports the violation because the module is in the source list
