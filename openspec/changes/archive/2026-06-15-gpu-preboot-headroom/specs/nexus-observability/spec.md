## ADDED Requirements

### Requirement: GPU pre-flight status is surfaced read-only

The Nexus health snapshot SHALL include a read-only `gpu_preflight` block derived
from the last pre-flight verdict, reporting only non-content operational data:
per-device VRAM, evicted/loaded model ids, GPU process names, the KAINE services
detected, and an operator state. The block SHALL never raise; a missing or corrupt
pre-flight record SHALL yield state `unknown`. Nexus SHALL NOT expose any control
that terminates a process from this block.

#### Scenario: Blocked pre-flight surfaces as critical

- **WHEN** the last pre-flight recorded a `blocked` verdict
- **THEN** the `gpu_preflight` block reports state `critical` with the per-device
  shortfall

#### Scenario: No pre-flight record is unknown, not an error

- **WHEN** no pre-flight record exists
- **THEN** the `gpu_preflight` block reports state `unknown`
- **AND** the snapshot is produced without error
