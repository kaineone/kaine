## ADDED Requirements

### Requirement: Revive at start and the research preflight use the configured encryption
The cycle SHALL install the configured state encryptor before it plans a revive or evaluates the research gate. A revive at start SHALL read an encrypted bundle with the configured key, and SHALL stop with the revive-refused exit code, without a traceback, when the key cannot decrypt it. The research gate's preflight preserve and revive round trip SHALL use the configured encryptor, so that when encryption is required the round trip writes and reads an encrypted bundle.

#### Scenario: Reviving an encrypted bundle
- **WHEN** the cycle starts with `--revive` on a bundle written with encryption on, and the same key is set
- **THEN** the bundle decrypts, the revive plan builds and the entity runs as the preserved individual

#### Scenario: The preflight under required encryption
- **WHEN** a research boot runs with `[preservation].require_encryption = true` and a key set
- **THEN** the preflight bundle is encrypted and the gate's revive decrypts it before the gate passes
