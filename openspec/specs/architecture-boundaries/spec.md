# architecture-boundaries Specification

## Purpose
Structural import contracts that keep KAINE's layers apart: the core runtime never imports the evaluation sidecar, and the other declared layering rules are checked on every change.

## Requirements

### Requirement: Sidecar boundary enforced by a structural contract
The codebase SHALL enforce the core/evaluation sidecar boundary with a structural
import-contract checker (not only a string grep): no module under `kaine/` may
import `kaine.evaluation` except the two composition-root entrypoints
(`kaine/cycle/__main__.py`, `kaine/nexus/__main__.py`). The check SHALL run fast
(pre-commit and a dedicated CI step, independent of the full test suite) and SHALL
report a precise contract violation naming the offending module.

#### Scenario: A forbidden import fails fast with a precise message
- **WHEN** a core module under `kaine/` (other than the two allowed entrypoints) imports `kaine.evaluation`
- **THEN** the contract checker fails in the pre-commit/dedicated-CI step with a message naming the offending module and the violated contract — without requiring the full test suite

#### Scenario: The clean baseline passes
- **WHEN** the checker runs against a codebase where only the two entrypoints import `kaine.evaluation`
- **THEN** the contract passes

### Requirement: Declared architectural layering
The import contracts MUST declare the project's real layering — at minimum that
`kaine.modules` does not import the cycle **runtime** (the engine/loop,
registry, preflight, boot, `__main__`, the Spot supervisor, and the
preservation/research monitors), with the pure data/contract module
`kaine.cycle.types` (`WorkspaceSnapshot`) as the single declared exception that
modules MAY import (directly or transitively); that `kaine.evaluation` does not
import Nexus internals; and that the boundary-neutral shared homes
(`kaine/persistence`, `kaine/experiment`, `kaine/privacy_filter`,
`kaine/text_embedding`, `kaine/lifecycle/welfare_signal`) depend on neither the
core-runtime nor the evaluation subsystem — so the layering is an enforced,
documented contract rather than an implicit convention. The cycle-runtime
boundary MUST cover every `kaine.cycle` submodule other than `kaine.cycle.types`,
including submodules added later, without the contract being edited.

#### Scenario: A layering violation is reported
- **WHEN** a module imports across a declared layer boundary in a forbidden direction
- **THEN** the contract checker reports it as a violation

#### Scenario: A new cycle submodule is covered
- **WHEN** a new runtime submodule is added under `kaine/cycle/` and a module imports it
- **THEN** the contract checker reports the violation with no change to the contract

### Requirement: The core runtime does not import edge features
The boot, cycle and workspace packages SHALL NOT import the install, setup, transfer, distributed, remote, wheel-index or research-export packages. The only declared exception is the cycle entry point's import of the remote bridge, which is to move into an optional-components boot phase. The rule SHALL be enforced by a structural import contract in the required CI gate.

#### Scenario: A new edge import fails CI
- **WHEN** a module under `kaine.boot`, `kaine.cycle` or `kaine.workspace` imports `kaine.setup` (or another edge package)
- **THEN** `lint-imports` reports the contract as broken and the required CI gate fails

#### Scenario: Shared defaults live in neutral modules
- **WHEN** the runtime needs a speech-model default or the organ content check
- **THEN** it imports them from `kaine.model_paths` or `kaine.organ_probe`, not from `kaine.setup`

### Requirement: The runtime verifies speech models without importing setup
The speech-model manifest and the integrity check run before a speech model loads SHALL live outside `kaine.setup`, in a module that imports only the standard library and `kaine.model_paths`. The runtime speech modules and the Nexus health probes SHALL NOT import `kaine.setup`, directly or indirectly. `kaine.setup.speech_models` SHALL import the manifest and the installed-model check from that module rather than keep its own copies.

#### Scenario: The speech modules do not reach setup
- **WHEN** the import graph is built
- **THEN** there is no chain from the sherpa STT or TTS module, or from the Nexus health probes, to `kaine.setup`

#### Scenario: Setup uses the runtime definitions
- **WHEN** install-time code reads `MANIFEST` or `is_installed` from `kaine.setup.speech_models`
- **THEN** each is the same object the runtime module defines

### Requirement: Module factories are independent
Each module factory SHALL live in its own module under `kaine.boot.factories`, and no factory module SHALL import another factory module. Helpers that several factories share SHALL live outside `kaine.boot.factories`. An import contract SHALL enforce this. `kaine.boot` SHALL re-export every factory and boot helper, so callers import from `kaine.boot` alone.

#### Scenario: A factory imports another factory
- **WHEN** one module under `kaine.boot.factories` imports another
- **THEN** the import contract check fails

#### Scenario: Callers keep importing from kaine.boot
- **WHEN** code imports a factory or boot helper from `kaine.boot`
- **THEN** it receives the object defined in the submodule
