# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## ADDED Requirements

### Requirement: Multi-seed stability harness
The system SHALL provide a reusable, boundary-neutral multi-seed stability harness
— the longitudinal / multi-run control — that runs an experiment across several
seeds and reports summary statistics and a stability verdict. The harness SHALL
take a callable `run_fn(seed)` and a `metric_fn` (it SHALL NOT depend on
`kaine.evaluation`, so both the core cycle and the evaluation sidecar may use it),
run `run_fn` once per seed pinning the global seed before each invocation, and
return a report containing the seeds, the per-seed headline metric values, their
mean and standard deviation, their coefficient of variation (`std / |mean|`), the
distribution of verdict outcomes across seeds, and a stability boolean. The
ensemble SHALL be reported stable when the coefficient of variation is within a
configured tolerance AND the verdict is unanimous across seeds; it SHALL be
reported unstable otherwise. The report SHALL expose human-readable reasons for its
stability verdict, and the harness SHALL provide an assertion helper that raises an
error carrying those reasons when the ensemble is not stable. This is the
multi-seed analog of the bit-for-bit seed-determinism guarantee: it demonstrates
that N seeds are enough for nondeterminism to wash out.

#### Scenario: A stable experiment across seeds yields a stable report
- **WHEN** the harness runs an experiment whose headline metric varies across
  seeds within the configured tolerance and whose verdict is the same on every seed
- **THEN** the report's coefficient of variation is within tolerance
- **AND** the verdict distribution records a single unanimous outcome
- **AND** the report is stable

#### Scenario: A deliberately unstable metric is reported unstable
- **WHEN** the harness runs an experiment whose headline metric swings beyond the
  configured tolerance across seeds
- **THEN** the report's coefficient of variation exceeds the tolerance
- **AND** the report is not stable
- **AND** the report's reasons state that the metric varies too much across seeds

#### Scenario: Verdict unanimity is captured and gates stability
- **WHEN** the harness runs an experiment whose headline metric is stable across
  seeds but whose verdict outcome differs between seeds
- **THEN** the verdict distribution records more than one outcome
- **AND** the report is not unanimous
- **AND** the report is not stable even though the metric coefficient of variation
  is within tolerance

#### Scenario: The assertion helper fails honestly on an unstable ensemble
- **WHEN** the assertion helper is invoked on an experiment that is not stable
- **THEN** it raises an error
- **AND** the error carries the report's reasons explaining why the ensemble is
  unstable

#### Scenario: Demonstrated on a real experiment, offline
- **WHEN** the harness runs the oscillatory-ablation runner across several seeds
  with few ticks
- **THEN** the report's verdict distribution is a unanimous WIN
- **AND** the effect metric's coefficient of variation is within tolerance
- **AND** the report is stable
- **AND** no entity is booted, no live module is attached, and no network
  connection is opened
