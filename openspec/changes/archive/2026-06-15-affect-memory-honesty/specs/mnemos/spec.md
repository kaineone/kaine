## ADDED Requirements

### Requirement: Mnemos recall does not fabricate empty success on storage failure

`QdrantStorage.search()` SHALL raise `StorageError` (not return `[]`) when
the Qdrant backend operation fails.  `Mnemos.recall()` SHALL catch
`StorageError`, log it at `error` level, and publish a `mnemos.recall` event
carrying `"error": true` and `"error_detail"` — never a fake `count=0` result
that looks like a successful empty search.

`InMemoryStorage.search()` is unaffected: missing collections return `[]`
normally (that is a valid empty result, not a storage failure).

#### Scenario: Qdrant backend failure

- **WHEN** `QdrantStorage.search()` encounters any exception from the client
- **THEN** it raises `StorageError` with a descriptive message
- **AND** does NOT return `[]`

#### Scenario: Mnemos recall on StorageError

- **WHEN** `Mnemos.recall()` encounters a `StorageError`
- **THEN** it logs the error at `logging.ERROR` level
- **AND** publishes `mnemos.recall` with `"error": true`
- **AND** returns `[]` to the caller (graceful empty, not a fake success)
- **AND** the published event does NOT carry `"error": true` on a successful recall

#### Scenario: Successful recall

- **WHEN** `Mnemos.recall()` completes without error
- **THEN** `mnemos.recall` is published with real `count` and no `"error"` key
