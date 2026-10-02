## ADDED Requirements

### Requirement: Research records are kept by default

`retention_days` SHALL ship as `0` in `[evaluation.paths]`,
`[research_event_log]` and `[research_event_log.raw_archive]`, and the matching
configuration dataclasses SHALL default to `0` when the key is absent. A value of
`0` or less SHALL disable the age-based purge, so no daily file is deleted
automatically. A positive value SHALL still purge daily files older than that
many days. Disk space is checked before boot by the pre-boot disk-free rows
instead of by deleting records.

#### Scenario: Shipped config keeps records

- **WHEN** the committed `config/kaine.toml` is loaded
- **THEN** all three `retention_days` values are `0`

#### Scenario: Absent key keeps records

- **WHEN** the evaluation paths, research event log and raw archive configs are
  built from empty tables
- **THEN** each `retention_days` is `0`

#### Scenario: An old research file survives a sink start

- **WHEN** a sink built with `retention_days = 0` starts in a directory holding a
  daily file older than 30 days
- **THEN** that file remains on disk
