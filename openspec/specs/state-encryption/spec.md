# state-encryption Specification

## Purpose
At-rest encryption of the entity's cognitive-state files, how its key is supplied, and the rule that no process reads or writes that state through a disabled encryptor because its configuration or key could not be loaded.

## Requirements

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

### Requirement: A configuration error never disables encryption
A component that reads `[security.state_encryption]` SHALL NOT treat a configuration that cannot be loaded or validated as a disabled or empty encryption section; it SHALL raise a configuration error. A process that performs cognitive-state file I/O SHALL NOT perform that I/O when its configured encryption posture could not be installed (for example the configuration failed to load or validate, or encryption is enabled and no key is available); it SHALL log an error naming the cause and leave those state operations unavailable instead of falling back to the disabled pass-through encryptor.

#### Scenario: Malformed configuration at Nexus startup
- **WHEN** Nexus reads the state-encryption section and the configuration fails to load or validate
- **THEN** Nexus logs an error naming the cause, does not construct its fork manager, and performs no fork or merge state I/O

#### Scenario: Encryption enabled without a key at Nexus startup
- **WHEN** `[security.state_encryption].enabled` is true and no key is available when Nexus starts
- **THEN** Nexus logs an error naming the missing key, does not construct its fork manager, and never writes a fork snapshot in plaintext

#### Scenario: Decommission cannot install the encryption posture
- **WHEN** `python -m kaine.lifecycle` (decommission) starts and the merged configuration cannot be loaded or validated, or the state-encryption posture cannot be installed
- **THEN** it reports a configuration error and exits before assessing divergence, capturing a backup or deleting anything, so it never judges or copies encrypted state through the pass-through encryptor

#### Scenario: Nexus reports disabled fork operations
- **WHEN** Nexus has no fork manager (the encryption posture could not be installed, or the fork manager could not be constructed)
- **THEN** the fork listing reports that fork operations are unavailable, with the actual reason, instead of an empty list of forks

#### Scenario: Encrypted state with encryption disabled stops decommission
- **WHEN** the decommission CLI finds a cognitive-state file carrying the encryption header while the installed encryptor is disabled
- **THEN** it refuses with a configuration error and exit status 6 before assessing divergence, capturing a backup or deleting anything, because it could neither read that state for the welfare assessment nor back it up faithfully
