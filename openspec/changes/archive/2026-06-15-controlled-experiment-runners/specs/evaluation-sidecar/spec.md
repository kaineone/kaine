# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## ADDED Requirements

### Requirement: Controlled offline runners for the passive instruments
The system SHALL provide a controlled, seeded, offline runner for each of the A/B-divergence, memory-coherence, and self-model (Eidolon) instruments. Each runner SHALL execute a FIXED stimulus battery against the instrument's production control seam and emit a shared-schema `Verdict` plus seeded JSONL. Each runner SHALL call `set_global_seed(seed)` at the start of a run so that, given the same seed and battery, the verdict and reported metrics are reproducible. Each runner SHALL run headless without an entity boot and without attaching to live modules, the network, or any external service — using deterministic / echo clients and an in-memory Mnemos only. Each runner SHALL expose a `__main__` CLI accepting at least `--seed` and `--out`.

#### Scenario: Each runner emits a verdict on its battery

- **WHEN** any of the three runners is invoked on its fixed stimulus battery
- **THEN** it emits a shared-schema `Verdict` (WIN or NULL) with the per-case
  measurements carried in the verdict's metrics and written to JSONL

#### Scenario: A seeded run reproduces

- **WHEN** a runner is invoked twice with the same seed and battery
- **THEN** the verdict and the reported metrics are identical across the two
  invocations (the wall-clock timestamp excepted)

#### Scenario: The A/B runner shows dynamic range

- **WHEN** the A/B-divergence runner executes its battery containing both
  empty-conditioning cases and heavy-conditioning cases through `divergence_control`
- **THEN** every empty-conditioning case reports divergence approximately 0
- **AND** every heavy-conditioning case reports divergence above the configured
  floor
- **AND** the verdict is WIN only when both hold (the meter has dynamic range)

#### Scenario: The memory runner's advantage is retrieval

- **WHEN** the memory-coherence runner runs its planted-fact battery through a
  full-system retrieval arm and a bare arm, then re-runs the SAME full-system client
  against an EMPTIED Mnemos as a recorded check
- **THEN** with the facts planted, the full-system arm's accuracy exceeds the bare
  arm's by at least the configured floor
- **AND** a never-stored fact yields honest non-recall scored 0
- **AND** with the Mnemos emptied the full-system advantage vanishes, proving the
  advantage is produced by retrieval and not a hard-coded answer

#### Scenario: The self-model runner validates the scorer

- **WHEN** the self-model runner runs its battery of planted-signal / claim cases
  through the calibrated Eidolon scorer
- **THEN** the verdict reports the scorer's accuracy on the known cases
- **AND** the record states that this validates the scorer's
  trait-keyword-vs-derived-signal arithmetic, not predicted-vs-actual self-knowledge

#### Scenario: Offline, no entity boot

- **WHEN** any of the three runners is invoked
- **THEN** it uses only deterministic / echo clients and an in-memory Mnemos over
  no network
- **AND** it does NOT boot an entity, attach to live modules, or open a network
  connection
