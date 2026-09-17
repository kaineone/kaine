## MODIFIED Requirements

### Requirement: Application-layer at-rest encryption for cognitive state files
The `StateEncryptor` SHALL encrypt and decrypt the following at-rest state files using AES-256-GCM when `[security.state_encryption].enabled` is true: `state/eidolon/self_model.json`, all files under `state/phantasia/` (DreamerV3 checkpoints and latent states), and all sidecar JSONL files under `state/evaluation/observers/`. When `enabled` is false the `StateEncryptor` SHALL be a no-op pass-through so all existing code paths work unchanged. The shipped default SHALL enable encryption automatically when a key is resolvable, and SHALL warn loudly at boot when plaintext persistence is chosen.

#### Scenario: State file is encrypted on write when enabled
- **WHEN** `[security.state_encryption].enabled` is true and a state file is written
- **THEN** the file on disk is AES-256-GCM encrypted and not human-readable

#### Scenario: State file is decrypted on read when enabled
- **WHEN** `[security.state_encryption].enabled` is true and a state file is read
- **THEN** the decrypted content is returned and the calling module is unaware of the encryption

#### Scenario: Encryption defaults to enabled when a key is present
- **WHEN** the entity boots with `KAINE_STATE_KEY` or the kernel keyring providing a valid key and `[security.state_encryption].enabled` is not explicitly set
- **THEN** encryption is enabled and state files are written encrypted

#### Scenario: Plaintext persistence warns the operator
- **WHEN** `[security.state_encryption].enabled` is explicitly false
- **THEN** the entity boots but logs a prominent warning that cognitive state is being persisted in plaintext

#### Scenario: Encryption is a no-op when disabled
- **WHEN** `[security.state_encryption].enabled` is false
- **THEN** files are written and read as plaintext and no encryption library is invoked
