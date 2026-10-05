# host-probe Specification

## Purpose
The host-probe capability inspects the host's RAM, CPU architecture, accelerator availability, and PyTorch importability to recommend a matching capability-matrix tier, without applying that tier to the running configuration.

## Requirements

### Requirement: A host probe recommends a tier without applying it

The system SHALL provide a host-capability probe that reports total RAM, CPU
architecture, CUDA/MPS availability, and whether the PyTorch runtime imports
successfully, and maps those to a recommended tier with the matching
capability-matrix row. The probe SHALL recommend only; it SHALL NOT apply a
profile or start the entity, consistent with operator-supervised boot.

#### Scenario: Probe recommends a tier from host capabilities

- **WHEN** the host probe is run
- **THEN** it reports RAM, CPU architecture, accelerator presence, and torch
  importability
- **AND** it prints a recommended tier and that tier's capability-matrix row
- **AND** it does not apply a profile or start the entity

#### Scenario: A torch-incapable low-RAM host is recommended Tier 0

- **WHEN** the probe runs on a host where torch does not import or RAM is below
  the Tier-1 threshold
- **THEN** the recommended tier is Tier 0 (symbolic-reasoning + memory + sensor
  node), not a multimodal tier

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
