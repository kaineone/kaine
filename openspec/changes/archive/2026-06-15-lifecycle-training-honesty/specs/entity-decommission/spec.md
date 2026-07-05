## ADDED Requirements

### Requirement: Backup encryption failure reports ok=False

`capture_backup` SHALL return `BackupResult(ok=False, encryption_failed=True)`
when state encryption is enabled and the encryption step throws. Returning
`ok=True` in this case is a silent security downgrade: the operator may proceed
to delete entity state believing an encrypted backup exists, when in fact a
plaintext bundle is on disk.

`BackupResult` SHALL carry an `encryption_failed: bool` field (default `False`)
that is `True` only when encryption was enabled and failed. It is `False` when
encryption was disabled by configuration (ordinary plaintext, not a failure).

#### Scenario: Encryption enabled and fails → ok=False

- **WHEN** state encryption is enabled (encryptor.enabled is True)
- **AND** the encryption step raises an exception
- **THEN** `capture_backup` returns `BackupResult(ok=False, encryption_failed=True)`
- **AND** the error is recorded in `result.errors`
- **AND** `result.encrypted` is `False`

#### Scenario: Encryption disabled → ok=True, encryption_failed=False

- **WHEN** state encryption is disabled (encryptor.enabled is False or no encryptor)
- **THEN** `capture_backup` returns `ok=True, encryption_failed=False`
  (plaintext bundle is the honest outcome)

### Requirement: Qdrant get_collections probe failure is recorded and deletion skipped

When `client.get_collections()` raises, `delete_entity_state` SHALL:

1. Record the failure in `result.errors` with a message identifying it as a
   probe failure and noting that collection existence could not be confirmed.
2. Log a warning at WARNING level.
3. Skip all per-collection `delete_collection` calls for that client.

Proceeding as if all expected collections are present (the previous behaviour)
hides the probe failure from the result and may attempt to delete collections
whose existence cannot be verified.

#### Scenario: Probe failure records error and skips deletion

- **WHEN** `client.get_collections()` raises (network error, auth failure, etc.)
- **THEN** `result.errors` contains a message referencing the probe failure
- **AND** `result.dropped_collections` is empty (no collections deleted)

#### Scenario: Probe success deletes matching collections

- **WHEN** `client.get_collections()` succeeds
- **THEN** collections present in both the expected set and the returned set
  are deleted normally
- **AND** no probe-failure error appears in `result.errors`
