## ADDED Requirements

### Requirement: The runtime verifies speech models without importing setup
The speech-model manifest and the integrity check run before a speech model loads SHALL live outside `kaine.setup`, in a module that imports only the standard library and `kaine.model_paths`. The runtime speech modules and the Nexus health probes SHALL NOT import `kaine.setup`, directly or indirectly. `kaine.setup.speech_models` SHALL re-export those names for install-time callers.

#### Scenario: The speech modules do not reach setup
- **WHEN** the import graph is built
- **THEN** there is no chain from the sherpa STT or TTS module, or from the Nexus health probes, to `kaine.setup`

#### Scenario: Setup callers see the same objects
- **WHEN** install-time code reads `verify_model_dir`, `is_installed`, `validate_tokens_file` or `MANIFEST` from `kaine.setup.speech_models`
- **THEN** each is the same object the runtime module defines
