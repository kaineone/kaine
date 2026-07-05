# experiment-foundation Specification

## Purpose
TBD - created by archiving change experiment-run-identity. Update Purpose after archive.
## Requirements
### Requirement: Global seed control
The system SHALL provide `set_global_seed(seed)` that pins the `random` and
`numpy` global RNGs and, when available, the `torch` RNG, and returns the seed
used. It SHALL NOT fail when `torch` is absent or CPU-only.

#### Scenario: Seeding is reproducible
- **WHEN** `set_global_seed(n)` is called and a sequence of `random`/`numpy` draws is taken, then `set_global_seed(n)` is called again and the same draws are taken
- **THEN** the two draw sequences are identical

#### Scenario: Torch absence does not fail
- **WHEN** `set_global_seed(n)` runs in an environment without torch (or CPU-only torch)
- **THEN** it completes without raising and still returns `n`

### Requirement: Per-run identity and manifest
The cycle SHALL mint a `RunContext` at startup carrying a unique `run_id`, the
`seed` used, `started_at`, a best-effort `git_sha`, the configured `model_ids`,
a `config_digest`, and the kaine version, and SHALL make it available
process-globally via `get_run_context()`. When `[experiment].write_manifest` is
true the cycle SHALL write the context to
`data/evaluation/runs/<run_id>/manifest.json`. `get_run_context()` SHALL return
`None` when no run has been started (the library/unit-test default).

#### Scenario: Fresh seed is generated and recorded when unset
- **WHEN** `[experiment].seed` is blank and the cycle boots
- **THEN** a seed is generated, passed to `set_global_seed`, and recorded in the run manifest

#### Scenario: git_sha falls back without raising
- **WHEN** the git commit cannot be determined (no git / detached / timeout)
- **THEN** the `RunContext` has `git_sha = None` and no exception propagates

#### Scenario: Manifest is export-eligible and content-free
- **WHEN** a research metrics bundle is built
- **THEN** files under the `runs` directory are eligible for inclusion
- **AND** the manifest contains only run_id, seed, git_sha, model_ids, config_digest, started_at, and version — no entity interior content

### Requirement: Durable records carry run identity
When a run context is set, every record written through `AsyncJsonlSink` SHALL
carry the run's `run_id` and a per-sink monotonic `seq`. When no run context is
set, records SHALL NOT be modified (no `run_id`/`seq` added).

#### Scenario: Records are stamped within a run
- **WHEN** a run context is set and two records are written to a sink
- **THEN** both records carry the same `run_id` and `seq` values 0 and 1

#### Scenario: Records are untouched outside a run
- **WHEN** no run context is set and a record is written to a sink
- **THEN** the written record contains neither `run_id` nor `seq`

### Requirement: Shared verdict schema
The system SHALL provide a shared `Verdict` schema (outcome in WIN / NULL /
NEGATIVE for comparative experiments and PASS / FAIL for safety gates, plus an
optional detail string and metrics map) with a stable serialization, and the
active-inference benchmark and enforcement red-team reports SHALL include a
`verdict` field using it without removing their existing fields.

#### Scenario: Experiments emit the shared verdict
- **WHEN** the AIF benchmark and the red-team each emit their report
- **THEN** each report contains a `verdict` object whose `outcome` is one of the shared schema's values

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

