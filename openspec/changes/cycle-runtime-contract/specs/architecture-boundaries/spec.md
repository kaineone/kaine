## MODIFIED Requirements

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
