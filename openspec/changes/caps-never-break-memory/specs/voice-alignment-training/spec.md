## MODIFIED Requirements

### Requirement: Adapter retention bounded
Accepted adapters are the entity's learned voice, so infrastructure SHALL NOT
cull them by default. `[hypnos.voice_alignment].adapter_retention` SHALL ship
as `0` (and default to `0` when absent), meaning every accepted adapter under
`adapter_output_dir` is kept. A positive value SHALL keep at most that many
accepted adapters: older accepted adapters SHALL be evicted after every
successful promotion. A negative value SHALL be rejected. The `current`
symlink is never evicted. Disk space for adapters is checked before boot by the
pre-boot disk-free rows, not by deletion.

#### Scenario: Eviction on overflow
- **WHEN** 6 adapters are accepted in sequence and retention is 5
- **THEN** only the 5 most-recent timestamp directories remain;
  `current` points at the newest

#### Scenario: Default keeps every adapter
- **WHEN** retention is 0 and an adapter is accepted while 8 older accepted
  adapters exist
- **THEN** all 9 adapter directories remain

#### Scenario: Negative retention is rejected
- **WHEN** a voice-alignment config is built with `adapter_retention = -1`
- **THEN** construction raises `ValueError`
