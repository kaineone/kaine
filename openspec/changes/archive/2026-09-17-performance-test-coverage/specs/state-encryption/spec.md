## ADDED Requirements

### Requirement: State-encryption boot wiring is tested end-to-end
`build_registry` SHALL be tested with `[security.state_encryption].enabled=true` both without a key (fail-closed) and with a key (successful install and round-trip).

#### Scenario: Boot fails closed without a key
- **WHEN** `build_registry` is called with encryption enabled and neither `KAINE_STATE_KEY` nor the keyring provides a key
- **THEN** a `CryptoConfigError` is raised before any module is initialized

#### Scenario: Boot installs encryptor with a key
- **WHEN** `build_registry` is called with encryption enabled and `KAINE_STATE_KEY` set to a valid 32-byte key
- **THEN** `get_state_encryptor().enabled` is true and an encrypt/decrypt round-trip succeeds
