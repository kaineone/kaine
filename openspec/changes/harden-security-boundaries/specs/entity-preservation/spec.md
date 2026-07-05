## ADDED Requirements

### Requirement: Fork/merge snapshot ids are validated before path resolution

The system SHALL treat fork/merge snapshot ids received from any request boundary
as untrusted input. A snapshot id SHALL match the strict pattern
`^[0-9a-f]{16}(\+[0-9a-f]{16})?$` before use, and the resolved snapshot path SHALL
be confirmed to remain within the configured snapshot root. An id that fails
either check SHALL be rejected (HTTP 422 at the API boundary) and SHALL NOT reach
`load_snapshot`.

This is defense in depth: the validation SHALL be enforced both at the request
endpoint and at the path-builder (`snapshot_dir` / `snapshot_path`), so a future
caller cannot bypass it.

#### Scenario: Absolute-path id is rejected

- **WHEN** a fork request supplies a `parent_id` that is an absolute path or
  contains `..` or a path separator
- **THEN** the request is rejected with HTTP 422
- **AND** no file outside the snapshot root is read

#### Scenario: Valid id still resolves

- **WHEN** a fork request supplies a well-formed 16-hex-character id that exists
- **THEN** the snapshot loads normally

#### Scenario: Path-builder rejects an escaping id even if the endpoint is bypassed

- **WHEN** `snapshot_path` is called with an id whose resolved path leaves the root
- **THEN** it raises rather than returning a path outside the root
