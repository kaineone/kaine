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
