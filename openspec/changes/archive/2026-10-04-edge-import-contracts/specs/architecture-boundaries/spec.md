## ADDED Requirements

### Requirement: The core runtime does not import edge features
The boot, cycle and workspace packages SHALL NOT import the install, setup, transfer, distributed, remote, wheel-index or research-export packages. The only declared exception is the cycle entry point's import of the remote bridge, which is to move into an optional-components boot phase. The rule SHALL be enforced by a structural import contract in the required CI gate.

#### Scenario: A new edge import fails CI
- **WHEN** a module under `kaine.boot`, `kaine.cycle` or `kaine.workspace` imports `kaine.setup` (or another edge package)
- **THEN** `lint-imports` reports the contract as broken and the required CI gate fails

#### Scenario: Shared defaults live in neutral modules
- **WHEN** the runtime needs a speech-model default or the organ content check
- **THEN** it imports them from `kaine.model_paths` or `kaine.organ_probe`, not from `kaine.setup`
