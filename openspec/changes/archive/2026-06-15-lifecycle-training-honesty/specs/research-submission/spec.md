## ADDED Requirements

### Requirement: Bundle.encryption_error distinguishes enabled-but-failed from disabled encryption

`Bundle` SHALL carry an `encryption_error: Optional[str]` field. When
encryption is enabled and the encryption step fails, `_encrypt_bundle` SHALL
set `bundle.encryption_error` to a non-None string describing the failure.
When encryption is disabled by configuration, `encryption_error` SHALL remain
`None`. This allows callers (CLI, API handlers) to distinguish:

- `encrypted=True, encryption_error=None` — encryption succeeded
- `encrypted=False, encryption_error=None` — encryption disabled (ordinary plaintext)
- `encrypted=False, encryption_error=<msg>` — encryption was enabled and failed

The `plaintext_note` field continues to be set for human-readable display in
both the disabled and failed cases (the preview output).

#### Scenario: Encryption enabled and fails → encryption_error set

- **WHEN** state encryption is enabled (encryptor.enabled is True)
- **AND** the encryption step raises an exception
- **THEN** `bundle.encryption_error` is a non-None string describing the failure
- **AND** `bundle.encrypted` is `False`
- **AND** `bundle.plaintext_note` is also set

#### Scenario: Encryption disabled → encryption_error is None

- **WHEN** state encryption is disabled
- **THEN** `bundle.encryption_error` is `None`
- **AND** `bundle.encrypted` is `False`

#### Scenario: Encryption succeeds → encryption_error is None

- **WHEN** encryption succeeds
- **THEN** `bundle.encryption_error` is `None`
- **AND** `bundle.encrypted` is `True`
