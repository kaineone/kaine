## ADDED Requirements

### Requirement: Application-layer at-rest encryption for cognitive state files
The `StateEncryptor` SHALL encrypt and decrypt the following at-rest state files
using AES-256-GCM when `[security.state_encryption].enabled` is true:
`state/eidolon/self_model.json`, all files under `state/phantasia/` (DreamerV3
checkpoints and latent states), and all sidecar JSONL files under
`state/evaluation/observers/`. When `enabled` is false the
`StateEncryptor` SHALL be a no-op pass-through so all existing code paths work
unchanged.

#### Scenario: State file is encrypted on write when enabled
- **WHEN** `[security.state_encryption].enabled` is true and a state file is
  written
- **THEN** the file on disk is AES-256-GCM encrypted and not human-readable

#### Scenario: State file is decrypted on read when enabled
- **WHEN** `[security.state_encryption].enabled` is true and a state file is read
- **THEN** the decrypted content is returned and the calling module is unaware of
  the encryption

#### Scenario: Encryption is a no-op when disabled
- **WHEN** `[security.state_encryption].enabled` is false
- **THEN** files are written and read as plaintext and no encryption library is
  invoked

### Requirement: Key loaded from environment or kernel keyring
The `StateEncryptor` SHALL load the encryption key from the environment variable
named by `key_env_var` (default `KAINE_STATE_KEY`). If the env var is absent, it
SHALL attempt to load from the Linux kernel keyring. If neither source is
available and `enabled` is true, it SHALL raise a configuration error at startup
rather than proceeding without a key.

#### Scenario: Key missing with encryption enabled raises error at startup
- **WHEN** `enabled` is true and neither `KAINE_STATE_KEY` nor the keyring
  provides a key
- **THEN** startup raises a `CryptoConfigError` and the entity does not boot

### Requirement: Fork/merge export bundles are encrypted
Fork/merge state export bundles SHALL be encrypted before writing to `state/forks/`
and decrypted on import when `[security.state_encryption].enabled` is true. The
encryption key MUST be communicated out-of-band for cross-host transfers.

#### Scenario: Fork export bundle is encrypted
- **WHEN** a fork export is produced with encryption enabled
- **THEN** the export file is AES-256-GCM encrypted

#### Scenario: Fork import decrypts the bundle
- **WHEN** an encrypted fork bundle is imported with the correct key
- **THEN** the state is successfully restored

### Requirement: SECURITY.md names all v4 at-rest state files
SECURITY.md §4 SHALL enumerate all new v4 at-rest state files (Empatheia Qdrant
collection, Phantasia world-model checkpoints, sidecar JSONL logs under
`state/evaluation/observers/`) alongside the v1 files, noting which gain
application-layer encryption under this change and which remain OS-layer
operator responsibility.

#### Scenario: SECURITY.md is updated
- **WHEN** this change is implemented
- **THEN** SECURITY.md §4 contains a named list of all v4 at-rest state files
  and their protection posture
