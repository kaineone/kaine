# experiment-foundation (delta)

## ADDED Requirements

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
