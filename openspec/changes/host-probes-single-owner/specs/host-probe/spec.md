## ADDED Requirements

### Requirement: Host memory has one owner
System memory figures SHALL come from `kaine.hostmem.system_memory_pool()`, which SHALL try `/proc/meminfo`, then psutil, then POSIX `sysconf` for the total. Any other reader of total system RAM SHALL use that pool rather than probing on its own. A figure that no source reports SHALL be `None` with an unknown reason, never zero.

#### Scenario: sysconf supplies the total when the others fail
- **WHEN** `/proc/meminfo` is unreadable and psutil is unavailable
- **THEN** the pool reports the total from `sysconf`
- **AND** its available figure is `None` with an unknown reason

#### Scenario: The tier probe reads the same figure
- **WHEN** the host probe reports total RAM
- **THEN** it equals the system pool's total, in GiB

### Requirement: The GPU preflight probes the host once per run
The GPU preflight SHALL take one host snapshot per run and SHALL use it for both the per-device VRAM figures and the memory-state classification.

#### Scenario: One snapshot
- **WHEN** the preflight runs with the gate enabled
- **THEN** `describe_host()` is called exactly once
