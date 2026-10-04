## ADDED Requirements

### Requirement: The core reaches no install-time code, directly or indirectly
No import chain from `kaine.boot`, `kaine.cycle` or `kaine.workspace` SHALL reach `kaine.setup`, other than the declared remote-bridge exception for edge features. The language organ's runtime pieces (the model-server lifecycle, the served-model checks and the device map) SHALL live outside `kaine.setup`. The import contract SHALL forbid indirect imports.

#### Scenario: A runtime module imports setup tooling through another module
- **WHEN** a module the core imports, directly or through others, imports `kaine.setup`
- **THEN** the import contract check fails

#### Scenario: The model-server command line keeps working
- **WHEN** an operator runs `python -m kaine.setup.model_server status`
- **THEN** it runs the lifecycle in `kaine.organ_server`
