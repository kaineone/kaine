## ADDED Requirements

### Requirement: The Praxis audit log is tamper-evident

The Praxis audit log SHALL be tamper-evident, not merely append-only. Each record
SHALL carry a hash chained to the previous record
(`this_hash = sha256(prev_hash || canonical(record))`), and the system SHALL
provide a verifier that detects any edit, reordering, or truncation of historical
records and reports the first break.

#### Scenario: Edited history is detected

- **WHEN** a historical audit record is altered or removed on disk
- **THEN** the chain verifier reports a break at that record

### Requirement: Praxis audit and sandbox files are owner-only

Praxis SHALL create the audit log and the filesystem sandbox owner-only — mode
0600 for files and mode 0700 for directories — regardless of the ambient umask,
matching the preservation snapshot hardening.

#### Scenario: Files are not group/world readable under a permissive umask

- **WHEN** the audit log and sandbox are created under umask `0002`
- **THEN** the audit log is mode `0600` and the sandbox directory is mode `0700`
