# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## ADDED Requirements

### Requirement: Controlled offline oscillatory-ablation runner
The system SHALL provide a controlled, offline oscillatory-ablation runner that
executes the cognitive cycle twice under identical conditions — the same global
seed, the same fixed scripted input, and deterministic mode — differing only in
whether the oscillatory coherence layer is enabled (a real `CoherenceScorer`
with configurable precision gain) or disabled (`coherence=None`, the layer-absent
baseline). The runner SHALL run headless without an entity boot and without
attaching to live modules, the network, or any external service. It SHALL emit a
verdict reporting the measured effect of precision modulation on selection: WIN
when selection is measurably changed by the layer above a configurable floor, and
NULL otherwise, with the effect size carried in the verdict's metrics.

#### Scenario: Enabled-vs-disabled run is reproducible
- **WHEN** the runner is invoked twice with the same seed, stimulus, and gain
- **THEN** the verdict and the reported effect metrics are identical across the two invocations

#### Scenario: Difference is attributable to the layer alone
- **WHEN** the enabled and disabled arms are run
- **THEN** both arms use the same seed, the same scripted input, and deterministic mode
- **AND** the only difference between the arms is the presence of the coherence layer

#### Scenario: A non-trivial stimulus yields a measurable effect
- **WHEN** the runner is given a stimulus in which phase-locked sources and
  desynchronized sources compete and the coherence layer is enabled at a precision
  gain sufficient to re-rank them
- **THEN** the verdict is WIN
- **AND** the reported effect size (selection-divergence fraction) is greater than zero

#### Scenario: The disabled arm matches the layer-absent baseline
- **WHEN** the runner executes the disabled arm
- **THEN** its per-tick trajectory is bit-for-bit identical to a cycle run with no
  coherence layer at all (the layer-absent baseline)

#### Scenario: No measurable difference is reported as null
- **WHEN** the enabled and disabled arms produce identical selection trajectories
- **THEN** the verdict is NULL
- **AND** the reported effect size is zero

#### Scenario: Offline, no entity boot
- **WHEN** the runner is invoked
- **THEN** it drives only the cycle engine and Syneidesis over a scripted in-memory bus
- **AND** it does NOT boot an entity, attach to live modules, or open a network connection
