## MODIFIED Requirements

### Requirement: Key loaded from environment or kernel keyring
Before migration to per-entity custody, the `StateEncryptor` SHALL load the encryption key from the environment variable named by `key_env_var` (default `KAINE_STATE_KEY`), falling back to the Linux kernel keyring, and SHALL raise a configuration error at startup if `enabled` is true and neither source provides a key. After migration, entity state SHALL be encrypted under per-entity keys as defined by `entity-key-custody`, and the operator key sources SHALL be accepted only by the one-way migration tool.

#### Scenario: Key missing with encryption enabled raises error at startup
- **WHEN** a host that has not migrated has `enabled` true and neither `KAINE_STATE_KEY` nor the keyring provides a key
- **THEN** startup raises a `CryptoConfigError` and the entity does not boot

#### Scenario: Operator key after migration
- **WHEN** a migrated host boots with `KAINE_STATE_KEY` set
- **THEN** the runtime ignores it for entity state and logs that per-entity custody is active

### Requirement: Fork/merge export bundles are encrypted
Fork/merge state export bundles SHALL be encrypted before writing to `state/forks/` and decrypted on import. After migration they SHALL be encrypted under the owning entity's data key, and cross-host transfer SHALL use the attested re-wrap defined by `entity-key-custody` instead of an out-of-band key.

#### Scenario: Fork export bundle is encrypted
- **WHEN** a fork export is produced with encryption enabled
- **THEN** the export file is AES-256-GCM encrypted

#### Scenario: Fork import decrypts the bundle
- **WHEN** an encrypted fork bundle is imported on a host that holds its wrapped data key
- **THEN** the state is successfully restored
