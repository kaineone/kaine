## ADDED Requirements

### Requirement: Pre-boot report has a WARN status
The pre-boot report SHALL support a WARN status alongside PASS, FAIL and SKIP. A WARN row SHALL NOT fail the gate, and the verdict line SHALL count WARN rows.

#### Scenario: Warnings do not fail the gate
- **WHEN** the report holds PASS and WARN rows and no FAIL row
- **THEN** the verdict is PASS and the warning count is shown

### Requirement: Bus memory budget row
`python -m kaine.preboot` SHALL report a "Bus budget" row. The budget SHALL be the sum, over the streams the run produces, of the stream's configured maxlen times its per-entry size, multiplied by 2 for AOF-rewrite headroom. The streams SHALL be `workspace.broadcast` and `cycle.out`, the `<module>.out` stream of every enabled module, `lingua.internal` and `lingua.external` when Lingua is enabled, and `volition.out` and `volition_feedback.out` when Nous is enabled. A stream's per-entry size SHALL be measured from the running bus (`MEMORY USAGE` divided by `XLEN` for a stream holding at least 100 entries) when possible, else taken from the measured table in `kaine/bus/config.py`, else the 2 KB estimate. The budget SHALL be compared with the server's `maxmemory`, read through the bus client with `CONFIG GET maxmemory`.

The row SHALL be FAIL only when the measured streams alone (live or table sizes, with headroom) exceed `maxmemory`. When the budget exceeds `maxmemory` only because of streams at the 2 KB estimate, the row SHALL be WARN and SHALL name those streams. The row SHALL be WARN when the budget exceeds 70% of `maxmemory`, and PASS otherwise. When `maxmemory` cannot be read, the row SHALL be WARN with the reason. When `maxmemory` is 0 (no limit), the row SHALL be WARN and state the budget. A FAIL or WARN detail SHALL name `KAINE_REDIS_MAXMEMORY` as the setting to raise.

#### Scenario: Budget fits
- **WHEN** the budget is 1 GB and `maxmemory` is 4 GB
- **THEN** the row is PASS

#### Scenario: Budget close to the cap
- **WHEN** the budget is 1 GB of measured streams and `maxmemory` is 1.2 GB
- **THEN** the row is WARN

#### Scenario: Measured streams over the cap
- **WHEN** the measured streams alone need 1 GB and `maxmemory` is 0.5 GB
- **THEN** the row is FAIL

#### Scenario: Overage only through estimates
- **WHEN** the measured streams fit but a stream at the 2 KB estimate pushes the budget over `maxmemory`
- **THEN** the row is WARN and names that stream

#### Scenario: A live sample confirms the overage
- **WHEN** the same stream is sampled from the running bus at the same size
- **THEN** the row is FAIL

#### Scenario: maxmemory unreadable
- **WHEN** the bus client cannot read `maxmemory`
- **THEN** the row is WARN and gives the reason

### Requirement: Disk free rows
`python -m kaine.preboot` SHALL report free disk for every configured durable path, resolved from the same keys and defaults the modules use: `[preboot].state_root` and `data_root`, `[lifecycle].snapshots_path`, `[preservation.divergence_monitor].out_root` and `[preservation.welfare_response].out_root`, `[evaluation.paths].trajectory_dir` and `evaluation_logs`, `[research_event_log].log_dir` and `[research_event_log.raw_archive].archive_dir`, `[hypnos.voice_alignment].adapter_output_dir` and `trainer_workdir`, `[ignition_log].directory`, `[spot.incident_log].path`, the directory of `[eidolon].persistence_path`, and the native Redis data directory (`<state root>/services/redis/data`) when it exists. A path that does not exist yet SHALL be measured at its nearest existing parent. Paths on the same filesystem SHALL share one "Disk free" row that lists them. Each row SHALL be FAIL when free space is below the larger of `disk_fail_min_free_gb` and `disk_fail_min_free_percent` of the filesystem, WARN when free space is below `disk_warn_min_free_gb`, and PASS otherwise. When the native Redis data directory does not exist, a "Disk free (Redis data)" row SHALL be SKIP and say that a container volume is not measured. The thresholds and roots SHALL be keys in a `[preboot]` table with the defaults `state_root = "state"`, `data_root = "data"`, `disk_fail_min_free_gb = 10.0`, `disk_fail_min_free_percent = 5.0` and `disk_warn_min_free_gb = 20.0`. An unknown key or a non-numeric threshold in `[preboot]` SHALL produce a FAIL row naming the problem.

#### Scenario: Plenty of space
- **WHEN** the filesystem holding the durable paths has 100 GB free of 500 GB
- **THEN** its row is PASS

#### Scenario: Low but above the floor
- **WHEN** it has 15 GB free of 100 GB
- **THEN** its row is WARN

#### Scenario: Below the floor
- **WHEN** it has 8 GB free of 100 GB
- **THEN** its row is FAIL

#### Scenario: Percentage floor on a large disk
- **WHEN** it has 40 GB free of 1000 GB
- **THEN** its row is FAIL because 40 GB is below 5% of the filesystem

#### Scenario: A durable path on another filesystem
- **WHEN** the preservation out_root is on a separate filesystem with 5 GB free of 100 GB
- **THEN** that filesystem has its own FAIL row listing the out_root, and the other paths share a PASS row
