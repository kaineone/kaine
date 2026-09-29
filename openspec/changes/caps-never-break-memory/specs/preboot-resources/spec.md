## ADDED Requirements

### Requirement: Pre-boot report has a WARN status
The pre-boot report SHALL support a WARN status alongside PASS, FAIL and SKIP. A WARN row SHALL NOT fail the gate, and the verdict line SHALL count WARN rows.

#### Scenario: Warnings do not fail the gate
- **WHEN** the report holds PASS and WARN rows and no FAIL row
- **THEN** the verdict is PASS and the warning count is shown

### Requirement: Bus memory budget row
`python -m kaine.preboot` SHALL report a "Bus budget" row. The budget SHALL be the sum, over the streams the run produces, of the stream's configured maxlen times its typical event size from `kaine/bus/config.py`, multiplied by 2 for AOF-rewrite headroom. The streams SHALL be `workspace.broadcast` and `cycle.out`, the `<module>.out` stream of every enabled module, `lingua.internal` and `lingua.external` when Lingua is enabled, and `volition.out` and `volition_feedback.out` when Nous is enabled. The budget SHALL be compared with the server's `maxmemory`, read through the bus client with `CONFIG GET maxmemory`.

The row SHALL be FAIL when the budget exceeds `maxmemory`, WARN when it exceeds 70% of `maxmemory`, and PASS otherwise. When `maxmemory` cannot be read, the row SHALL be WARN with the reason. When `maxmemory` is 0 (no limit), the row SHALL be WARN and state the budget. A FAIL or WARN detail SHALL name `KAINE_REDIS_MAXMEMORY` as the setting to raise.

#### Scenario: Budget fits
- **WHEN** the budget is 1 GB and `maxmemory` is 4 GB
- **THEN** the row is PASS

#### Scenario: Budget close to the cap
- **WHEN** the budget is 3 GB and `maxmemory` is 4 GB
- **THEN** the row is WARN

#### Scenario: Budget over the cap
- **WHEN** the budget is 5 GB and `maxmemory` is 4 GB
- **THEN** the row is FAIL

#### Scenario: maxmemory unreadable
- **WHEN** the bus client cannot read `maxmemory`
- **THEN** the row is WARN and gives the reason

### Requirement: Disk free rows
`python -m kaine.preboot` SHALL report a "Disk free" row for the state root, the data root and, when it exists, the native Redis data directory (`<state root>/services/redis/data`). Each row SHALL be FAIL when free space is below the larger of `disk_fail_min_free_gb` and `disk_fail_min_free_percent` of the filesystem, WARN when free space is below `disk_warn_min_free_gb`, and PASS otherwise. When the native Redis data directory does not exist, its row SHALL be SKIP and say that a container volume is not measured. The thresholds and roots SHALL be keys in a `[preboot]` table with the defaults `state_root = "state"`, `data_root = "data"`, `disk_fail_min_free_gb = 10.0`, `disk_fail_min_free_percent = 5.0` and `disk_warn_min_free_gb = 20.0`. An unknown key or a non-numeric threshold in `[preboot]` SHALL produce a FAIL row naming the problem.

#### Scenario: Plenty of space
- **WHEN** a root's filesystem has 100 GB free of 500 GB
- **THEN** its row is PASS

#### Scenario: Low but above the floor
- **WHEN** a root's filesystem has 15 GB free of 100 GB
- **THEN** its row is WARN

#### Scenario: Below the floor
- **WHEN** a root's filesystem has 8 GB free of 100 GB
- **THEN** its row is FAIL

#### Scenario: Percentage floor on a large disk
- **WHEN** a root's filesystem has 40 GB free of 1000 GB
- **THEN** its row is FAIL because 40 GB is below 5% of the filesystem
